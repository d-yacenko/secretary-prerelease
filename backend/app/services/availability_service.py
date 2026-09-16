"""Derived read-only free/busy from materialized confirmed calendar events.

Availability is computed on demand from Google/Yandex calendar Objects.
It does not persist slots, copy provider calendars, or call providers.
Only HARD confirmed calendar commitments occupy busy time.

Interval arithmetic uses UTC instants so DST-equal ZoneInfo wall times are
not treated as a fixed 24-hour civil day.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import Object
from app.services.calendar_event_query import (
    WEEK_CALENDAR_PROVIDERS,
    active_event_predicates,
)
from app.services.errors import ValidationError

MIN_DURATION_MINUTES_MIN = 5
MIN_DURATION_MINUTES_MAX = 1440
DEFAULT_MIN_DURATION_MINUTES = 30
MAX_WINDOW = timedelta(days=7)


def availability_hard_event_overlaps_window(window_start: datetime, window_end: datetime):
    """Availability overlap: unknown-end events fail closed if they started before window_end.

    Known-end uses ordinary half-open interval overlap. Unknown-end has no lower bound
    at window_start because the event cannot be proven finished. This is intentionally
    stricter than Week/Today ``event_overlaps_window``.
    """
    return or_(
        and_(
            Object.due_at.is_(None),
            Object.start_at < window_end,
        ),
        and_(
            Object.due_at.is_not(None),
            Object.start_at < window_end,
            Object.due_at > window_start,
        ),
    )


def parse_aware_instant(raw: str, field: str) -> datetime:
    text = str(raw).strip()
    if not text:
        raise ValidationError(f"naive {field}")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"naive {field}")
    return parsed


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _instant_delta(start_at: datetime, end_at: datetime) -> timedelta:
    return _as_utc(end_at) - _as_utc(start_at)


def _validate_window(
    start_at: datetime,
    end_at: datetime,
    min_duration_minutes: int,
) -> None:
    if start_at.tzinfo is None or start_at.utcoffset() is None:
        raise ValidationError("naive start_at")
    if end_at.tzinfo is None or end_at.utcoffset() is None:
        raise ValidationError("naive end_at")
    if _as_utc(end_at) <= _as_utc(start_at):
        raise ValidationError("end_at must be after start_at")
    if _instant_delta(start_at, end_at) > MAX_WINDOW:
        raise ValidationError("window larger than 7 days")
    if not MIN_DURATION_MINUTES_MIN <= min_duration_minutes <= MIN_DURATION_MINUTES_MAX:
        raise ValidationError("invalid min_duration_minutes")


def _clip_to_window(
    start_at: datetime,
    end_at: datetime,
    window_start: datetime,
    window_end: datetime,
) -> tuple[datetime, datetime] | None:
    start_utc = _as_utc(start_at)
    end_utc = _as_utc(end_at)
    clipped_start = max(window_start, start_utc)
    clipped_end = min(window_end, end_utc)
    if clipped_start < clipped_end:
        return clipped_start, clipped_end
    return None


def _merge_busy(
    intervals: list[tuple[datetime, datetime, list[UUID]]],
) -> list[tuple[datetime, datetime, list[UUID]]]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: (item[0], item[1], str(item[2][0])))
    merged: list[tuple[datetime, datetime, list[UUID]]] = [ordered[0]]
    for start_at, end_at, event_ids in ordered[1:]:
        prev_start, prev_end, prev_ids = merged[-1]
        if start_at <= prev_end:
            combined_ids = sorted({*prev_ids, *event_ids}, key=str)
            merged[-1] = (
                prev_start,
                max(prev_end, end_at),
                combined_ids,
            )
        else:
            merged.append((start_at, end_at, event_ids))
    return merged


def _free_intervals(
    window_start: datetime,
    window_end: datetime,
    busy: list[tuple[datetime, datetime, list[UUID]]],
    min_duration: timedelta,
) -> list[tuple[datetime, datetime, int]]:
    free: list[tuple[datetime, datetime, int]] = []
    cursor = window_start
    for start_at, end_at, _event_ids in busy:
        if start_at > cursor:
            gap = start_at - cursor
            if gap >= min_duration:
                free.append((cursor, start_at, int(gap.total_seconds() // 60)))
        cursor = max(cursor, end_at)
    if cursor < window_end:
        gap = window_end - cursor
        if gap >= min_duration:
            free.append((cursor, window_end, int(gap.total_seconds() // 60)))
    return free


class AvailabilityService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def query(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        timezone: str,
        min_duration_minutes: int = DEFAULT_MIN_DURATION_MINUTES,
    ) -> dict:
        _validate_window(start_at, end_at, min_duration_minutes)
        window_start = _as_utc(start_at)
        window_end = _as_utc(end_at)
        events = self._events_for_window(window_start, window_end)
        unknown_ids: list[UUID] = []
        busy_raw: list[tuple[datetime, datetime, list[UUID]]] = []
        for obj in events:
            if obj.due_at is None:
                unknown_ids.append(obj.id)
                continue
            clipped = _clip_to_window(obj.start_at, obj.due_at, window_start, window_end)
            if clipped is None:
                continue
            busy_raw.append((clipped[0], clipped[1], [obj.id]))
        busy = _merge_busy(busy_raw)
        complete = not unknown_ids
        min_duration = timedelta(minutes=min_duration_minutes)
        free = (
            _free_intervals(window_start, window_end, busy, min_duration)
            if complete
            else []
        )
        return {
            "timezone": timezone,
            "window_start": window_start,
            "window_end": window_end,
            "min_duration_minutes": min_duration_minutes,
            "availability_complete": complete,
            "busy_intervals": [
                {
                    "start_at": item[0],
                    "end_at": item[1],
                    "event_ids": item[2],
                }
                for item in busy
            ],
            "free_intervals": [
                {
                    "start_at": item[0],
                    "end_at": item[1],
                    "duration_minutes": item[2],
                }
                for item in free
            ],
            "unknown_end_event_ids": sorted(unknown_ids, key=str),
        }

    def _events_for_window(self, window_start: datetime, window_end: datetime) -> list[Object]:
        stmt = (
            select(Object)
            .where(
                *active_event_predicates(self._user_id),
                Object.provider.in_(WEEK_CALENDAR_PROVIDERS),
                availability_hard_event_overlaps_window(window_start, window_end),
            )
            .order_by(Object.start_at.asc(), Object.id.asc())
        )
        return list(self._session.scalars(stmt))
