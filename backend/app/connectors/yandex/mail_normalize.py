from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any

from app.connectors.email_html_text import html_email_to_plain_text, normalize_plain_email_text
from app.connectors.yandex.constants import MAX_EMAIL_BODY_CHARS
from app.services.client_intake_constants import (
    MAX_EMAIL_ATTACHMENT_BYTES,
    MAX_EMAIL_ATTACHMENT_BYTES_PER_MESSAGE,
    MAX_EMAIL_ATTACHMENTS_PER_MESSAGE,
)


def _strip_html(text: str) -> str:
    return html_email_to_plain_text(text)


def _header_value(msg: Any, name: str) -> str | None:
    value = msg.get(name)
    if value is None:
        return None
    return str(value)


def _parse_addresses(value: str | None) -> list[str]:
    if not value:
        return []
    return [addr for _, addr in getaddresses([value]) if addr]


def _compact_headers(msg: Any) -> dict[str, str]:
    keep = ("message-id", "in-reply-to", "references", "reply-to", "list-id")
    compact: dict[str, str] = {}
    for name in keep:
        value = _header_value(msg, name)
        if value:
            compact[name] = value
    return compact


def _is_attachment_part(part: Any) -> bool:
    return part.get_content_disposition() == "attachment"


def _extract_body(msg: Any) -> str | None:
    if msg.is_multipart():
        plain: str | None = None
        html_body: str | None = None
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if _is_attachment_part(part):
                continue
            content_type = part.get_content_type()
            try:
                payload = part.get_payload(decode=True)
            except TypeError:
                payload = None
            if not payload:
                continue
            decoded = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            if content_type == "text/plain" and plain is None:
                plain = normalize_plain_email_text(decoded)
            elif content_type == "text/html" and html_body is None:
                html_body = decoded
        if plain:
            return plain
        if html_body:
            return _strip_html(html_body)
        return None

    if _is_attachment_part(msg):
        return None

    try:
        payload = msg.get_payload(decode=True)
    except TypeError:
        payload = None
    if not payload:
        return None
    decoded = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    if msg.get_content_type() == "text/html":
        return _strip_html(decoded)
    return normalize_plain_email_text(decoded)


def _parse_timestamp(msg: Any) -> datetime:
    date_header = msg.get("Date")
    if not date_header:
        return datetime.now(UTC)
    try:
        parsed = parsedate_to_datetime(date_header)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    except (TypeError, ValueError):
        return datetime.now(UTC)


def build_external_id(folder: str, uidvalidity: int, uid: int) -> str:
    return f"{folder.lower()}:{uidvalidity}:{uid}"


def normalize_imap_message(
    raw_bytes: bytes,
    folder: str,
    uid: int,
    uidvalidity: int,
) -> dict[str, Any]:
    msg = message_from_bytes(raw_bytes, policy=policy.default)
    subject = _header_value(msg, "Subject")
    sender = _header_value(msg, "From")
    recipients = _parse_addresses(_header_value(msg, "To"))
    cc = _parse_addresses(_header_value(msg, "Cc"))
    timestamp = _parse_timestamp(msg)
    body_text = _extract_body(msg)
    message_id_header = _header_value(msg, "Message-ID")

    metadata = {
        "folder": folder,
        "imap_uid": uid,
        "imap_uidvalidity": uidvalidity,
        "message_id": message_id_header,
        "sender": sender,
        "recipients": recipients,
        "cc": cc,
        "subject": subject,
        "timestamp": timestamp.isoformat(),
        "headers": _compact_headers(msg),
    }

    body = body_text[:MAX_EMAIL_BODY_CHARS] if body_text else None
    external_id = build_external_id(folder, uidvalidity, uid)

    return {
        "external_id": external_id,
        "kind": "email",
        "provider": "yandex_mail",
        "origin": "source",
        "state": "observed",
        "title": subject or f"Yandex message {external_id}",
        "body": body,
        "metadata": metadata,
        "occurred_at": timestamp,
    }


def extract_imap_attachment_descriptors(msg: Any) -> list[dict[str, Any]]:
    descriptors: list[dict[str, Any]] = []
    fetched_total = 0
    part_counter = 0
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        is_attachment = disposition == "attachment" or (
            filename and disposition != "inline"
        )
        if not is_attachment:
            continue
        if len(descriptors) >= MAX_EMAIL_ATTACHMENTS_PER_MESSAGE:
            break
        part_key = f"part-{part_counter}"
        part_counter += 1
        try:
            payload = part.get_payload(decode=True)
        except TypeError:
            payload = None
        payload_len = len(payload) if isinstance(payload, bytes) else 0
        known_size = payload_len or None
        content_id = part.get("Content-ID")
        descriptor: dict[str, Any] = {
            "part_key": part_key,
            "filename": filename or "attachment",
            "mime_type": part.get_content_type(),
            "size": known_size,
            "content_id": str(content_id) if content_id else None,
        }
        remaining = MAX_EMAIL_ATTACHMENT_BYTES_PER_MESSAGE - fetched_total
        if (
            isinstance(payload, bytes)
            and payload_len > 0
            and payload_len <= MAX_EMAIL_ATTACHMENT_BYTES
            and payload_len <= remaining
        ):
            descriptor["inline_bytes"] = payload
            fetched_total += payload_len
        descriptors.append(descriptor)
    return descriptors
