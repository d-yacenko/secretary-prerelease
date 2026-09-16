"""Canonical RFC Message-ID extraction from normalized email metadata."""

from typing import Any


def extract_rfc_message_id(metadata: dict[str, Any], provider: str | None = None) -> str | None:
    """Return normalized RFC Message-ID (without angle brackets), not provider API ids."""
    headers = metadata.get("headers") or {}
    provider_key = (provider or "").lower()

    if provider_key == "gmail":
        raw = headers.get("message-id")
    elif provider_key in {"yandex_mail", "yandex"}:
        raw = metadata.get("message_id") or headers.get("message-id")
    else:
        raw = headers.get("message-id") or metadata.get("message_id")

    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("<") and text.endswith(">") and len(text) > 2:
        text = text[1:-1].strip()
    return text.lower()


def normalize_rfc_message_id_token(value: str) -> str:
    text = value.strip()
    if text.startswith("<") and text.endswith(">") and len(text) > 2:
        text = text[1:-1].strip()
    return text.lower()
