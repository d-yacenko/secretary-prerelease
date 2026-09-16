"""Yandex Mail bounded history backfill state stored on YandexMailAccount.sync_state."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

HISTORY_BACKFILL_KEY = "history_backfill"
HISTORY_BACKFILL_VERSION = 1
MAX_IMAP_UID = 4_294_967_295
INITIAL_HISTORY_BEFORE_UID = MAX_IMAP_UID + 1


def utcnow() -> datetime:
    return datetime.now(UTC)


def utc_today() -> date:
    return utcnow().date()


def safe_scan_boundary_date() -> date:
    return utc_today() + timedelta(days=1)


def parse_stored_date(value: str) -> date:
    return date.fromisoformat(value)


def format_stored_date(d: date) -> str:
    return d.isoformat()


@dataclass(frozen=True)
class MailHistoryActiveScan:
    active_start_date: date
    active_end_date: date
    active_before_uid: int | None


@dataclass(frozen=True)
class MailHistoryBackfillPlan:
    scan: MailHistoryActiveScan | None
    backfill: dict[str, Any]


def get_history_backfill(state: dict[str, Any]) -> dict[str, Any]:
    backfill = state.get(HISTORY_BACKFILL_KEY)
    if not isinstance(backfill, dict):
        return {}
    return sanitize_history_backfill(dict(backfill))


def set_history_backfill(state: dict[str, Any], backfill: dict[str, Any]) -> dict[str, Any]:
    updated = dict(state)
    if backfill:
        updated[HISTORY_BACKFILL_KEY] = sanitize_history_backfill(backfill)
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
    try:
        return parse_stored_date(str(raw))
    except (ValueError, TypeError):
        return None


def _parse_active_history_days(backfill: dict[str, Any]) -> int | None:
    raw = backfill.get("active_history_days")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _parse_active_before_uid(backfill: dict[str, Any]) -> int | None:
    raw = backfill.get("active_before_uid")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _has_active_marker(backfill: dict[str, Any]) -> bool:
    return (
        backfill.get("active_start_date") is not None
        or backfill.get("active_end_date") is not None
        or backfill.get("active_before_uid") is not None
    )


def clear_active_window(backfill: dict[str, Any]) -> dict[str, Any]:
    backfill = dict(backfill)
    backfill.pop("active_start_date", None)
    backfill.pop("active_end_date", None)
    backfill.pop("active_history_days", None)
    backfill.pop("active_before_uid", None)
    return backfill


def sanitize_history_backfill(backfill: dict[str, Any]) -> dict[str, Any]:
    backfill = dict(backfill)
    active_start = _parse_optional_date(backfill, "active_start_date")
    active_end = _parse_optional_date(backfill, "active_end_date")
    scanned_start = _parse_optional_date(backfill, "scanned_start_date")
    scanned_end = _parse_optional_date(backfill, "scanned_end_date")
    active_history_days = _parse_active_history_days(backfill)
    active_before_uid = _parse_active_before_uid(backfill)

    if (
        active_start is None
        or active_end is None
        or active_start >= active_end
        or (_has_active_marker(backfill) and active_history_days is None)
        or (_has_active_marker(backfill) and active_before_uid is None)
    ):
        backfill.pop("active_start_date", None)
        backfill.pop("active_end_date", None)
        backfill.pop("active_history_days", None)
        backfill.pop("active_before_uid", None)
    else:
        backfill["active_start_date"] = format_stored_date(active_start)
        backfill["active_end_date"] = format_stored_date(active_end)
        backfill["active_history_days"] = active_history_days
        backfill["active_before_uid"] = active_before_uid

    if (
        scanned_start is not None
        and scanned_end is not None
        and scanned_start < scanned_end
    ):
        backfill["scanned_start_date"] = format_stored_date(scanned_start)
        backfill["scanned_end_date"] = format_stored_date(scanned_end)
    else:
        backfill.pop("scanned_start_date", None)
        backfill.pop("scanned_end_date", None)

    inbox_uidvalidity = backfill.get("inbox_uidvalidity")
    if inbox_uidvalidity is not None:
        try:
            backfill["inbox_uidvalidity"] = int(inbox_uidvalidity)
        except (TypeError, ValueError):
            backfill.pop("inbox_uidvalidity", None)

    backfill["version"] = HISTORY_BACKFILL_VERSION
    return backfill


def continue_active_scan(backfill: dict[str, Any]) -> MailHistoryActiveScan | None:
    backfill = sanitize_history_backfill(backfill)
    active_start = _parse_optional_date(backfill, "active_start_date")
    active_end = _parse_optional_date(backfill, "active_end_date")
    active_before_uid = _parse_active_before_uid(backfill)
    if (
        active_start is None
        or active_end is None
        or active_start >= active_end
        or active_before_uid is None
    ):
        return None
    return MailHistoryActiveScan(
        active_start_date=active_start,
        active_end_date=active_end,
        active_before_uid=active_before_uid,
    )


def reconcile_active_scan(backfill: dict[str, Any], history_days: int) -> dict[str, Any]:
    backfill = sanitize_history_backfill(backfill)
    continuing = continue_active_scan(backfill)
    if continuing is None:
        return backfill

    active_history_days = _parse_active_history_days(backfill)
    if active_history_days is None:
        return clear_active_window(backfill)

    if history_days < active_history_days:
        return clear_active_window(backfill)

    return backfill


def plan_history_active_scan(
    backfill: dict[str, Any],
    history_days: int,
) -> MailHistoryBackfillPlan:
    backfill = reconcile_active_scan(backfill, history_days)
    continuing = continue_active_scan(backfill)
    if continuing is not None:
        return MailHistoryBackfillPlan(scan=continuing, backfill=backfill)

    desired_start, desired_end = desired_history_window(history_days)
    scanned_start = _parse_optional_date(backfill, "scanned_start_date")
    scanned_end = _parse_optional_date(backfill, "scanned_end_date")

    if scanned_start is None and scanned_end is None:
        if desired_start >= desired_end:
            return MailHistoryBackfillPlan(scan=None, backfill=backfill)
        return MailHistoryBackfillPlan(
            scan=MailHistoryActiveScan(
                active_start_date=desired_start,
                active_end_date=desired_end,
                active_before_uid=None,
            ),
            backfill=backfill,
        )

    if scanned_start is not None and desired_start < scanned_start:
        return MailHistoryBackfillPlan(
            scan=MailHistoryActiveScan(
                active_start_date=desired_start,
                active_end_date=scanned_start,
                active_before_uid=None,
            ),
            backfill=backfill,
        )

    if scanned_end is not None and scanned_end < desired_end:
        return MailHistoryBackfillPlan(
            scan=MailHistoryActiveScan(
                active_start_date=scanned_end,
                active_end_date=desired_end,
                active_before_uid=None,
            ),
            backfill=backfill,
        )

    return MailHistoryBackfillPlan(scan=None, backfill=backfill)


def complete_active_window(backfill: dict[str, Any]) -> dict[str, Any]:
    backfill = sanitize_history_backfill(backfill)
    active_start = _parse_optional_date(backfill, "active_start_date")
    active_end = _parse_optional_date(backfill, "active_end_date")
    if active_start is None or active_end is None:
        return clear_active_window(backfill)

    scanned_start = _parse_optional_date(backfill, "scanned_start_date")
    scanned_end = _parse_optional_date(backfill, "scanned_end_date")

    if scanned_start is None and scanned_end is None:
        backfill["scanned_start_date"] = format_stored_date(active_start)
        backfill["scanned_end_date"] = format_stored_date(active_end)
    elif scanned_end is not None and active_end == scanned_start:
        backfill["scanned_start_date"] = format_stored_date(active_start)
    elif scanned_start is not None and active_start == scanned_end:
        backfill["scanned_end_date"] = format_stored_date(active_end)
    else:
        return clear_active_window(backfill)

    return clear_active_window(backfill)


def start_active_window(
    backfill: dict[str, Any],
    scan: MailHistoryActiveScan,
    history_days: int,
    before_uid: int,
    inbox_uidvalidity: int | None = None,
) -> dict[str, Any]:
    if history_days <= 0:
        raise ValueError("history_days must be positive")
    if before_uid <= 0:
        raise ValueError("before_uid must be positive")
    backfill = dict(backfill)
    backfill["active_start_date"] = format_stored_date(scan.active_start_date)
    backfill["active_end_date"] = format_stored_date(scan.active_end_date)
    backfill["active_history_days"] = history_days
    backfill["active_before_uid"] = before_uid
    if inbox_uidvalidity is not None:
        backfill["inbox_uidvalidity"] = inbox_uidvalidity
    return backfill


def persist_history_cursor(backfill: dict[str, Any], next_before_uid: int) -> dict[str, Any]:
    if next_before_uid <= 0:
        raise ValueError("next_before_uid must be positive")
    backfill = dict(backfill)
    backfill["active_before_uid"] = next_before_uid
    return backfill


def clear_history_if_uidvalidity_changed(
    state: dict[str, Any],
    current_uidvalidity: int,
) -> dict[str, Any]:
    backfill = get_history_backfill(state)
    if not backfill:
        return state
    stored = backfill.get("inbox_uidvalidity")
    if stored is None:
        return state
    if int(stored) != current_uidvalidity:
        return set_history_backfill(state, {})
    return state
