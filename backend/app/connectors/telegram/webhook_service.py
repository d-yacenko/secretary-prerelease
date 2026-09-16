from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.connectors.telegram.account_store import (
    TelegramAccountStore,
    TelegramIdentityConflict,
)
from app.connectors.telegram.link_state import TelegramLinkStateStore, utcnow
from app.connectors.telegram.materialize import TelegramObjectMaterializer
from app.connectors.telegram.normalize import (
    display_name_from_user,
    is_private_chat,
    provider_id_str,
    username_from_user,
)
from app.core.config import settings


def telegram_is_configured() -> bool:
    return bool(
        settings.telegram_bot_token.strip()
        and settings.telegram_bot_username.strip()
        and settings.telegram_webhook_secret.strip()
        and settings.telegram_webhook_url.strip()
    )


def webhook_secret_matches(provided: str | None) -> bool:
    expected = settings.telegram_webhook_secret.strip()
    if not expected:
        return False
    if provided is None:
        return False
    return hmac.compare_digest(provided, expected)


def bot_username() -> str:
    return settings.telegram_bot_username.strip().lstrip("@")


def can_reply_from_rights(rights: dict | None) -> bool:
    if not isinstance(rights, dict):
        return False
    return rights.get("can_reply") is True


class TelegramWebhookService:
    def __init__(self, session: Session, *, materializer: TelegramObjectMaterializer | None = None) -> None:
        self._session = session
        self._accounts = TelegramAccountStore(session)
        self._links = TelegramLinkStateStore(session)
        self._materializer = materializer or TelegramObjectMaterializer(session)

    def handle_update(self, update: dict[str, Any]) -> None:
        if not isinstance(update, dict):
            return
        if "message" in update:
            self._handle_bot_message(update.get("message"))
        if "business_connection" in update:
            self._handle_business_connection(update.get("business_connection"))
        if "business_message" in update:
            self._handle_business_message(update.get("business_message"))
        if "edited_business_message" in update:
            self._handle_business_message(update.get("edited_business_message"))
        if "deleted_business_messages" in update:
            self._handle_deleted_business_messages(update.get("deleted_business_messages"))

    def _handle_bot_message(self, message: object) -> None:
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        if not is_private_chat(chat if isinstance(chat, dict) else None):
            return
        raw_state = _start_payload(message)
        if raw_state is None:
            return
        from_user = message.get("from") if isinstance(message.get("from"), dict) else None
        telegram_user_id = _require_int_id(from_user.get("id") if from_user else None)
        chat_id = _require_int_id(chat.get("id") if isinstance(chat, dict) else None)
        if telegram_user_id is None or chat_id is None:
            return
        row = self._links.lock_by_raw_state(raw_state)
        if row is None:
            return
        if row.consumed_at is not None:
            return
        if row.expires_at <= utcnow():
            return
        try:
            self._accounts.bind_identity(
                user_id=row.user_id,
                telegram_user_id=telegram_user_id,
                user_chat_id=chat_id,
                telegram_username=username_from_user(from_user),
                display_name=display_name_from_user(from_user),
            )
        except TelegramIdentityConflict:
            return
        self._links.consume(row)

    def _handle_business_connection(self, connection: object) -> None:
        if not isinstance(connection, dict):
            return
        user = connection.get("user") if isinstance(connection.get("user"), dict) else None
        telegram_user_id = _require_int_id(user.get("id") if user else None)
        connection_id = provider_id_str(connection.get("id"))
        if telegram_user_id is None or not connection_id:
            return
        account = self._accounts.get_by_telegram_user_id(telegram_user_id)
        if account is None:
            return
        if account.telegram_user_id != telegram_user_id:
            return
        user_chat_id = _require_int_id(connection.get("user_chat_id"))
        rights = connection.get("rights") if isinstance(connection.get("rights"), dict) else {}
        enabled = connection.get("is_enabled") is True
        connected_at = _timestamp(connection.get("date"))
        if user:
            account.telegram_username = username_from_user(user)
            account.display_name = display_name_from_user(user)
        self._accounts.apply_business_connection(
            account,
            business_connection_id=connection_id,
            business_user_chat_id=user_chat_id,
            business_rights=rights,
            enabled=enabled,
            connected_at=connected_at,
        )

    def _handle_business_message(self, message: object) -> None:
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        if not is_private_chat(chat if isinstance(chat, dict) else None):
            return
        connection_id = provider_id_str(message.get("business_connection_id"))
        if not connection_id:
            return
        account = self._accounts.get_by_business_connection_id(connection_id)
        if account is None or not account.business_connection_enabled:
            return
        if account.business_connection_id != connection_id:
            return
        self._materializer.upsert_business_message(
            user_id=account.user_id,
            account_id=account.id,
            business_connection_id=connection_id,
            business_user_id=str(account.telegram_user_id),
            message=message,
            skip_hidden=True,
        )

    def _handle_deleted_business_messages(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        connection_id = provider_id_str(payload.get("business_connection_id"))
        chat = payload.get("chat") if isinstance(payload.get("chat"), dict) else None
        if not connection_id or not is_private_chat(chat):
            return
        chat_id = provider_id_str(chat.get("id") if chat else None)
        if not chat_id:
            return
        account = self._accounts.get_by_business_connection_id(connection_id)
        if account is None:
            return
        raw_ids = payload.get("message_ids")
        if not isinstance(raw_ids, list):
            return
        message_ids = [item for item in (provider_id_str(item) for item in raw_ids) if item]
        self._materializer.hide_deleted_messages(
            user_id=account.user_id,
            business_connection_id=connection_id,
            chat_id=chat_id,
            message_ids=message_ids,
        )


def _start_payload(message: dict[str, Any]) -> str | None:
    text = str(message.get("text") or "").strip()
    if not text.startswith("/start"):
        return None
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return None
    payload = parts[1].strip()
    return payload or None


def _require_int_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip() if value is not None else ""
    if text.lstrip("-").isdigit():
        return int(text)
    return None


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, int) and value > 0:
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str) and value.strip().isdigit():
        return datetime.fromtimestamp(int(value), tz=UTC)
    return None
