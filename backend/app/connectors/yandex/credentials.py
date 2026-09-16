from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleConfigurationError
from app.connectors.yandex.errors import YandexConfigurationError
from app.db.models import YandexMailAccount
from app.services.user_serialization_gate import lock_user_serialization_row


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class YandexMailSyncSnapshot:
    account_id: UUID
    user_id: UUID
    email: str
    imap_host: str
    imap_port: int
    app_password: str
    sync_state: dict


class YandexMailAccountStore:
    def __init__(self, session: Session, encryption: CredentialEncryption) -> None:
        self._session = session
        self._encryption = encryption

    def get_by_id_for_user(self, account_id: UUID, user_id: UUID) -> YandexMailAccount | None:
        return self._session.scalar(
            select(YandexMailAccount).where(
                YandexMailAccount.id == account_id,
                YandexMailAccount.user_id == user_id,
            )
        )

    def load_sync_snapshot(
        self, account_id: UUID, user_id: UUID
    ) -> YandexMailSyncSnapshot | None:
        account = self.get_by_id_for_user(account_id, user_id)
        if account is None:
            return None
        return YandexMailSyncSnapshot(
            account_id=account.id,
            user_id=account.user_id,
            email=account.email,
            imap_host=account.imap_host,
            imap_port=account.imap_port,
            app_password=self.get_app_password(account),
            sync_state=dict(account.sync_state or {}),
        )

    def get_by_email(self, user_id: UUID, email: str) -> YandexMailAccount | None:
        return self._session.scalar(
            select(YandexMailAccount).where(
                YandexMailAccount.user_id == user_id,
                YandexMailAccount.email == email,
            )
        )

    def list_accounts(self, user_id: UUID) -> list[YandexMailAccount]:
        return list(
            self._session.scalars(
                select(YandexMailAccount)
                .where(YandexMailAccount.user_id == user_id)
                .order_by(YandexMailAccount.email)
            ).all()
        )

    def upsert_account(
        self,
        user_id: UUID,
        email: str,
        app_password: str,
        imap_host: str,
        imap_port: int,
    ) -> YandexMailAccount:
        account = self.get_by_email(user_id, email)
        if account is None:
            if lock_user_serialization_row(self._session, user_id) is None:
                raise YandexConfigurationError("user not found")
            account = YandexMailAccount(
                user_id=user_id,
                email=email,
                imap_host=imap_host,
                imap_port=imap_port,
                app_password_encrypted=self._encryption.encrypt(app_password),
            )
            self._session.add(account)
        else:
            account.app_password_encrypted = self._encryption.encrypt(app_password)
            account.imap_host = imap_host
            account.imap_port = imap_port
        account.updated_at = utcnow()
        self._session.flush()
        return account

    def get_app_password(self, account: YandexMailAccount) -> str:
        return self._encryption.decrypt(account.app_password_encrypted)

    def update_sync_state(self, account: YandexMailAccount, sync_state: dict) -> YandexMailAccount:
        account.sync_state = sync_state
        account.updated_at = utcnow()
        self._session.flush()
        return account

    @staticmethod
    def build_encryption(key: str) -> CredentialEncryption:
        try:
            return CredentialEncryption(key)
        except GoogleConfigurationError as exc:
            raise YandexConfigurationError(exc.message) from exc
