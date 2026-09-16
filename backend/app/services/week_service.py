"""Read-only Monday–Sunday projection of materialized calendar event Objects.

Week A does not expand RRULE, synthesize occurrences, or mutate providers.
Google Calendar and Yandex Calendar remain the authoritative event stores.
"""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Object, UserSettings
from app.domain.planned_execution import KIND_TASK
from app.domain.task_lifecycle import (
    TASK_STATUS_DONE,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_OPEN,
)
from app.domain.temporal_hint import KIND_TEMPORAL_HINT, LIFECYCLE_UNRESOLVED
from app.services.calendar_event_query import (
    WEEK_CALENDAR_PROVIDERS,
    active_event_predicates,
    event_is_all_day,
    event_overlaps_window,
)
from app.services.errors import ValidationError
from app.services.provenance import REJECTED_STATE
from app.services.temporal_signals_constants import (
    METADATA_LIFECYCLE,
    TEMPORAL_SIGNALS_ENABLED_DEFAULT,
    WEEK_MAX_TEMPORAL_HINTS,
)

WEEK_MAX_EVENTS = 500
WEEK_MAX_SCHEDULED_WORK = 500
VISIBLE_SCHEDULED_WORK_STATUSES = frozenset(
    {
        TASK_STATUS_OPEN,
        TASK_STATUS_IN_PROGRESS,
        TASK_STATUS_DONE,
    }
)


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def parse_week_start(raw: str | None, tz: ZoneInfo, *, now_local: datetime | None = None) -> date:
    if raw is None or not str(raw).strip():
        local = now_local if now_local is not None else datetime.now(tz)
        return monday_of(local.date())
    text = str(raw).strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError("invalid week_start") from exc
    if parsed.weekday() != 0:
        raise ValidationError("week_start must be a Monday")
    return parsed


def local_week_window(week_start: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    window_start = datetime.combine(week_start, time.min, tzinfo=tz)
    window_end = window_start + timedelta(days=7)
    return window_start, window_end


def _all_day_date_range(obj: Object) -> tuple[date, date] | None:
    if not event_is_all_day(obj) or obj.start_at is None or obj.due_at is None:
        return None
    start_date = obj.start_at.astimezone(UTC).date()
    end_date = obj.due_at.astimezone(UTC).date()
    if end_date <= start_date:
        return None
    return start_date, end_date


def event_occupies_day(obj: Object, day_date: date, day_start: datetime, day_end: datetime) -> bool:
    all_day_range = _all_day_date_range(obj)
    if all_day_range is not None:
        start_date, end_date = all_day_range
        return start_date <= day_date < end_date
    if obj.start_at is None:
        return False
    if obj.due_at is None:
        return day_start <= obj.start_at < day_end
    return obj.start_at < day_end and obj.due_at > day_start


def _event_sort_key(obj: Object) -> tuple[bool, datetime, str]:
    start = obj.start_at or datetime.min.replace(tzinfo=UTC)
    return (not event_is_all_day(obj), start, str(obj.id))


def scheduled_work_occupies_day(obj: Object, day_start: datetime, day_end: datetime) -> bool:
    if obj.planned_start_at is None or obj.planned_end_at is None:
        return False
    return obj.planned_start_at < day_end and obj.planned_end_at > day_start


def _scheduled_work_sort_key(obj: Object) -> tuple[datetime, str]:
    start = obj.planned_start_at or datetime.min.replace(tzinfo=UTC)
    return (start, str(obj.id))


def _hint_sort_key(obj: Object) -> tuple[datetime, str]:
    start = obj.start_at or datetime.min.replace(tzinfo=UTC)
    return (start, str(obj.id))


class WeekService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def snapshot(
        self,
        *,
        week_start: str | None = None,
        timezone: str | None = None,
        reference_at: datetime | None = None,
    ) -> dict:
        tz_name = timezone or settings.secretary_timezone
        tz = ZoneInfo(tz_name)
        now_local = (
            reference_at.astimezone(tz) if reference_at is not None else datetime.now(tz)
        )
        start_date = parse_week_start(week_start, tz, now_local=now_local)
        window_start, window_end = local_week_window(start_date, tz)
        events = self._events_for_window(window_start, window_end)
        scheduled = self._scheduled_work_for_window(window_start, window_end)
        hints = (
            self._hints_for_window(window_start, window_end)
            if self._temporal_hints_enabled()
            else []
        )
        today_date = now_local.date()
        days = []
        for offset in range(7):
            day_date = start_date + timedelta(days=offset)
            day_start = datetime.combine(day_date, time.min, tzinfo=tz)
            day_end = day_start + timedelta(days=1)
            day_events = [
                obj for obj in events if event_occupies_day(obj, day_date, day_start, day_end)
            ]
            day_events.sort(key=_event_sort_key)
            day_scheduled = [
                obj
                for obj in scheduled
                if scheduled_work_occupies_day(obj, day_start, day_end)
            ]
            day_scheduled.sort(key=_scheduled_work_sort_key)
            day_hints = [
                obj for obj in hints if event_occupies_day(obj, day_date, day_start, day_end)
            ]
            day_hints.sort(key=_hint_sort_key)
            days.append(
                {
                    "date": day_date.isoformat(),
                    "is_today": day_date == today_date,
                    "events": day_events,
                    "scheduled_work": day_scheduled,
                    "temporal_hints": day_hints,
                }
            )
        return {
            "week_start": start_date.isoformat(),
            "week_end": (start_date + timedelta(days=7)).isoformat(),
            "timezone": tz_name,
            "window_start": window_start,
            "window_end": window_end,
            "today_date": today_date.isoformat(),
            "is_current_week": start_date == monday_of(today_date),
            "days": days,
        }

    def _temporal_hints_enabled(self) -> bool:
        row = self._session.get(UserSettings, self._user_id)
        if row is None:
            return TEMPORAL_SIGNALS_ENABLED_DEFAULT
        return bool(row.temporal_signals_enabled)

    def _events_for_window(self, window_start: datetime, window_end: datetime) -> list[Object]:
        stmt = (
            select(Object)
            .where(
                *active_event_predicates(self._user_id),
                Object.provider.in_(WEEK_CALENDAR_PROVIDERS),
                event_overlaps_window(window_start, window_end),
            )
            .order_by(Object.start_at.asc(), Object.id.asc())
            .limit(WEEK_MAX_EVENTS)
        )
        return list(self._session.scalars(stmt))

    def _scheduled_work_for_window(
        self, window_start: datetime, window_end: datetime
    ) -> list[Object]:
        stmt = (
            select(Object)
            .where(
                Object.user_id == self._user_id,
                Object.kind == KIND_TASK,
                Object.deleted_at.is_(None),
                Object.status.in_(VISIBLE_SCHEDULED_WORK_STATUSES),
                Object.planned_start_at.is_not(None),
                Object.planned_end_at.is_not(None),
                Object.planned_start_at < window_end,
                Object.planned_end_at > window_start,
            )
            .order_by(Object.planned_start_at.asc(), Object.id.asc())
            .limit(WEEK_MAX_SCHEDULED_WORK)
        )
        return list(self._session.scalars(stmt))

    def _hints_for_window(self, window_start: datetime, window_end: datetime) -> list[Object]:
        lifecycle = Object.metadata_[METADATA_LIFECYCLE].as_string()
        stmt = (
            select(Object)
            .where(
                Object.user_id == self._user_id,
                Object.kind == KIND_TEMPORAL_HINT,
                Object.state != REJECTED_STATE,
                Object.deleted_at.is_(None),
                or_(Object.status.is_(None), Object.status != "deleted"),
                Object.start_at.is_not(None),
                or_(lifecycle.is_(None), lifecycle == LIFECYCLE_UNRESOLVED),
                event_overlaps_window(window_start, window_end),
            )
            .order_by(Object.start_at.asc(), Object.id.asc())
            .limit(WEEK_MAX_TEMPORAL_HINTS)
        )
        return list(self._session.scalars(stmt))
