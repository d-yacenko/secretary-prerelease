from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_errors import TelegramMtprotoIdentityConflictError
from app.connectors.telegram.mtproto_transport import TelegramMtprotoIdentity
from app.db.models import TelegramMtprotoAccount, TelegramMtprotoAuthChallenge


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
