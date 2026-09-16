"""Google Calendar bounded history backfill state on GoogleAccount.calendar_sync_state."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

HISTORY_BACKFILL_KEY = "history_backfill"
HISTORY_BACKFILL_VERSION = 1
CALENDARS_KEY = "calendars"
LAST_HISTORY_CALENDAR_ID_KEY = "last_history_calendar_id"


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CalendarHistoryActiveWindow:
    active_start: datetime
    active_end: datetime
    next_page_token: str | None


@dataclass(frozen=True)
class CalendarHistoryBackfillPlan:
    window: CalendarHistoryActiveWindow | None
    calendar_backfill: dict[str, Any]


def empty_calendar_sync_state() -> dict[str, Any]:
    return {}


def get_history_backfill(state: dict[str, Any]) -> dict[str, Any]:
    backfill = state.get(HISTORY_BACKFILL_KEY)
    if not isinstance(backfill, dict):
        return {}
    return dict(backfill)


def set_history_backfill(state: dict[str, Any], backfill: dict[str, Any]) -> dict[str, Any]:
    updated = dict(state)
    if backfill:
        updated[HISTORY_BACKFILL_KEY] = backfill
    else:
        updated.pop(HISTORY_BACKFILL_KEY, None)
    return updated


def get_calendar_backfill(backfill: dict[str, Any], calendar_id: str) -> dict[str, Any]:
    calendars = backfill.get(CALENDARS_KEY)
    if not isinstance(calendars, dict):
        return {}
    entry = calendars.get(calendar_id)
    if not isinstance(entry, dict):
        return {}
    return sanitize_calendar_backfill(dict(entry))


def set_calendar_backfill(
    backfill: dict[str, Any],
    calendar_id: str,
    calendar_entry: dict[str, Any],
) -> dict[str, Any]:
    backfill = dict(backfill)
    calendars = dict(backfill.get(CALENDARS_KEY) or {})
    if calendar_entry is not None:
        calendars[calendar_id] = sanitize_calendar_backfill(calendar_entry)
    else:
        calendars.pop(calendar_id, None)
    if calendars:
        backfill[CALENDARS_KEY] = calendars
    else:
        backfill.pop(CALENDARS_KEY, None)
    backfill["version"] = HISTORY_BACKFILL_VERSION
    return backfill


def desired_history_window(history_days: int) -> tuple[datetime, datetime]:
    desired_end = utcnow()
    desired_start = desired_end - timedelta(days=history_days)
    return desired_start, desired_end


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


def _parse_optional_datetime(entry: dict[str, Any], key: str) -> datetime | None:
    raw = entry.get(key)
    if raw is None:
        return None
    try:
        return parse_stored_datetime(str(raw))
    except (ValueError, TypeError):
        return None


def _parse_active_history_days(entry: dict[str, Any]) -> int | None:
    raw = entry.get("active_history_days")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _parse_active_page_size(entry: dict[str, Any]) -> int | None:
    raw = entry.get("active_page_size")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _has_active_marker(entry: dict[str, Any]) -> bool:
    return (
        entry.get("active_start") is not None
        or entry.get("active_end") is not None
        or entry.get("next_page_token")
    )


def sanitize_calendar_backfill(entry: dict[str, Any]) -> dict[str, Any]:
    entry = dict(entry)
    active_start = _parse_optional_datetime(entry, "active_start")
    active_end = _parse_optional_datetime(entry, "active_end")
    scanned_start = _parse_optional_datetime(entry, "scanned_start")
    scanned_end = _parse_optional_datetime(entry, "scanned_end")
    active_history_days = _parse_active_history_days(entry)

    if (
        active_start is None
        or active_end is None
        or active_start >= active_end
        or (_has_active_marker(entry) and active_history_days is None)
    ):
        entry.pop("active_start", None)
        entry.pop("active_end", None)
        entry.pop("next_page_token", None)
        entry.pop("active_history_days", None)
        entry.pop("active_page_size", None)
    else:
        entry["active_start"] = format_stored_datetime(active_start)
        entry["active_end"] = format_stored_datetime(active_end)
        if active_history_days is not None:
            entry["active_history_days"] = active_history_days
        else:
            entry.pop("active_history_days", None)
        active_page_size = _parse_active_page_size(entry)
        if active_page_size is not None:
            entry["active_page_size"] = active_page_size
        else:
            entry.pop("active_page_size", None)

    if (
        scanned_start is not None
        and scanned_end is not None
        and scanned_start < scanned_end
    ):
        entry["scanned_start"] = format_stored_datetime(scanned_start)
        entry["scanned_end"] = format_stored_datetime(scanned_end)
    else:
        entry.pop("scanned_start", None)
        entry.pop("scanned_end", None)

    token = entry.get("next_page_token")
    if token is not None and not str(token):
        entry.pop("next_page_token", None)

    return entry


def continue_active_window(calendar_backfill: dict[str, Any]) -> CalendarHistoryActiveWindow | None:
    calendar_backfill = sanitize_calendar_backfill(calendar_backfill)
    active_start = _parse_optional_datetime(calendar_backfill, "active_start")
    active_end = _parse_optional_datetime(calendar_backfill, "active_end")
    if active_start is None or active_end is None or active_start >= active_end:
        return None
    token = calendar_backfill.get("next_page_token")
    return CalendarHistoryActiveWindow(
        active_start=active_start,
        active_end=active_end,
        next_page_token=str(token) if token else None,
    )


def clear_active_window(calendar_backfill: dict[str, Any]) -> dict[str, Any]:
    calendar_backfill = dict(calendar_backfill)
    calendar_backfill.pop("active_start", None)
    calendar_backfill.pop("active_end", None)
    calendar_backfill.pop("next_page_token", None)
    calendar_backfill.pop("active_history_days", None)
    calendar_backfill.pop("active_page_size", None)
    return calendar_backfill


def _active_page_size_invalid(
    calendar_backfill: dict[str, Any],
    max_limit: int,
    effective_limit: int,
) -> bool:
    active_page_size = _parse_active_page_size(calendar_backfill)
    if active_page_size is None:
        return True
    if active_page_size > max_limit:
        return True
    return active_page_size > effective_limit


def reconcile_active_window(
    calendar_backfill: dict[str, Any],
    history_days: int,
    max_limit: int | None = None,
    effective_limit: int | None = None,
) -> dict[str, Any]:
    calendar_backfill = sanitize_calendar_backfill(calendar_backfill)
    continuing = continue_active_window(calendar_backfill)
    if continuing is None:
        return calendar_backfill

    active_history_days = _parse_active_history_days(calendar_backfill)
    if active_history_days is None:
        return clear_active_window(calendar_backfill)

    if history_days < active_history_days:
        return clear_active_window(calendar_backfill)

    _, desired_end = desired_history_window(history_days)
    if continuing.active_end > desired_end:
        return clear_active_window(calendar_backfill)

    if (
        max_limit is not None
        and effective_limit is not None
        and _active_page_size_invalid(calendar_backfill, max_limit, effective_limit)
    ):
        return clear_active_window(calendar_backfill)

    return calendar_backfill


def plan_history_active_window(
    calendar_backfill: dict[str, Any],
    history_days: int,
) -> CalendarHistoryBackfillPlan:
    calendar_backfill = reconcile_active_window(calendar_backfill, history_days)
    continuing = continue_active_window(calendar_backfill)
    if continuing is not None:
        return CalendarHistoryBackfillPlan(window=continuing, calendar_backfill=calendar_backfill)

    desired_start, desired_end = desired_history_window(history_days)
    scanned_start = _parse_optional_datetime(calendar_backfill, "scanned_start")
    scanned_end = _parse_optional_datetime(calendar_backfill, "scanned_end")

    if scanned_start is None and scanned_end is None:
        if desired_start >= desired_end:
            return CalendarHistoryBackfillPlan(window=None, calendar_backfill=calendar_backfill)
        return CalendarHistoryBackfillPlan(
            window=CalendarHistoryActiveWindow(
                active_start=desired_start,
                active_end=desired_end,
                next_page_token=None,
            ),
            calendar_backfill=calendar_backfill,
        )

    if scanned_start is not None and desired_start < scanned_start:
        return CalendarHistoryBackfillPlan(
            window=CalendarHistoryActiveWindow(
                active_start=desired_start,
                active_end=scanned_start,
                next_page_token=None,
            ),
            calendar_backfill=calendar_backfill,
        )

    if scanned_end is not None and scanned_end < desired_end:
        return CalendarHistoryBackfillPlan(
            window=CalendarHistoryActiveWindow(
                active_start=scanned_end,
                active_end=desired_end,
                next_page_token=None,
            ),
            calendar_backfill=calendar_backfill,
        )

    return CalendarHistoryBackfillPlan(window=None, calendar_backfill=calendar_backfill)


def complete_active_window(calendar_backfill: dict[str, Any]) -> dict[str, Any]:
    calendar_backfill = sanitize_calendar_backfill(calendar_backfill)
    active_start = _parse_optional_datetime(calendar_backfill, "active_start")
    active_end = _parse_optional_datetime(calendar_backfill, "active_end")
    if active_start is None or active_end is None:
        return clear_active_window(calendar_backfill)

    scanned_start = _parse_optional_datetime(calendar_backfill, "scanned_start")
    scanned_end = _parse_optional_datetime(calendar_backfill, "scanned_end")

    if scanned_start is None and scanned_end is None:
        calendar_backfill["scanned_start"] = format_stored_datetime(active_start)
        calendar_backfill["scanned_end"] = format_stored_datetime(active_end)
    elif scanned_end is not None and active_start == scanned_end:
        calendar_backfill["scanned_end"] = format_stored_datetime(active_end)
    elif scanned_start is not None and active_end == scanned_start:
        calendar_backfill["scanned_start"] = format_stored_datetime(active_start)
    else:
        return clear_active_window(calendar_backfill)

    return clear_active_window(calendar_backfill)


def persist_active_page_token(
    calendar_backfill: dict[str, Any],
    window: CalendarHistoryActiveWindow,
    next_page_token: str | None,
) -> dict[str, Any]:
    calendar_backfill = dict(calendar_backfill)
    calendar_backfill["active_start"] = format_stored_datetime(window.active_start)
    calendar_backfill["active_end"] = format_stored_datetime(window.active_end)
    if next_page_token:
        calendar_backfill["next_page_token"] = next_page_token
    else:
        calendar_backfill.pop("next_page_token", None)
    return calendar_backfill


def start_active_window(
    calendar_backfill: dict[str, Any],
    window: CalendarHistoryActiveWindow,
    history_days: int,
    page_size: int,
) -> dict[str, Any]:
    if history_days <= 0:
        raise ValueError("history_days must be positive")
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    calendar_backfill = dict(calendar_backfill)
    calendar_backfill["active_start"] = format_stored_datetime(window.active_start)
    calendar_backfill["active_end"] = format_stored_datetime(window.active_end)
    calendar_backfill["active_history_days"] = history_days
    calendar_backfill["active_page_size"] = page_size
    calendar_backfill.pop("next_page_token", None)
    return calendar_backfill


def reconcile_discovered_calendars(
    backfill: dict[str, Any],
    calendar_ids: list[str],
    history_days: int,
    max_limit: int,
    effective_limit: int,
) -> dict[str, Any]:
    backfill = dict(backfill)
    calendars = dict(backfill.get(CALENDARS_KEY) or {})
    for calendar_id in calendar_ids:
        entry = sanitize_calendar_backfill(dict(calendars.get(calendar_id) or {}))
        reconciled = reconcile_active_window(
            entry,
            history_days,
            max_limit=max_limit,
            effective_limit=effective_limit,
        )
        if reconciled != entry:
            calendars[calendar_id] = reconciled
    if calendars:
        backfill[CALENDARS_KEY] = calendars
    else:
        backfill.pop(CALENDARS_KEY, None)
    backfill["version"] = HISTORY_BACKFILL_VERSION
    return backfill


def select_history_calendar(
    backfill: dict[str, Any],
    calendar_ids: list[str],
    history_days: int,
) -> tuple[str | None, CalendarHistoryBackfillPlan | None, dict[str, Any]]:
    if not calendar_ids:
        return None, None, backfill

    last_id = backfill.get(LAST_HISTORY_CALENDAR_ID_KEY)
    start_idx = 0
    if isinstance(last_id, str) and last_id in calendar_ids:
        start_idx = calendar_ids.index(last_id) + 1
        if start_idx >= len(calendar_ids):
            start_idx = 0

    for offset in range(len(calendar_ids)):
        calendar_id = calendar_ids[(start_idx + offset) % len(calendar_ids)]
        entry = get_calendar_backfill(backfill, calendar_id)
        plan = plan_history_active_window(entry, history_days)
        if plan.window is not None:
            if plan.calendar_backfill != entry:
                backfill = set_calendar_backfill(backfill, calendar_id, plan.calendar_backfill)
            return calendar_id, plan, backfill

    return None, None, backfill


def set_last_history_calendar_id(backfill: dict[str, Any], calendar_id: str) -> dict[str, Any]:
    backfill = dict(backfill)
    backfill[LAST_HISTORY_CALENDAR_ID_KEY] = calendar_id
    backfill["version"] = HISTORY_BACKFILL_VERSION
    return backfill


def plan_calendar_history(
    state: dict[str, Any],
    calendar_id: str,
    history_days: int,
) -> tuple[CalendarHistoryBackfillPlan, dict[str, Any]]:
    backfill = get_history_backfill(state)
    calendar_backfill = get_calendar_backfill(backfill, calendar_id)
    plan = plan_history_active_window(calendar_backfill, history_days)
    entry: dict[str, Any] | None = plan.calendar_backfill
    if plan.window is not None and not entry:
        entry = {}
    updated_backfill = set_calendar_backfill(backfill, calendar_id, entry)
    updated_state = set_history_backfill(state, updated_backfill)
    return plan, updated_state
