from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.teams.constants import (
    AUTH_STATUS_ACTIVE,
    AUTH_STATUS_RECONNECT_REQUIRED,
    SYNC_START_AT_KEY,
)
from app.connectors.teams.errors import (
    TeamsConfigurationError,
    TeamsIdentityConflictError,
    TeamsIdentitySwitchError,
    TeamsOAuthError,
)
from app.connectors.teams.id_token import canonicalize_microsoft_guid
from app.db.models import TeamsAccount
from app.services.user_serialization_gate import lock_user_serialization_row


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class TeamsCredentialSnapshot:
    account_id: UUID
    access_token: str
    refresh_token: str
    token_expiry: datetime | None
    microsoft_user_id: str
    tenant_id: str
    auth_status: str


class TeamsAccountStore:
    def __init__(self, session: Session, encryption: CredentialEncryption) -> None:
        self._session = session
        self._encryption = encryption

    @staticmethod
    def build_encryption(credential_key: str) -> CredentialEncryption:
        return CredentialEncryption(credential_key)

    def get_by_id_for_user(self, account_id: UUID, user_id: UUID) -> TeamsAccount | None:
        return self._session.scalar(
            select(TeamsAccount).where(
                TeamsAccount.id == account_id,
                TeamsAccount.user_id == user_id,
            )
        )

    def get_by_user_id(self, user_id: UUID) -> TeamsAccount | None:
        return self._session.scalar(select(TeamsAccount).where(TeamsAccount.user_id == user_id))

    def get_by_microsoft_identity(
        self, tenant_id: str, microsoft_user_id: str
    ) -> TeamsAccount | None:
        tenant_id = canonicalize_microsoft_guid(tenant_id, claim="tenant id")
        microsoft_user_id = canonicalize_microsoft_guid(microsoft_user_id, claim="user id")
        return self._session.scalar(
            select(TeamsAccount).where(
                TeamsAccount.tenant_id == tenant_id,
                TeamsAccount.microsoft_user_id == microsoft_user_id,
            )
        )

    def list_accounts(self, user_id: UUID) -> list[TeamsAccount]:
        account = self.get_by_user_id(user_id)
        return [account] if account is not None else []

    def upsert_tokens(
        self,
        user_id: UUID,
        *,
        microsoft_user_id: str,
        tenant_id: str,
        upn: str | None,
        display_name: str | None,
        scopes: list[str],
        access_token: str,
        refresh_token: str,
        token_expiry: datetime | None,
    ) -> TeamsAccount:
        tenant_id = canonicalize_microsoft_guid(tenant_id, claim="tenant id")
        microsoft_user_id = canonicalize_microsoft_guid(microsoft_user_id, claim="user id")
        conflict = self.get_by_microsoft_identity(tenant_id, microsoft_user_id)
        if conflict is not None and conflict.user_id != user_id:
            raise TeamsIdentityConflictError("Microsoft Teams identity is already connected")
        account = self.get_by_user_id(user_id)
        now = utcnow()
        encrypted_access = self._encryption.encrypt(access_token)
        encrypted_refresh = self._encryption.encrypt(refresh_token)
        try:
            if account is None:
                if lock_user_serialization_row(self._session, user_id) is None:
                    raise TeamsOAuthError("user not found")
                account = TeamsAccount(
                    user_id=user_id,
                    microsoft_user_id=microsoft_user_id,
                    tenant_id=tenant_id,
                    upn=upn,
                    display_name=display_name,
                    auth_status=AUTH_STATUS_ACTIVE,
                    access_token_encrypted=encrypted_access,
                    refresh_token_encrypted=encrypted_refresh,
                    token_expiry=token_expiry,
                    scopes=scopes,
                    sync_state={SYNC_START_AT_KEY: now.isoformat()},
                )
                self._session.add(account)
            else:
                if (
                    account.tenant_id != tenant_id
                    or account.microsoft_user_id != microsoft_user_id
                ):
                    raise TeamsIdentitySwitchError(
                        "disconnect Microsoft Teams before connecting a different account"
                    )
                account.upn = upn
                account.display_name = display_name
                account.scopes = scopes
                account.auth_status = AUTH_STATUS_ACTIVE
                account.access_token_encrypted = encrypted_access
                account.refresh_token_encrypted = encrypted_refresh
                account.token_expiry = token_expiry
            account.updated_at = now
            self._session.flush()
        except IntegrityError as exc:
            raise TeamsIdentityConflictError(
                "Microsoft Teams identity is already connected"
            ) from exc
        return account

    def mark_reconnect_required(self, account: TeamsAccount) -> None:
        account.auth_status = AUTH_STATUS_RECONNECT_REQUIRED
        account.updated_at = utcnow()
        self._session.flush()

    def disconnect(self, user_id: UUID) -> TeamsAccount | None:
        account = self.get_by_user_id(user_id)
        if account is None:
            return None
        self._session.delete(account)
        self._session.flush()
        return account

    def get_access_token(self, account: TeamsAccount) -> str:
        if not account.access_token_encrypted:
            raise TeamsConfigurationError("Teams account is missing access token")
        return self._encryption.decrypt(account.access_token_encrypted)

    def encrypt_secret(self, value: str) -> str:
        return self._encryption.encrypt(value)

    def decrypt_secret(self, value: str) -> str:
        return self._encryption.decrypt(value)

    def get_refresh_token(self, account: TeamsAccount) -> str:
        if not account.refresh_token_encrypted:
            raise TeamsOAuthError("Teams account is missing refresh token")
        return self._encryption.decrypt(account.refresh_token_encrypted)

    def update_tokens_from_refresh(
        self,
        account: TeamsAccount,
        access_token: str,
        refresh_token: str | None,
        token_expiry: datetime | None,
    ) -> TeamsAccount:
        account.access_token_encrypted = self._encryption.encrypt(access_token)
        if refresh_token is not None:
            account.refresh_token_encrypted = self._encryption.encrypt(refresh_token)
        account.token_expiry = token_expiry
        account.auth_status = AUTH_STATUS_ACTIVE
        account.updated_at = utcnow()
        self._session.flush()
        return account

    def load_credential_snapshot(
        self, account_id: UUID, user_id: UUID
    ) -> TeamsCredentialSnapshot | None:
        account = self.get_by_id_for_user(account_id, user_id)
        if account is None:
            return None
        return TeamsCredentialSnapshot(
            account_id=account.id,
            access_token=self.get_access_token(account),
            refresh_token=self.get_refresh_token(account),
            token_expiry=account.token_expiry,
            microsoft_user_id=account.microsoft_user_id,
            tenant_id=account.tenant_id,
            auth_status=account.auth_status,
        )

    def get_sync_state(self, account_id: UUID, user_id: UUID) -> dict[str, Any]:
        account = self.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise TeamsOAuthError("Teams account not found")
        state = account.sync_state
        return dict(state) if isinstance(state, dict) else {}

    def update_sync_state(self, account_id: UUID, user_id: UUID, state: dict[str, Any]) -> None:
        account = self.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise TeamsOAuthError("Teams account not found")
        account.sync_state = dict(state)
        flag_modified(account, "sync_state")
        account.updated_at = utcnow()
        self._session.flush()
