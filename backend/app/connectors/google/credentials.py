from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleConnectorError, GoogleOAuthError
from app.db.models import GoogleAccount
from app.services.user_serialization_gate import lock_user_serialization_row


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class AccountCredentialSnapshot:
    account_id: UUID
    access_token: str | None
    refresh_token: str | None
    token_expiry: datetime | None


class GoogleAccountStore:
    def __init__(self, session: Session, encryption: CredentialEncryption) -> None:
        self._session = session
        self._encryption = encryption

    def get_by_email(self, user_id: UUID, email: str) -> GoogleAccount | None:
        return self._session.scalar(
            select(GoogleAccount).where(
                GoogleAccount.user_id == user_id,
                GoogleAccount.email == email,
            )
        )

    def get_by_id_for_user(self, account_id: UUID, user_id: UUID) -> GoogleAccount | None:
        return self._session.scalar(
            select(GoogleAccount).where(
                GoogleAccount.id == account_id,
                GoogleAccount.user_id == user_id,
            )
        )

    def load_credential_snapshot(
        self, account_id: UUID, user_id: UUID
    ) -> AccountCredentialSnapshot | None:
        account = self.get_by_id_for_user(account_id, user_id)
        if account is None:
            return None
        return AccountCredentialSnapshot(
            account_id=account.id,
            access_token=self.get_access_token(account),
            refresh_token=self.get_refresh_token(account),
            token_expiry=account.token_expiry,
        )

    def list_accounts(self, user_id: UUID) -> list[GoogleAccount]:
        return list(
            self._session.scalars(
                select(GoogleAccount)
                .where(GoogleAccount.user_id == user_id)
                .order_by(GoogleAccount.email)
            )
        )

    def upsert_tokens(
        self,
        user_id: UUID,
        email: str,
        scopes: list[str],
        access_token: str | None,
        refresh_token: str | None,
        token_expiry: datetime | None,
    ) -> GoogleAccount:
        account = self.get_by_email(user_id, email)
        if account is None:
            if lock_user_serialization_row(self._session, user_id) is None:
                raise GoogleOAuthError("user not found")
            account = GoogleAccount(user_id=user_id, email=email, scopes=scopes)
            self._session.add(account)
        else:
            account.scopes = scopes

        if access_token is not None:
            account.access_token_encrypted = self._encryption.encrypt(access_token)
        if refresh_token is not None:
            account.refresh_token_encrypted = self._encryption.encrypt(refresh_token)
        account.token_expiry = token_expiry
        account.updated_at = utcnow()
        self._session.flush()
        return account

    def get_access_token(self, account: GoogleAccount) -> str | None:
        if account.access_token_encrypted is None:
            return None
        return self._encryption.decrypt(account.access_token_encrypted)

    def get_refresh_token(self, account: GoogleAccount) -> str | None:
        if account.refresh_token_encrypted is None:
            return None
        return self._encryption.decrypt(account.refresh_token_encrypted)

    def require_refresh_token(self, account: GoogleAccount) -> str:
        token = self.get_refresh_token(account)
        if token is None:
            raise GoogleOAuthError("google account is missing refresh token")
        return token

    def update_tokens_from_refresh(
        self,
        account: GoogleAccount,
        access_token: str,
        refresh_token: str | None,
        token_expiry: datetime | None,
    ) -> GoogleAccount:
        account.access_token_encrypted = self._encryption.encrypt(access_token)
        if refresh_token is not None:
            account.refresh_token_encrypted = self._encryption.encrypt(refresh_token)
        account.token_expiry = token_expiry
        account.updated_at = utcnow()
        self._session.flush()
        return account

    def get_gmail_sync_state(self, account_id: UUID, user_id: UUID) -> dict[str, Any]:
        account = self.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise GoogleConnectorError("google account not found")
        state = account.gmail_sync_state
        return dict(state) if isinstance(state, dict) else {}

    def get_calendar_sync_state(self, account_id: UUID, user_id: UUID) -> dict[str, Any]:
        account = self.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise GoogleConnectorError("google account not found")
        state = account.calendar_sync_state
        return dict(state) if isinstance(state, dict) else {}

    def update_gmail_sync_state(
        self,
        account_id: UUID,
        user_id: UUID,
        state: dict[str, Any],
    ) -> None:
        account = self.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise GoogleConnectorError("google account not found")
        account.gmail_sync_state = dict(state)
        account.updated_at = utcnow()
        self._session.flush()

    def update_calendar_sync_state(
        self,
        account_id: UUID,
        user_id: UUID,
        state: dict[str, Any],
    ) -> None:
        account = self.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise GoogleConnectorError("google account not found")
        account.calendar_sync_state = dict(state)
        account.updated_at = utcnow()
        self._session.flush()

    def build_encryption(key: str) -> CredentialEncryption:
        return CredentialEncryption(key)
