"""Legacy Telegram Bot API link-state persistence retained for compatibility.

Do not use this store to re-enable live Bot linking or ingress.
"""

from __future__ import annotations

import hashlib
import secrets
import string
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.telegram.constants import (
    LINK_STATE_TOKEN_LENGTH,
    LINK_STATE_TTL_SECONDS,
    TELEGRAM_START_PARAM_ALLOWED,
    TELEGRAM_START_PARAM_MAX_LENGTH,
)
from app.db.models import TelegramLinkState

_ALPHABET = string.ascii_letters + string.digits + "_-"


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_link_state(raw_state: str) -> str:
    return hashlib.sha256(raw_state.encode("utf-8")).hexdigest()


def generate_link_state_token() -> str:
    token = "".join(secrets.choice(_ALPHABET) for _ in range(LINK_STATE_TOKEN_LENGTH))
    if len(token) > TELEGRAM_START_PARAM_MAX_LENGTH:
        raise RuntimeError("telegram start parameter exceeds Telegram length limit")
    if any(ch not in TELEGRAM_START_PARAM_ALLOWED for ch in token):
        raise RuntimeError("telegram start parameter contains illegal characters")
    return token


class TelegramLinkStateStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_for_user(self, user_id: UUID) -> tuple[str, TelegramLinkState]:
        raw_state = generate_link_state_token()
        row = TelegramLinkState(
            id=uuid4(),
            user_id=user_id,
            state_hash=hash_link_state(raw_state),
            expires_at=utcnow() + timedelta(seconds=LINK_STATE_TTL_SECONDS),
        )
        self._session.add(row)
        self._session.flush()
        return raw_state, row

    def lock_by_raw_state(self, raw_state: str) -> TelegramLinkState | None:
        state_hash = hash_link_state(raw_state)
        return self._session.scalar(
            select(TelegramLinkState)
            .where(TelegramLinkState.state_hash == state_hash)
            .with_for_update()
        )

    def consume(self, row: TelegramLinkState) -> None:
        row.consumed_at = utcnow()
        self._session.flush()
