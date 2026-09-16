import base64
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Any

from app.connectors.email_html_text import html_email_to_plain_text, normalize_plain_email_text
from app.connectors.google.constants import GMAIL_READONLY_SCOPE, MAX_EMAIL_BODY_CHARS
from app.services.client_intake_constants import (
    MAX_EMAIL_ATTACHMENTS_PER_MESSAGE,
)


def _header_value(headers: list[dict[str, Any]], name: str) -> str | None:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            value = header.get("value")
            return str(value) if value is not None else None
    return None


def _parse_addresses(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [part.strip() for part in value.split(",")]
    addresses: list[str] = []
    for part in parts:
        _, addr = parseaddr(part)
        if addr:
            addresses.append(addr)
    return addresses


def _decode_body_data(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    return raw.decode("utf-8", errors="replace")


def _strip_html(text: str) -> str:
    return html_email_to_plain_text(text)


def _part_headers(part: dict[str, Any]) -> dict[str, str]:
    headers = part.get("headers") or []
    compact: dict[str, str] = {}
    for header in headers:
        name = str(header.get("name", "")).lower()
        if header.get("value"):
            compact[name] = str(header["value"])
    return compact


def _is_gmail_attachment_part(part: dict[str, Any]) -> bool:
    body = part.get("body") or {}
    if body.get("attachmentId"):
        return True
    headers = _part_headers(part)
    disposition = headers.get("content-disposition", "").lower()
    return disposition.startswith("attachment")


def _collect_text_parts(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    if _is_gmail_attachment_part(payload):
        return None, None
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {})
    data = body.get("data")
    plain: str | None = None
    html_body: str | None = None

    if data:
        decoded = _decode_body_data(str(data))
        if mime_type == "text/plain":
            plain = normalize_plain_email_text(decoded)
        elif mime_type == "text/html":
            html_body = decoded

    for part in payload.get("parts", []):
        if _is_gmail_attachment_part(part):
            continue
        nested_plain, nested_html = _collect_text_parts(part)
        if nested_plain and plain is None:
            plain = nested_plain
        if nested_html and html_body is None:
            html_body = nested_html

    return plain, html_body


def extract_gmail_attachment_descriptors(payload: dict[str, Any]) -> list[dict[str, Any]]:
    descriptors: list[dict[str, Any]] = []

    def walk(part: dict[str, Any], path_prefix: str = "") -> None:
        part_id = str(part.get("partId") or path_prefix or len(descriptors))
        body = part.get("body") or {}
        headers = _part_headers(part)
        filename = part.get("filename") or headers.get("filename")
        attachment_id = body.get("attachmentId")
        inline_data = body.get("data")
        is_attachment = _is_gmail_attachment_part(part) or (
            filename and (attachment_id is not None or inline_data)
        )
        if not is_attachment:
            for child in part.get("parts", []):
                child_prefix = f"{part_id}.{len(descriptors)}"
                walk(child, child_prefix)
            return

        attachment_key = str(attachment_id) if attachment_id else f"inline:{part_id}"
        inline_bytes: bytes | None = None
        if inline_data and not attachment_id:
            padded = str(inline_data) + "=" * (-len(str(inline_data)) % 4)
            inline_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))

        descriptors.append(
            {
                "attachment_key": attachment_key,
                "attachment_id": attachment_id,
                "part_id": part_id,
                "filename": str(filename or "attachment"),
                "mime_type": part.get("mimeType"),
                "size": body.get("size") or (
                    len(inline_bytes) if inline_bytes is not None else None
                ),
                "content_id": headers.get("content-id"),
                "inline_bytes": inline_bytes,
            }
        )
        for child in part.get("parts", []):
            child_prefix = f"{part_id}.{len(descriptors)}"
            walk(child, child_prefix)

    walk(payload)
    return descriptors[:MAX_EMAIL_ATTACHMENTS_PER_MESSAGE]


def _extract_body(payload: dict[str, Any]) -> str | None:
    plain, html_body = _collect_text_parts(payload)
    if plain:
        return plain
    if html_body:
        return _strip_html(html_body)
    return None


def _compact_headers(headers: list[dict[str, Any]]) -> dict[str, str]:
    keep = ("message-id", "in-reply-to", "references", "reply-to", "list-id")
    compact: dict[str, str] = {}
    for header in headers:
        name = str(header.get("name", "")).lower()
        if name in keep and header.get("value"):
            compact[name] = str(header["value"])
    return compact


def normalize_gmail_message(message: dict[str, Any]) -> dict[str, Any]:
    message_id = str(message.get("id", ""))
    payload = message.get("payload", {})
    headers = payload.get("headers", [])
    internal_ms = message.get("internalDate")
    if internal_ms is not None:
        timestamp = datetime.fromtimestamp(int(internal_ms) / 1000, tz=UTC)
    else:
        timestamp = datetime.now(UTC)

    subject = _header_value(headers, "Subject")
    sender = _header_value(headers, "From")
    recipients = _parse_addresses(_header_value(headers, "To"))
    cc = _parse_addresses(_header_value(headers, "Cc"))
    body_text = _extract_body(payload)
    labels = [str(label) for label in message.get("labelIds", [])]

    metadata = {
        "message_id": message_id,
        "thread_id": str(message.get("threadId", "")),
        "sender": sender,
        "recipients": recipients,
        "cc": cc,
        "subject": subject,
        "timestamp": timestamp.isoformat(),
        "headers": _compact_headers(headers),
        "labels": labels,
    }

    body = None
    if body_text:
        body = body_text[:MAX_EMAIL_BODY_CHARS]

    return {
        "external_id": message_id,
        "kind": "email",
        "provider": "gmail",
        "origin": "source",
        "state": "observed",
        "title": subject or f"Gmail message {message_id}",
        "body": body,
        "metadata": metadata,
        "occurred_at": timestamp,
        "scopes": [GMAIL_READONLY_SCOPE],
    }
