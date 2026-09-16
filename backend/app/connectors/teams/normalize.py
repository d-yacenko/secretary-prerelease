from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.connectors.teams.constants import (
    ACCEPTED_CHAT_TYPES,
    CHAT_TYPE_GROUP,
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
    MAX_CHAT_TITLE_CHARS,
    MAX_DISPLAY_NAME_CHARS,
    MAX_MESSAGE_BODY_CHARS,
    MAX_TITLE_CHARS,
    MESSAGE_REFERENCE_CONTENT_TYPE,
    MESSAGE_TYPE_MESSAGE,
    TEAMS_KIND,
    TEAMS_ORIGIN,
    TEAMS_PROVIDER,
    TEAMS_STATE,
)
from app.connectors.teams.html_text import teams_body_to_plain_text
from app.connectors.teams.id_token import (
    canonicalize_microsoft_guid,
    try_canonical_microsoft_guid,
)


def build_external_id(tenant_id: str, microsoft_user_id: str, chat_id: str, message_id: str) -> str:
    tenant = canonicalize_microsoft_guid(tenant_id, claim="tenant id")
    user = canonicalize_microsoft_guid(microsoft_user_id, claim="user id")
    return f"{tenant}|{user}|{chat_id}|{message_id}"


def provider_id_str(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    return text or None


def _parse_message_reference_content(content: object) -> dict[str, Any] | None:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_message_reference_ids(message: dict[str, Any] | None) -> list[str]:
    if not isinstance(message, dict):
        return []
    attachments = message.get("attachments")
    if not isinstance(attachments, list):
        return []
    found: list[str] = []
    seen: set[str] = set()
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        content_type = str(attachment.get("contentType") or "").strip()
        if content_type != MESSAGE_REFERENCE_CONTENT_TYPE:
            continue
        parsed = _parse_message_reference_content(attachment.get("content"))
        if parsed is None:
            continue
        message_id = provider_id_str(parsed.get("messageId"))
        if not message_id or message_id in seen:
            continue
        seen.add(message_id)
        found.append(message_id)
    return found


def quoted_message_id_from_attachments(message: dict[str, Any] | None) -> str | None:
    found = extract_message_reference_ids(message)
    if len(found) == 1:
        return found[0]
    return None


def merge_quoted_message_provenance(
    existing_quoted: str | None, incoming_quoted: str | None
) -> str | None:
    existing = provider_id_str(existing_quoted)
    incoming = provider_id_str(incoming_quoted)
    if existing and incoming and existing != incoming:
        return existing
    if existing and not incoming:
        return existing
    return incoming


def parse_graph_datetime(value: object) -> datetime | None:
    text = provider_id_str(value)
    if text is None:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def accepted_chat_type(chat: dict[str, Any] | None) -> str | None:
    if not isinstance(chat, dict):
        return None
    chat_type = str(chat.get("chatType") or "").strip()
    if chat_type in ACCEPTED_CHAT_TYPES:
        return chat_type
    return None


def _clip(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    return text[:limit]


def display_title_for_chat(
    chat: dict[str, Any],
    *,
    self_user_id: str,
) -> str | None:
    chat_type = accepted_chat_type(chat)
    topic = _clip(provider_id_str(chat.get("topic")), MAX_CHAT_TITLE_CHARS)
    if chat_type == CHAT_TYPE_GROUP:
        if topic:
            return topic
        names = _member_display_names(chat, exclude_user_id=None)
        if names:
            return _clip(", ".join(names[:4]), MAX_CHAT_TITLE_CHARS)
        return "Teams group"
    names = _member_display_names(chat, exclude_user_id=self_user_id)
    if names:
        return _clip(names[0], MAX_CHAT_TITLE_CHARS)
    return topic or "Teams chat"


def _member_display_names(chat: dict[str, Any], *, exclude_user_id: str | None) -> list[str]:
    members = chat.get("members")
    if not isinstance(members, list):
        return []
    names: list[str] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        user_id = provider_id_str(member.get("userId") or _nested_user_id(member))
        if exclude_user_id and try_canonical_microsoft_guid(
            user_id
        ) == try_canonical_microsoft_guid(exclude_user_id):
            continue
        name = _clip(provider_id_str(member.get("displayName")), MAX_DISPLAY_NAME_CHARS)
        if name:
            names.append(name)
    return names


def _nested_user_id(member: dict[str, Any]) -> str | None:
    user = member.get("user")
    if isinstance(user, dict):
        return provider_id_str(user.get("id"))
    return None


def sender_from_message(message: dict[str, Any]) -> tuple[str | None, str | None]:
    raw_from = message.get("from")
    if not isinstance(raw_from, dict):
        return None, None
    user = raw_from.get("user")
    if isinstance(user, dict):
        return provider_id_str(user.get("id")), _clip(
            provider_id_str(user.get("displayName")), MAX_DISPLAY_NAME_CHARS
        )
    application = raw_from.get("application")
    if isinstance(application, dict):
        return provider_id_str(application.get("id")), _clip(
            provider_id_str(application.get("displayName")), MAX_DISPLAY_NAME_CHARS
        )
    return None, None


def normalize_teams_message(
    *,
    message: dict[str, Any],
    account_id: UUID,
    tenant_id: str,
    microsoft_user_id: str,
    chat_id: str,
    chat_type: str,
    chat_display_title: str | None,
    frozen_quoted_message_id: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return None
    message_type = str(message.get("messageType") or "").strip() or MESSAGE_TYPE_MESSAGE
    if message_type != MESSAGE_TYPE_MESSAGE:
        return None
    if message.get("deletedDateTime"):
        return None
    message_id = provider_id_str(message.get("id"))
    if not message_id:
        return None
    body = message.get("body") if isinstance(message.get("body"), dict) else {}
    text = teams_body_to_plain_text(
        content_type=provider_id_str(body.get("contentType")) if body else None,
        content=str(body.get("content") or "") if body else "",
    )
    if len(text) > MAX_MESSAGE_BODY_CHARS:
        text = text[:MAX_MESSAGE_BODY_CHARS]
    tenant_id = canonicalize_microsoft_guid(tenant_id, claim="tenant id")
    microsoft_user_id = canonicalize_microsoft_guid(microsoft_user_id, claim="user id")
    sender_id, sender_name = sender_from_message(message)
    sender_identity = try_canonical_microsoft_guid(sender_id)
    direction = DIRECTION_OUTBOUND if sender_identity == microsoft_user_id else DIRECTION_INBOUND
    occurred_at = parse_graph_datetime(message.get("createdDateTime"))
    modified_at = parse_graph_datetime(message.get("lastModifiedDateTime"))
    title_name = sender_name or ("Вы" if direction == DIRECTION_OUTBOUND else chat_display_title or "Teams")
    preview = text.replace("\n", " ").strip() or "(без текста)"
    title = _clip(f"{title_name}: {preview}", MAX_TITLE_CHARS) or "Teams"
    graph_quoted = quoted_message_id_from_attachments(message)
    quoted_message_id = provider_id_str(frozen_quoted_message_id) or graph_quoted
    return {
        "provider": TEAMS_PROVIDER,
        "kind": TEAMS_KIND,
        "origin": TEAMS_ORIGIN,
        "state": TEAMS_STATE,
        "external_id": build_external_id(tenant_id, microsoft_user_id, chat_id, message_id),
        "title": title,
        "body": text,
        "occurred_at": occurred_at,
        "metadata": {
            "account_id": str(account_id),
            "tenant_id": tenant_id,
            "teams_user_id": microsoft_user_id,
            "chat_id": chat_id,
            "chat_type": chat_type,
            "message_id": message_id,
            "sender_id": sender_id,
            "sender_display_name": sender_name,
            "chat_display_title": chat_display_title,
            "direction": direction,
            "created_at": occurred_at.isoformat() if occurred_at else None,
            "modified_at": modified_at.isoformat() if modified_at else None,
            "reply_to_message_id": provider_id_str(message.get("replyToId")),
            "quoted_message_id": quoted_message_id,
        },
    }
