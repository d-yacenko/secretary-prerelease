from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleConfigurationError
from app.connectors.mattermost.errors import MattermostConfigurationError
from app.db.models import MattermostAccount
from app.services.user_serialization_gate import lock_user_serialization_row


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class MattermostSyncSnapshot:
    account_id: UUID
    user_id: UUID
    server_url: str
    normalized_server_url: str
    remote_user_id: str
    username: str
    access_token: str
    sync_state: dict


class MattermostAccountStore:
    def __init__(self, session: Session, encryption: CredentialEncryption) -> None:
        self._session = session
        self._encryption = encryption

    def get_by_id_for_user(self, account_id: UUID, user_id: UUID) -> MattermostAccount | None:
        return self._session.scalar(
            select(MattermostAccount).where(
                MattermostAccount.id == account_id,
                MattermostAccount.user_id == user_id,
            )
        )

    def get_by_server_and_remote_user(
        self,
        user_id: UUID,
        server_url: str,
        remote_user_id: str,
    ) -> MattermostAccount | None:
        return self._session.scalar(
            select(MattermostAccount).where(
                MattermostAccount.user_id == user_id,
                MattermostAccount.server_url == server_url,
                MattermostAccount.remote_user_id == remote_user_id,
            )
        )

    def list_accounts(self, user_id: UUID) -> list[MattermostAccount]:
        return list(
            self._session.scalars(
                select(MattermostAccount)
                .where(MattermostAccount.user_id == user_id)
                .order_by(MattermostAccount.server_url, MattermostAccount.username)
            ).all()
        )

    def upsert_account(
        self,
        user_id: UUID,
        normalized_server_url: str,
        remote_user_id: str,
        username: str,
        access_token: str,
        display_name: str | None = None,
        email: str | None = None,
    ) -> MattermostAccount:
        account = self.get_by_server_and_remote_user(
            user_id=user_id,
            server_url=normalized_server_url,
            remote_user_id=remote_user_id,
        )
        encrypted = self._encryption.encrypt(access_token)
        identity_changed = account is None or account.username != username or account.email != email
        if identity_changed and lock_user_serialization_row(self._session, user_id) is None:
            raise MattermostConfigurationError("user not found")
        if account is None:
            account = MattermostAccount(
                user_id=user_id,
                server_url=normalized_server_url,
                remote_user_id=remote_user_id,
                username=username,
                display_name=display_name,
                email=email,
                access_token_encrypted=encrypted,
            )
            self._session.add(account)
        else:
            account.username = username
            account.display_name = display_name
            account.email = email
            account.access_token_encrypted = encrypted
        account.updated_at = utcnow()
        self._session.flush()
        return account

    def load_sync_snapshot(
        self,
        account_id: UUID,
        user_id: UUID,
        normalized_server_url: str,
    ) -> MattermostSyncSnapshot | None:
        account = self.get_by_id_for_user(account_id, user_id)
        if account is None:
            return None
        return MattermostSyncSnapshot(
            account_id=account.id,
            user_id=account.user_id,
            server_url=account.server_url,
            normalized_server_url=normalized_server_url,
            remote_user_id=account.remote_user_id,
            username=account.username,
            access_token=self.get_access_token(account),
            sync_state=dict(account.sync_state or {}),
        )

    def get_access_token(self, account: MattermostAccount) -> str:
        return self._encryption.decrypt(account.access_token_encrypted)

    def update_sync_state(
        self, account: MattermostAccount, sync_state: dict
    ) -> MattermostAccount:
        account.sync_state = sync_state
        account.updated_at = utcnow()
        self._session.flush()
        return account

    @staticmethod
    def build_encryption(key: str) -> CredentialEncryption:
        try:
            return CredentialEncryption(key)
        except GoogleConfigurationError as exc:
            raise MattermostConfigurationError(exc.message) from exc
