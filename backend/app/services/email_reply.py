"""Deterministic email reply routing from a canonical stored message.

Recipient, subject, threading headers, and source account come from the
object envelope and connected accounts. Message body, title instructions,
and display-name text are never routing input.
"""

from __future__ import annotations

from email.utils import getaddresses
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.core.config import settings
from app.services.external_account_resolution import google_has_send_capability
from app.tools.schemas import MAX_EMAIL_SUBJECT_CHARS, ToolError, _normalize_email_address

_MAX_REFERENCES_CHARS = 2000
_MAX_REFERENCES_TOKENS = 20
_MAX_MESSAGE_ID_CHARS = 998


def reply_recipient(metadata: dict[str, Any]) -> str:
    headers = _headers(metadata)
    reply_to = _first_valid_address(headers.get("reply-to"))
    if reply_to is not None:
        return reply_to
    sender = _first_valid_address(metadata.get("sender")) or _first_valid_address(
        headers.get("from")
    )
    if sender is not None:
        return sender
    raise ToolError("canonical reply recipient is unavailable")


def reply_subject(original: object) -> str:
    text = " ".join(str(original or "").replace("\r", " ").replace("\n", " ").split())
    if text.lower().startswith("re:"):
        subject = text
    elif text:
        subject = f"Re: {text}"
    else:
        subject = "Re:"
    if len(subject) > MAX_EMAIL_SUBJECT_CHARS:
        subject = subject[:MAX_EMAIL_SUBJECT_CHARS].rstrip()
    return subject or "Re:"


def reply_message_id(metadata: dict[str, Any]) -> str | None:
    raw = _headers(metadata).get("message-id")
    return _clean_message_id(raw)


def reply_references(metadata: dict[str, Any], message_id: str | None) -> str | None:
    tokens: list[str] = []
    raw = _headers(metadata).get("references") or ""
    for part in str(raw).replace("\r", " ").replace("\n", " ").split():
        cleaned = _clean_message_id(part)
        if cleaned and cleaned not in tokens:
            tokens.append(cleaned)
    if message_id and message_id not in tokens:
        tokens.append(message_id)
    if not tokens:
        return None
    while len(tokens) > _MAX_REFERENCES_TOKENS:
        tokens.pop(0)
    while tokens and len(" ".join(tokens)) > _MAX_REFERENCES_CHARS:
        tokens.pop(0)
    if not tokens:
        return None
    return " ".join(tokens)


def gmail_thread_id(metadata: dict[str, Any]) -> str | None:
    raw = metadata.get("thread_id")
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or any(char in text for char in "\r\n\x00 "):
        return None
    if len(text) > 200:
        return None
    return text


def envelope_addresses(metadata: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for key in ("recipients", "cc"):
        for address in _valid_addresses(metadata.get(key)):
            found.add(address.lower())
    headers = _headers(metadata)
    for key in ("to", "cc"):
        for address in _valid_addresses(headers.get(key)):
            found.add(address.lower())
    return found


def resolve_reply_source_email(
    session: Session,
    user_id: UUID,
    *,
    object_provider: str,
    metadata: dict[str, Any],
    provider_constraint: str | None,
    account_email_constraint: str | None,
) -> tuple[str, str]:
    mapped = _mapped_provider(object_provider)
    if provider_constraint is not None and provider_constraint != mapped:
        raise ToolError("provider does not match the message source")
    capable = _capable_emails(session, user_id, mapped)
    if not capable:
        raise ToolError("no supported account connected")
    requested = _lower(account_email_constraint)
    stored = _lower(metadata.get("source_account_email"))
    if stored:
        if requested and requested != stored:
            raise ToolError("account does not match the message source account")
        match = _matching(capable, stored)
        if match is None:
            raise ToolError("message source account is not connected")
        return mapped, match
    determined, pool = _legacy_source(capable, envelope_addresses(metadata))
    if requested:
        if determined is not None and determined.lower() != requested:
            raise ToolError("account does not match the message source account")
        narrowed = _matching(pool, requested)
        if narrowed is None:
            raise ToolError("account does not match the message source account")
        return mapped, narrowed
    if determined is None:
        raise ToolError("message source account is ambiguous")
    return mapped, determined


def _legacy_source(capable: list[str], envelope: set[str]) -> tuple[str | None, list[str]]:
    matched = [email for email in capable if email.lower() in envelope]
    if len(matched) == 1:
        return matched[0], matched
    if len(matched) > 1:
        return None, matched
    if len(capable) == 1:
        return capable[0], capable
    return None, capable


def _capable_emails(session: Session, user_id: UUID, provider: str) -> list[str]:
    encryption = _encryption()
    if provider == "google":
        accounts = GoogleAccountStore(session, encryption).list_accounts(user_id)
        return [account.email for account in accounts if google_has_send_capability(account)]
    accounts = YandexMailAccountStore(session, encryption).list_accounts(user_id)
    return [account.email for account in accounts]


def _matching(emails: list[str], requested: str) -> str | None:
    for email in emails:
        if email.lower() == requested:
            return email
    return None


def _mapped_provider(object_provider: str) -> str:
    if object_provider == "gmail":
        return "google"
    if object_provider == "yandex_mail":
        return "yandex"
    raise ToolError("reply requires a gmail or yandex mail message")


def _encryption() -> CredentialEncryption:
    if not settings.secretary_credential_key:
        raise ToolError("credentials are not configured")
    return CredentialEncryption(settings.secretary_credential_key)


def _headers(metadata: dict[str, Any]) -> dict[str, str]:
    raw = metadata.get("headers")
    if not isinstance(raw, dict):
        return {}
    return {str(key).lower(): str(value) for key, value in raw.items() if value is not None}


def _first_valid_address(value: object) -> str | None:
    addresses = _valid_addresses(value)
    return addresses[0] if addresses else None


def _valid_addresses(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        found: list[str] = []
        for item in value:
            found.extend(_valid_addresses(item))
        return found
    text = str(value).replace("\r", " ").replace("\n", " ")
    found = []
    for _name, address in getaddresses([text]):
        candidate = address.strip()
        if not candidate:
            continue
        try:
            found.append(_normalize_email_address(candidate))
        except ValueError:
            continue
    return found


def _clean_message_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = "".join(value.split())
    if "@" not in text or any(char in text for char in "\r\n\x00"):
        return None
    if not (text.startswith("<") and text.endswith(">")):
        text = f"<{text.strip('<>')}>"
    if len(text) > _MAX_MESSAGE_ID_CHARS or text == "<>":
        return None
    return text


def _lower(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text or None
