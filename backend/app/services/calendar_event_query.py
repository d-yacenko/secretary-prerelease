"""Shared calendar-event interval overlap used by Today and Unified Week.

Inclusion when ``due_at`` (event end) is present:

    start_at < window_end AND due_at > window_start

When ``due_at`` is absent, membership is start-in-window:

    window_start <= start_at < window_end

This matches existing Today calendar semantics. Week does not use Inbox
``feed_at``, ``created_at``, or Review Marker chronology.
"""

from datetime import UTC, datetime, time, timedelta

from sqlalchemy import and_, or_

from app.db.models import Object

WEEK_CALENDAR_PROVIDERS = ("google_calendar", "yandex_calendar")


def active_event_predicates(user_id):
    return (
        Object.user_id == user_id,
        Object.kind == "event",
        Object.state != "rejected",
        Object.deleted_at.is_(None),
        or_(Object.status.is_(None), Object.status != "deleted"),
        Object.start_at.is_not(None),
    )


def event_overlaps_window(window_start: datetime, window_end: datetime):
    return or_(
        and_(
            Object.due_at.is_(None),
            Object.start_at >= window_start,
            Object.start_at < window_end,
        ),
        and_(
            Object.due_at.is_not(None),
            Object.start_at < window_end,
            Object.due_at > window_start,
        ),
    )


def event_is_all_day(obj: Object) -> bool:
    """Detect all-day from the current canonical DATE representation.

    Google ``start.date`` / Yandex ``VALUE=DATE`` are stored as UTC midnight
    ``start_at`` and exclusive UTC midnight ``due_at`` with a whole-day length.
    """
    metadata = obj.metadata_ or {}
    if metadata.get("all_day") is True:
        return True
    start = obj.start_at
    end = obj.due_at
    if start is None or end is None:
        return False
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    if start_utc.time() != time.min or end_utc.time() != time.min:
        return False
    delta = end_utc - start_utc
    return delta >= timedelta(days=1) and delta % timedelta(days=1) == timedelta(0)
