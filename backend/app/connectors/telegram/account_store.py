"""Legacy Telegram Bot API persistence retained for schema compatibility only.

Do not use this store to re-enable live Bot linking or ingress.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import TelegramAccount


def utcnow() -> datetime:
    return datetime.now(UTC)


class TelegramAccountStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id_for_user(self, account_id: UUID, user_id: UUID) -> TelegramAccount | None:
        return self._session.scalar(
            select(TelegramAccount).where(
                TelegramAccount.id == account_id,
                TelegramAccount.user_id == user_id,
            )
        )

    def get_by_user_id(self, user_id: UUID) -> TelegramAccount | None:
        return self._session.scalar(
            select(TelegramAccount).where(TelegramAccount.user_id == user_id)
        )

    def get_by_telegram_user_id(self, telegram_user_id: int) -> TelegramAccount | None:
        return self._session.scalar(
            select(TelegramAccount).where(TelegramAccount.telegram_user_id == telegram_user_id)
        )

    def get_by_business_connection_id(self, business_connection_id: str) -> TelegramAccount | None:
        return self._session.scalar(
            select(TelegramAccount).where(
                TelegramAccount.business_connection_id == business_connection_id
            )
        )

    def bind_identity(
        self,
        *,
        user_id: UUID,
        telegram_user_id: int,
        user_chat_id: int,
        telegram_username: str | None,
        display_name: str | None,
    ) -> TelegramAccount:
        existing_for_user = self.get_by_user_id(user_id)
        existing_for_telegram = self.get_by_telegram_user_id(telegram_user_id)
        if existing_for_user is not None and existing_for_user.telegram_user_id != telegram_user_id:
            raise TelegramIdentityConflict("telegram identity already linked for this user")
        if existing_for_telegram is not None and existing_for_telegram.user_id != user_id:
            raise TelegramIdentityConflict("telegram identity already linked to another user")
        account = existing_for_user or existing_for_telegram
        if account is None:
            account = TelegramAccount(
                id=uuid4(),
                user_id=user_id,
                telegram_user_id=telegram_user_id,
                user_chat_id=user_chat_id,
                telegram_username=telegram_username,
                display_name=display_name,
            )
            self._session.add(account)
        else:
            account.user_chat_id = user_chat_id
            account.telegram_username = telegram_username
            account.display_name = display_name
            account.updated_at = utcnow()
        self._session.flush()
        return account

    def apply_business_connection(
        self,
        account: TelegramAccount,
        *,
        business_connection_id: str,
        business_user_chat_id: int | None,
        business_rights: dict,
        enabled: bool,
        connected_at: datetime | None,
    ) -> None:
        account.business_connection_id = business_connection_id
        account.business_user_chat_id = business_user_chat_id
        account.business_rights = dict(business_rights or {})
        account.business_connection_enabled = enabled
        if enabled:
            account.business_connected_at = connected_at or utcnow()
        account.updated_at = utcnow()
        self._session.flush()


class TelegramIdentityConflict(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
