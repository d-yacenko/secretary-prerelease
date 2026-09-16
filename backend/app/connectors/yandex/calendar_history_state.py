"""Yandex Calendar past-coverage and older-history state on account sync_state calendars."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

LAST_HISTORY_CALENDAR_HREF_KEY = "last_history_calendar_href"
CALENDARS_KEY = "calendars"


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CalendarHistoryActiveRange:
    active_start: datetime
    active_end: datetime
    history_backfill_cursor: datetime | None
    history_backfill_slice_end: datetime | None


@dataclass(frozen=True)
class CalendarHistoryBackfillPlan:
    range: CalendarHistoryActiveRange | None
    calendar_entry: dict[str, Any]


def format_stored_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_stored_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def desired_past_history_window(history_days: int) -> tuple[datetime, datetime]:
    desired_end = utcnow()
    desired_start = desired_end - timedelta(days=history_days)
    return desired_start, desired_end


def _parse_optional_datetime(entry: dict[str, Any], key: str) -> datetime | None:
    raw = entry.get(key)
    if raw is None:
        return None
    try:
        return parse_stored_datetime(str(raw))
    except (ValueError, TypeError):
        return None


def _parse_history_backfill_days(entry: dict[str, Any]) -> int | None:
    raw = entry.get("history_backfill_days")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _has_active_history_marker(entry: dict[str, Any]) -> bool:
    return (
        entry.get("history_backfill_start") is not None
        or entry.get("history_backfill_end") is not None
        or entry.get("history_backfill_cursor") is not None
        or entry.get("history_backfill_slice_end") is not None
    )


def clear_active_history_range(entry: dict[str, Any]) -> dict[str, Any]:
    entry = dict(entry)
    entry.pop("history_backfill_start", None)
    entry.pop("history_backfill_end", None)
    entry.pop("history_backfill_cursor", None)
    entry.pop("history_backfill_slice_end", None)
    entry.pop("history_backfill_days", None)
    return entry


def sanitize_calendar_history_state(entry: dict[str, Any]) -> dict[str, Any]:
    entry = dict(entry)

    covered_start = _parse_optional_datetime(entry, "covered_window_start")
    covered_end = _parse_optional_datetime(entry, "covered_window_end")
    if (
        covered_start is not None
        and covered_end is not None
        and covered_start >= covered_end
    ):
        entry.pop("covered_window_start", None)
        covered_start = None
    if covered_start is not None:
        entry["covered_window_start"] = format_stored_datetime(covered_start)
    else:
        entry.pop("covered_window_start", None)
    if covered_end is not None:
        entry["covered_window_end"] = format_stored_datetime(covered_end)
    else:
        entry.pop("covered_window_end", None)

    active_start = _parse_optional_datetime(entry, "history_backfill_start")
    active_end = _parse_optional_datetime(entry, "history_backfill_end")
    history_backfill_days = _parse_history_backfill_days(entry)
    cursor = _parse_optional_datetime(entry, "history_backfill_cursor")
    slice_end = _parse_optional_datetime(entry, "history_backfill_slice_end")

    if (
        active_start is None
        or active_end is None
        or active_start >= active_end
        or (_has_active_history_marker(entry) and history_backfill_days is None)
    ):
        entry = clear_active_history_range(entry)
    else:
        entry["history_backfill_start"] = format_stored_datetime(active_start)
        entry["history_backfill_end"] = format_stored_datetime(active_end)
        entry["history_backfill_days"] = history_backfill_days
        if cursor is not None:
            if cursor < active_start or cursor >= active_end:
                entry.pop("history_backfill_cursor", None)
                entry.pop("history_backfill_slice_end", None)
            else:
                entry["history_backfill_cursor"] = format_stored_datetime(cursor)
        else:
            entry.pop("history_backfill_cursor", None)
        if slice_end is not None:
            if slice_end <= active_start or slice_end > active_end:
                entry.pop("history_backfill_slice_end", None)
            else:
                entry["history_backfill_slice_end"] = format_stored_datetime(slice_end)
        else:
            entry.pop("history_backfill_slice_end", None)

    return entry


def continue_active_history_range(entry: dict[str, Any]) -> CalendarHistoryActiveRange | None:
    entry = sanitize_calendar_history_state(entry)
    active_start = _parse_optional_datetime(entry, "history_backfill_start")
    active_end = _parse_optional_datetime(entry, "history_backfill_end")
    if active_start is None or active_end is None or active_start >= active_end:
        return None
    cursor = _parse_optional_datetime(entry, "history_backfill_cursor")
    slice_end = _parse_optional_datetime(entry, "history_backfill_slice_end")
    return CalendarHistoryActiveRange(
        active_start=active_start,
        active_end=active_end,
        history_backfill_cursor=cursor,
        history_backfill_slice_end=slice_end,
    )


def reconcile_active_history_range(entry: dict[str, Any], history_days: int) -> dict[str, Any]:
    entry = sanitize_calendar_history_state(entry)
    continuing = continue_active_history_range(entry)
    if continuing is None:
        return entry

    active_history_days = _parse_history_backfill_days(entry)
    if active_history_days is None:
        return clear_active_history_range(entry)

    if history_days < active_history_days:
        return clear_active_history_range(entry)

    return entry


def plan_history_active_range(
    entry: dict[str, Any],
    history_days: int,
) -> CalendarHistoryBackfillPlan:
    entry = reconcile_active_history_range(entry, history_days)
    continuing = continue_active_history_range(entry)
    if continuing is not None:
        return CalendarHistoryBackfillPlan(range=continuing, calendar_entry=entry)

    desired_start, desired_end = desired_past_history_window(history_days)
    covered_start = _parse_optional_datetime(entry, "covered_window_start")

    if covered_start is None:
        if desired_start >= desired_end:
            return CalendarHistoryBackfillPlan(range=None, calendar_entry=entry)
        return CalendarHistoryBackfillPlan(
            range=CalendarHistoryActiveRange(
                active_start=desired_start,
                active_end=desired_end,
                history_backfill_cursor=None,
                history_backfill_slice_end=None,
            ),
            calendar_entry=entry,
        )

    if desired_start < covered_start:
        return CalendarHistoryBackfillPlan(
            range=CalendarHistoryActiveRange(
                active_start=desired_start,
                active_end=covered_start,
                history_backfill_cursor=None,
                history_backfill_slice_end=None,
            ),
            calendar_entry=entry,
        )

    return CalendarHistoryBackfillPlan(range=None, calendar_entry=entry)


def complete_active_history_range(entry: dict[str, Any]) -> dict[str, Any]:
    entry = sanitize_calendar_history_state(entry)
    active_start = _parse_optional_datetime(entry, "history_backfill_start")
    active_end = _parse_optional_datetime(entry, "history_backfill_end")
    if active_start is None or active_end is None:
        return clear_active_history_range(entry)

    covered_start = _parse_optional_datetime(entry, "covered_window_start")
    covered_end = _parse_optional_datetime(entry, "covered_window_end")

    if covered_start is None:
        if (covered_end is not None and active_end <= covered_end) or covered_end is None:
            entry["covered_window_start"] = format_stored_datetime(active_start)
        return clear_active_history_range(entry)

    if active_end == covered_start:
        entry["covered_window_start"] = format_stored_datetime(active_start)

    return clear_active_history_range(entry)


def start_active_history_range(
    entry: dict[str, Any],
    active_start: datetime,
    active_end: datetime,
    history_days: int,
) -> dict[str, Any]:
    if history_days <= 0:
        raise ValueError("history_days must be positive")
    entry = dict(entry)
    entry["history_backfill_start"] = format_stored_datetime(active_start)
    entry["history_backfill_end"] = format_stored_datetime(active_end)
    entry["history_backfill_days"] = history_days
    entry.pop("history_backfill_cursor", None)
    entry.pop("history_backfill_slice_end", None)
    return sanitize_calendar_history_state(entry)


def persist_history_backfill_cursor(
    entry: dict[str, Any],
    cursor: datetime,
    slice_end: datetime | None,
) -> dict[str, Any]:
    entry = dict(entry)
    entry["history_backfill_cursor"] = format_stored_datetime(cursor)
    if slice_end is not None:
        entry["history_backfill_slice_end"] = format_stored_datetime(slice_end)
    else:
        entry.pop("history_backfill_slice_end", None)
    return sanitize_calendar_history_state(entry)


def mark_initial_coverage_complete(
    entry: dict[str, Any],
    range_start: datetime,
    range_end: datetime,
) -> dict[str, Any]:
    entry = dict(entry)
    entry["covered_window_start"] = format_stored_datetime(range_start)
    entry["covered_window_end"] = format_stored_datetime(range_end)
    return sanitize_calendar_history_state(entry)


def clear_stale_reset_coverage(entry: dict[str, Any]) -> dict[str, Any]:
    entry = dict(entry)
    entry.pop("covered_window_start", None)
    entry.pop("covered_window_end", None)
    return clear_active_history_range(entry)


def get_calendar_entry(state: dict[str, Any], calendar_href: str) -> dict[str, Any]:
    calendars = state.get(CALENDARS_KEY)
    if not isinstance(calendars, dict):
        return {}
    entry = calendars.get(calendar_href)
    if not isinstance(entry, dict):
        return {}
    return sanitize_calendar_history_state(dict(entry))


def set_calendar_entry(
    state: dict[str, Any],
    calendar_href: str,
    calendar_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    updated = dict(state)
    calendars = dict(updated.get(CALENDARS_KEY) or {})
    if calendar_entry is not None:
        calendars[calendar_href] = sanitize_calendar_history_state(calendar_entry)
    else:
        calendars.pop(calendar_href, None)
    if calendars:
        updated[CALENDARS_KEY] = calendars
    else:
        updated.pop(CALENDARS_KEY, None)
    return updated


def plan_calendar_history(
    state: dict[str, Any],
    calendar_href: str,
    history_days: int,
) -> tuple[CalendarHistoryBackfillPlan, dict[str, Any]]:
    entry = get_calendar_entry(state, calendar_href)
    plan = plan_history_active_range(entry, history_days)
    if plan.range is not None and not entry:
        entry = {}
    updated_state = set_calendar_entry(state, calendar_href, plan.calendar_entry)
    return plan, updated_state


def select_history_calendar(
    state: dict[str, Any],
    calendar_hrefs: list[str],
    history_days: int,
) -> tuple[str | None, CalendarHistoryBackfillPlan | None, dict[str, Any]]:
    if not calendar_hrefs:
        return None, None, state

    last_href = state.get(LAST_HISTORY_CALENDAR_HREF_KEY)
    start_idx = 0
    if isinstance(last_href, str) and last_href in calendar_hrefs:
        start_idx = calendar_hrefs.index(last_href) + 1
        if start_idx >= len(calendar_hrefs):
            start_idx = 0

    for offset in range(len(calendar_hrefs)):
        calendar_href = calendar_hrefs[(start_idx + offset) % len(calendar_hrefs)]
        entry = get_calendar_entry(state, calendar_href)
        plan = plan_history_active_range(entry, history_days)
        if plan.range is not None:
            if plan.calendar_entry != entry:
                state = set_calendar_entry(state, calendar_href, plan.calendar_entry)
            return calendar_href, plan, state

    return None, None, state


def set_last_history_calendar_href(state: dict[str, Any], calendar_href: str) -> dict[str, Any]:
    updated = dict(state)
    updated[LAST_HISTORY_CALENDAR_HREF_KEY] = calendar_href
    return updated
