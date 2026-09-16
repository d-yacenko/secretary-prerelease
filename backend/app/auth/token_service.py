import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuthToken, User
from app.services.errors import NotFoundError, ValidationError

TOKEN_BYTE_LENGTH = 32
TOKEN_PREFIX_LENGTH = 8


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _token_prefix(plaintext: str) -> str:
    return plaintext[:TOKEN_PREFIX_LENGTH]


class AuthTokenService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def issue_token(
        self,
        user_id: UUID,
        label: str | None = None,
        expires_in_days: int | None = None,
    ) -> tuple[str, AuthToken]:
        user = self._session.get(User, user_id)
        if user is None:
            raise NotFoundError("user", user_id)

        plaintext = secrets.token_urlsafe(TOKEN_BYTE_LENGTH)
        expires_at = None
        if expires_in_days is not None:
            if expires_in_days <= 0:
                raise ValidationError("expires_in_days must be positive")
            expires_at = _utcnow() + timedelta(days=expires_in_days)

        prefix = label or _token_prefix(plaintext)
        token = AuthToken(
            user_id=user_id,
            token_hash=_hash_token(plaintext),
            token_prefix=prefix[:64],
            expires_at=expires_at,
        )
        self._session.add(token)
        self._session.flush()
        return plaintext, token

    def authenticate(self, plaintext: str) -> UUID | None:
        if not plaintext:
            return None
        token_hash = _hash_token(plaintext)
        token = self._session.scalar(
            select(AuthToken).where(AuthToken.token_hash == token_hash)
        )
        if token is None:
            return None
        if token.revoked_at is not None:
            return None
        if token.expires_at is not None and token.expires_at <= _utcnow():
            return None
        return token.user_id

    def revoke_by_prefix(self, user_id: UUID, token_prefix: str) -> int:
        if not token_prefix:
            raise ValidationError("token_prefix is required")
        tokens = self._session.scalars(
            select(AuthToken).where(
                AuthToken.user_id == user_id,
                AuthToken.token_prefix == token_prefix,
                AuthToken.revoked_at.is_(None),
            )
        ).all()
        if not tokens:
            raise NotFoundError("auth_token", token_prefix)
        now = _utcnow()
        for token in tokens:
            token.revoked_at = now
        self._session.flush()
        return len(tokens)
