"""Gmail bounded history backfill state stored on GoogleAccount.gmail_sync_state."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

HISTORY_BACKFILL_KEY = "history_backfill"
HISTORY_BACKFILL_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(UTC)


def utc_today() -> date:
    return utcnow().date()


def safe_scan_boundary_date() -> date:
    """Exclusive upper bound for Gmail `before:` on the current UTC day window."""
    return utc_today() + timedelta(days=1)


def date_to_gmail(d: date) -> str:
    return d.strftime("%Y/%m/%d")


def parse_stored_date(value: str) -> date:
    if "/" in value:
        year, month, day = value.split("/", 2)
        return date(int(year), int(month), int(day))
    return date.fromisoformat(value)


def format_stored_date(d: date) -> str:
    return d.isoformat()


@dataclass(frozen=True)
class HistoryActiveWindow:
    active_start: date
    active_end: date
    next_page_token: str | None


@dataclass(frozen=True)
class HistoryBackfillPlan:
    window: HistoryActiveWindow | None
    backfill: dict[str, Any]


def empty_gmail_sync_state() -> dict[str, Any]:
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


def desired_history_window(history_days: int) -> tuple[date, date]:
    desired_end = safe_scan_boundary_date()
    desired_start = utc_today() - timedelta(days=history_days)
    return desired_start, desired_end


def _parse_optional_date(backfill: dict[str, Any], key: str) -> date | None:
    raw = backfill.get(key)
    if raw is None:
        return None
    return parse_stored_date(str(raw))


def continue_active_window(backfill: dict[str, Any]) -> HistoryActiveWindow | None:
    active_start = _parse_optional_date(backfill, "active_start")
    active_end = _parse_optional_date(backfill, "active_end")
    if active_start is None or active_end is None:
        return None
    if active_start >= active_end:
        return None
    token = backfill.get("next_page_token")
    return HistoryActiveWindow(
        active_start=active_start,
        active_end=active_end,
        next_page_token=str(token) if token else None,
    )


def _active_window_within_desired(
    active_start: date,
    active_end: date,
    desired_start: date,
    desired_end: date,
) -> bool:
    return (
        active_start < active_end
        and active_start >= desired_start
        and active_end <= desired_end
    )


def clear_active_window(backfill: dict[str, Any]) -> dict[str, Any]:
    backfill = dict(backfill)
    backfill.pop("active_start", None)
    backfill.pop("active_end", None)
    backfill.pop("next_page_token", None)
    return backfill


def reconcile_active_window(backfill: dict[str, Any], history_days: int) -> dict[str, Any]:
    continuing = continue_active_window(backfill)
    if continuing is None:
        return backfill
    desired_start, desired_end = desired_history_window(history_days)
    if _active_window_within_desired(
        continuing.active_start,
        continuing.active_end,
        desired_start,
        desired_end,
    ):
        return backfill
    return clear_active_window(backfill)


def plan_history_active_window(
    backfill: dict[str, Any],
    history_days: int,
) -> HistoryBackfillPlan:
    backfill = reconcile_active_window(backfill, history_days)
    continuing = continue_active_window(backfill)
    if continuing is not None:
        return HistoryBackfillPlan(window=continuing, backfill=backfill)

    desired_start, desired_end = desired_history_window(history_days)
    scanned_start = _parse_optional_date(backfill, "scanned_start")
    scanned_end = _parse_optional_date(backfill, "scanned_end")

    if scanned_start is None and scanned_end is None:
        if desired_start >= desired_end:
            return HistoryBackfillPlan(window=None, backfill=backfill)
        return HistoryBackfillPlan(
            window=HistoryActiveWindow(
                active_start=desired_start,
                active_end=desired_end,
                next_page_token=None,
            ),
            backfill=backfill,
        )

    if scanned_start is not None and desired_start < scanned_start:
        return HistoryBackfillPlan(
            window=HistoryActiveWindow(
                active_start=desired_start,
                active_end=scanned_start,
                next_page_token=None,
            ),
            backfill=backfill,
        )

    if scanned_end is not None and scanned_end < desired_end:
        return HistoryBackfillPlan(
            window=HistoryActiveWindow(
                active_start=scanned_end,
                active_end=desired_end,
                next_page_token=None,
            ),
            backfill=backfill,
        )

    return HistoryBackfillPlan(window=None, backfill=backfill)


def complete_active_window(backfill: dict[str, Any]) -> dict[str, Any]:
    active_start = _parse_optional_date(backfill, "active_start")
    active_end = _parse_optional_date(backfill, "active_end")
    if active_start is None or active_end is None:
        backfill.pop("active_start", None)
        backfill.pop("active_end", None)
        backfill.pop("next_page_token", None)
        return backfill

    scanned_start = _parse_optional_date(backfill, "scanned_start")
    scanned_end = _parse_optional_date(backfill, "scanned_end")

    if scanned_start is None and scanned_end is None:
        scanned_start = active_start
        scanned_end = active_end
    elif scanned_end is not None and active_start == scanned_end:
        scanned_end = active_end
    elif scanned_start is not None and active_end == scanned_start:
        scanned_start = active_start
    else:
        scanned_start = active_start
        scanned_end = active_end

    backfill["scanned_start"] = format_stored_date(scanned_start)
    backfill["scanned_end"] = format_stored_date(scanned_end)
    backfill.pop("active_start", None)
    backfill.pop("active_end", None)
    backfill.pop("next_page_token", None)
    return backfill


def persist_active_page_token(
    backfill: dict[str, Any],
    window: HistoryActiveWindow,
    next_page_token: str | None,
) -> dict[str, Any]:
    backfill = dict(backfill)
    backfill["version"] = HISTORY_BACKFILL_VERSION
    backfill["active_start"] = format_stored_date(window.active_start)
    backfill["active_end"] = format_stored_date(window.active_end)
    if next_page_token:
        backfill["next_page_token"] = next_page_token
    else:
        backfill.pop("next_page_token", None)
    return backfill


def start_active_window(backfill: dict[str, Any], window: HistoryActiveWindow) -> dict[str, Any]:
    backfill = dict(backfill)
    backfill["version"] = HISTORY_BACKFILL_VERSION
    backfill["active_start"] = format_stored_date(window.active_start)
    backfill["active_end"] = format_stored_date(window.active_end)
    backfill.pop("next_page_token", None)
    return backfill
