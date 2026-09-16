from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_errors import TelegramMtprotoIdentityConflictError
from app.connectors.telegram.mtproto_transport import (
    TelegramMtprotoGroupDescriptor,
    TelegramMtprotoIdentity,
)
from app.db.models import (
    TelegramMtprotoAccount,
    TelegramMtprotoAuthChallenge,
    TelegramMtprotoChatSelection,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class TelegramMtprotoAccountStore:
    def __init__(self, session: Session, encryption: CredentialEncryption) -> None:
        self._session = session
        self._encryption = encryption

    def get_by_user_id(self, user_id: UUID) -> TelegramMtprotoAccount | None:
        return self._session.scalar(
            select(TelegramMtprotoAccount).where(TelegramMtprotoAccount.user_id == user_id)
        )

    def decrypt_session(self, account: TelegramMtprotoAccount) -> str:
        return self._encryption.decrypt(account.session_encrypted)

    def list_selections(self, account_id: UUID) -> list[TelegramMtprotoChatSelection]:
        return list(
            self._session.scalars(
                select(TelegramMtprotoChatSelection)
                .where(TelegramMtprotoChatSelection.account_id == account_id)
                .order_by(TelegramMtprotoChatSelection.created_at, TelegramMtprotoChatSelection.id)
            )
        )

    def get_selection(
        self, account_id: UUID, peer_id: int
    ) -> TelegramMtprotoChatSelection | None:
        return self._session.scalar(
            select(TelegramMtprotoChatSelection).where(
                TelegramMtprotoChatSelection.account_id == account_id,
                TelegramMtprotoChatSelection.peer_id == peer_id,
            )
        )

    def save_selection(
        self, account_id: UUID, descriptor: TelegramMtprotoGroupDescriptor
    ) -> TelegramMtprotoChatSelection:
        selection = self.get_selection(account_id, descriptor.peer_id)
        encrypted_reference = self._encryption.encrypt(descriptor.provider_peer_reference)
        if selection is None:
            selection = TelegramMtprotoChatSelection(
                id=uuid4(),
                account_id=account_id,
                peer_id=descriptor.peer_id,
                peer_kind=descriptor.kind,
                provider_peer_reference_encrypted=encrypted_reference,
                title=descriptor.title,
                username=descriptor.username,
                is_forum=descriptor.is_forum,
            )
            self._session.add(selection)
        else:
            selection.peer_kind = descriptor.kind
            selection.provider_peer_reference_encrypted = encrypted_reference
            selection.title = descriptor.title
            selection.username = descriptor.username
            selection.is_forum = descriptor.is_forum
            selection.updated_at = utcnow()
        self._session.flush()
        return selection

    def delete_selection(self, account_id: UUID, peer_id: int) -> None:
        selection = self.get_selection(account_id, peer_id)
        if selection is not None:
            self._session.delete(selection)
            self._session.flush()

    def get_challenge(
        self, user_id: UUID, challenge_id: UUID
    ) -> TelegramMtprotoAuthChallenge | None:
        return self._session.scalar(
            select(TelegramMtprotoAuthChallenge).where(
                TelegramMtprotoAuthChallenge.id == challenge_id,
                TelegramMtprotoAuthChallenge.user_id == user_id,
            )
        )

    def replace_challenge(
        self,
        *,
        user_id: UUID,
        auth_state: str,
        expires_at: datetime,
    ) -> TelegramMtprotoAuthChallenge:
        self._session.execute(
            delete(TelegramMtprotoAuthChallenge).where(
                TelegramMtprotoAuthChallenge.user_id == user_id
            )
        )
        challenge = TelegramMtprotoAuthChallenge(
            id=uuid4(),
            user_id=user_id,
            auth_state_encrypted=self._encryption.encrypt(auth_state),
            expires_at=expires_at,
        )
        self._session.add(challenge)
        self._session.flush()
        return challenge

    def update_challenge(
        self, challenge: TelegramMtprotoAuthChallenge, auth_state: str
    ) -> None:
        challenge.auth_state_encrypted = self._encryption.encrypt(auth_state)
        self._session.flush()

    def delete_challenge(self, challenge: TelegramMtprotoAuthChallenge) -> None:
        self._session.delete(challenge)
        self._session.flush()

    def save_account(
        self,
        *,
        user_id: UUID,
        identity: TelegramMtprotoIdentity,
        session: str,
    ) -> TelegramMtprotoAccount:
        account_for_user = self.get_by_user_id(user_id)
        account_for_identity = self._session.scalar(
            select(TelegramMtprotoAccount).where(
                TelegramMtprotoAccount.telegram_user_id == identity.telegram_user_id
            )
        )
        if account_for_user is not None and account_for_user.telegram_user_id != identity.telegram_user_id:
            raise TelegramMtprotoIdentityConflictError(
                "Telegram identity is already connected for this user"
            )
        if account_for_identity is not None and account_for_identity.user_id != user_id:
            raise TelegramMtprotoIdentityConflictError(
                "Telegram identity is already connected to another user"
            )
        account = account_for_user or account_for_identity
        encrypted_session = self._encryption.encrypt(session)
        if account is None:
            account = TelegramMtprotoAccount(
                id=uuid4(),
                user_id=user_id,
                telegram_user_id=identity.telegram_user_id,
                session_encrypted=encrypted_session,
                username=identity.username,
                display_name=identity.display_name,
            )
            self._session.add(account)
        else:
            account.session_encrypted = encrypted_session
            account.username = identity.username
            account.display_name = identity.display_name
            account.updated_at = utcnow()
        self._session.flush()
        return account
