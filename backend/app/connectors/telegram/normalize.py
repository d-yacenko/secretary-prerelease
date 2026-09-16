from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.connectors.telegram.constants import (
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
    MAX_TELEGRAM_MESSAGE_BODY_CHARS,
    MAX_TITLE_CHARS,
    PRIVATE_CHAT_TYPE,
    TELEGRAM_KIND,
    TELEGRAM_ORIGIN,
    TELEGRAM_PROVIDER,
    TELEGRAM_STATE,
)

_MEDIA_TYPES = (
    "photo",
    "video",
    "voice",
    "audio",
    "document",
    "animation",
    "sticker",
    "video_note",
    "contact",
    "location",
    "venue",
    "poll",
    "dice",
    "story",
)


def build_external_id(business_connection_id: str, chat_id: str, message_id: str) -> str:
    return f"{business_connection_id}|{chat_id}|{message_id}"


def provider_id_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    return text or None


def is_private_chat(chat: dict[str, Any] | None) -> bool:
    if not isinstance(chat, dict):
        return False
    return str(chat.get("type") or "").strip() == PRIVATE_CHAT_TYPE


def display_name_from_user(user: dict[str, Any] | None) -> str | None:
    if not isinstance(user, dict):
        return None
    first = str(user.get("first_name") or "").strip()
    last = str(user.get("last_name") or "").strip()
    combined = " ".join(part for part in (first, last) if part)
    return combined or None


def display_name_from_chat(chat: dict[str, Any] | None) -> str | None:
    if not isinstance(chat, dict):
        return None
    title = str(chat.get("title") or "").strip()
    if title:
        return title
    return display_name_from_user(chat)


def username_from_user(user: dict[str, Any] | None) -> str | None:
    if not isinstance(user, dict):
        return None
    username = str(user.get("username") or "").strip()
    return username or None


def message_type_of(message: dict[str, Any]) -> str:
    if str(message.get("text") or "").strip():
        return "text"
    for media_type in _MEDIA_TYPES:
        if message.get(media_type) is not None:
            return media_type
    if str(message.get("caption") or "").strip():
        return "caption"
    return "unknown"


def extract_message_body(message: dict[str, Any]) -> str | None:
    text = str(message.get("text") or "")
    if text.strip():
        return _bound_body(text)
    caption = str(message.get("caption") or "")
    if caption.strip():
        return _bound_body(caption)
    return None


def _bound_body(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(normalized) > MAX_TELEGRAM_MESSAGE_BODY_CHARS:
        return normalized[:MAX_TELEGRAM_MESSAGE_BODY_CHARS]
    return normalized


def _bound_title(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= MAX_TITLE_CHARS:
        return stripped
    return stripped[: MAX_TITLE_CHARS - 1].rstrip() + "…"


def _presentation_title(*, author: str | None, body: str | None, message_type: str) -> str:
    author_label = (author or "").strip() or "Telegram"
    if body and body.strip():
        first_line = body.strip().splitlines()[0].strip()
        return _bound_title(f"{author_label}: {first_line}")
    if message_type == "text":
        return _bound_title(f"{author_label}: message")
    return _bound_title(f"{author_label}: {message_type}")


def _occurred_at(message: dict[str, Any]) -> datetime | None:
    raw = message.get("date")
    if isinstance(raw, int) and raw > 0:
        return datetime.fromtimestamp(raw, tz=UTC)
    if isinstance(raw, str) and raw.strip().isdigit():
        return datetime.fromtimestamp(int(raw), tz=UTC)
    return None


def determine_direction(*, from_user_id: str | None, business_user_id: str) -> str:
    if from_user_id and from_user_id == business_user_id:
        return DIRECTION_OUTBOUND
    return DIRECTION_INBOUND


def normalize_telegram_business_message(
    *,
    message: dict[str, Any],
    account_id: UUID,
    business_connection_id: str,
    business_user_id: str,
) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not is_private_chat(chat if isinstance(chat, dict) else None):
        return None
    chat_id = provider_id_str(chat.get("id") if isinstance(chat, dict) else None)
    message_id = provider_id_str(message.get("message_id"))
    connection_id = provider_id_str(message.get("business_connection_id")) or business_connection_id
    if not chat_id or not message_id or not connection_id:
        return None
    from_user = message.get("from") if isinstance(message.get("from"), dict) else None
    from_user_id = provider_id_str(from_user.get("id") if from_user else None)
    direction = determine_direction(from_user_id=from_user_id, business_user_id=business_user_id)
    body = extract_message_body(message)
    message_type = message_type_of(message)
    from_display = display_name_from_user(from_user)
    chat_display = display_name_from_chat(chat if isinstance(chat, dict) else None)
    title_author = from_display or chat_display
    reply_to = message.get("reply_to_message")
    reply_to_message_id = None
    if isinstance(reply_to, dict):
        reply_to_message_id = provider_id_str(reply_to.get("message_id"))
    sender_bot = message.get("sender_business_bot")
    sender_business_bot_id = None
    if isinstance(sender_bot, dict):
        sender_business_bot_id = provider_id_str(sender_bot.get("id"))
    metadata: dict[str, Any] = {
        "account_id": str(account_id),
        "business_connection_id": connection_id,
        "business_user_id": business_user_id,
        "chat_id": chat_id,
        "message_id": message_id,
        "from_user_id": from_user_id,
        "from_username": username_from_user(from_user),
        "from_display_name": from_display,
        "chat_username": username_from_user(chat if isinstance(chat, dict) else None),
        "chat_display_name": chat_display,
        "direction": direction,
        "reply_to_message_id": reply_to_message_id,
        "sender_business_bot_id": sender_business_bot_id,
        "message_type": message_type,
    }
    return {
        "provider": TELEGRAM_PROVIDER,
        "kind": TELEGRAM_KIND,
        "origin": TELEGRAM_ORIGIN,
        "state": TELEGRAM_STATE,
        "external_id": build_external_id(connection_id, chat_id, message_id),
        "title": _presentation_title(
            author=title_author,
            body=body,
            message_type=message_type,
        ),
        "body": body,
        "occurred_at": _occurred_at(message),
        "metadata": metadata,
    }
