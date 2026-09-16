import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.google.constants import OAUTH_STATE_TTL_MINUTES
from app.connectors.google.errors import GoogleOAuthError
from app.db.models import OAuthState


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_oauth_state(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


class OAuthStateService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_state(self, user_id: UUID) -> str:
        state = secrets.token_urlsafe(32)
        row = OAuthState(
            user_id=user_id,
            state_hash=hash_oauth_state(state),
            expires_at=utcnow() + timedelta(minutes=OAUTH_STATE_TTL_MINUTES),
        )
        self._session.add(row)
        self._session.flush()
        return state

    def consume_state(self, state: str) -> UUID:
        state_hash = hash_oauth_state(state)
        row = self._session.scalar(
            select(OAuthState)
            .where(OAuthState.state_hash == state_hash)
            .with_for_update()
        )
        if row is None:
            raise GoogleOAuthError("invalid oauth state")
        if row.consumed_at is not None:
            raise GoogleOAuthError("oauth state already used")
        if row.expires_at < utcnow():
            raise GoogleOAuthError("oauth state expired")
        row.consumed_at = utcnow()
        self._session.flush()
        return row.user_id
