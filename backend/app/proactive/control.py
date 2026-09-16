from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import UserSettings
from app.proactive.constants import (
    PROACTIVE_ENABLED_DEFAULT,
    PROACTIVE_INTERVAL_MINUTES_DEFAULT,
    PROACTIVE_INTERVAL_MINUTES_MAX,
    PROACTIVE_INTERVAL_MINUTES_MIN,
)


@dataclass(frozen=True)
class ProactiveControl:
    enabled: bool
    interval_minutes: int


def _bounded_interval(value: int | None) -> int:
    if value is None:
        return PROACTIVE_INTERVAL_MINUTES_DEFAULT
    if value < PROACTIVE_INTERVAL_MINUTES_MIN or value > PROACTIVE_INTERVAL_MINUTES_MAX:
        return PROACTIVE_INTERVAL_MINUTES_DEFAULT
    return value


def _expire_cached_settings(session: Session, user_id: UUID) -> None:
    for obj in list(session.identity_map.values()):
        if isinstance(obj, UserSettings) and obj.user_id == user_id:
            session.expire(obj)


def read_proactive_control(
    session: Session,
    user_id: UUID,
    *,
    for_update: bool = False,
) -> ProactiveControl:
    """Read opt-in control columns from the database, not the identity map.

    for_update=True locks the UserSettings row after LLM/scheduler decision
    work and must not be held across provider calls.
    """
    _expire_cached_settings(session, user_id)
    stmt = select(
        UserSettings.proactive_enabled,
        UserSettings.proactive_interval_minutes,
    ).where(UserSettings.user_id == user_id)
    if for_update:
        stmt = stmt.with_for_update()
    stmt = stmt.execution_options(populate_existing=True)
    row = session.execute(stmt).one_or_none()
    if row is None:
        return ProactiveControl(
            enabled=PROACTIVE_ENABLED_DEFAULT,
            interval_minutes=PROACTIVE_INTERVAL_MINUTES_DEFAULT,
        )
    enabled, interval = row
    return ProactiveControl(enabled=bool(enabled), interval_minutes=_bounded_interval(interval))
