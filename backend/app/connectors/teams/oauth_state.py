import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.teams.constants import OAUTH_STATE_TTL_MINUTES
from app.connectors.teams.errors import TeamsOAuthError
from app.db.models import TeamsOAuthState


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_oauth_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


hash_oauth_state = hash_oauth_secret


@dataclass(frozen=True)
class CreatedTeamsOAuthState:
    state: str
    nonce: str


@dataclass(frozen=True)
class ConsumedTeamsOAuthState:
    user_id: UUID
    nonce_hash: str


class TeamsOAuthStateService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_state(self, user_id: UUID) -> CreatedTeamsOAuthState:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        row = TeamsOAuthState(
            user_id=user_id,
            state_hash=hash_oauth_secret(state),
            nonce_hash=hash_oauth_secret(nonce),
            expires_at=utcnow() + timedelta(minutes=OAUTH_STATE_TTL_MINUTES),
        )
        self._session.add(row)
        self._session.flush()
        return CreatedTeamsOAuthState(state=state, nonce=nonce)

    def consume_state(self, state: str) -> ConsumedTeamsOAuthState:
        state_hash = hash_oauth_secret(state)
        row = self._session.scalar(
            select(TeamsOAuthState)
            .where(TeamsOAuthState.state_hash == state_hash)
            .with_for_update()
        )
        if row is None:
            raise TeamsOAuthError("invalid oauth state")
        if row.consumed_at is not None:
            raise TeamsOAuthError("oauth state already used")
        if row.expires_at < utcnow():
            raise TeamsOAuthError("oauth state expired")
        row.consumed_at = utcnow()
        self._session.flush()
        return ConsumedTeamsOAuthState(user_id=row.user_id, nonce_hash=row.nonce_hash)
