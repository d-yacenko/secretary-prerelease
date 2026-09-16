"""Mattermost bounded history backfill state nested under per-channel sync_state."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

CHANNELS_KEY = "channels"
HISTORY_BACKFILL_KEY = "history_backfill"
HISTORY_BACKFILL_VERSION = 1
LAST_HISTORY_CHANNEL_ID_KEY = "last_history_channel_id"


def utcnow() -> datetime:
    return datetime.now(UTC)


def utcnow_ms() -> int:
    return int(utcnow().timestamp() * 1000)


def desired_history_window_ms(history_days: int) -> tuple[int, int]:
    now = utcnow()
    end_ms = int(now.timestamp() * 1000)
    start_ms = int((now - timedelta(days=history_days)).timestamp() * 1000)
    return start_ms, end_ms


@dataclass(frozen=True)
class MattermostHistoryActiveScan:
    active_start_ms: int
    active_end_ms: int
    active_before_post_id: str | None
    active_oldest_processed_post_id: str | None


@dataclass(frozen=True)
class MattermostHistoryBackfillPlan:
    scan: MattermostHistoryActiveScan | None
    backfill: dict[str, Any]


def get_history_backfill(channel_entry: dict[str, Any]) -> dict[str, Any]:
    backfill = channel_entry.get(HISTORY_BACKFILL_KEY)
    if not isinstance(backfill, dict):
        return {}
    return sanitize_history_backfill(dict(backfill))


def set_history_backfill(
    channel_entry: dict[str, Any],
    backfill: dict[str, Any] | None,
) -> dict[str, Any]:
    updated = dict(channel_entry)
    if backfill:
        updated[HISTORY_BACKFILL_KEY] = sanitize_history_backfill(backfill)
    else:
        updated.pop(HISTORY_BACKFILL_KEY, None)
    return sanitize_channel_history_state(updated)


def _parse_optional_ms(backfill: dict[str, Any], key: str) -> int | None:
    raw = backfill.get(key)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


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


def _parse_post_id(backfill: dict[str, Any], key: str) -> str | None:
    raw = backfill.get(key)
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    return value


def _has_active_marker(backfill: dict[str, Any]) -> bool:
    return (
        backfill.get("active_start_ms") is not None
        or backfill.get("active_end_ms") is not None
        or backfill.get("active_before_post_id") is not None
        or backfill.get("active_oldest_processed_post_id") is not None
    )


def clear_active_history(backfill: dict[str, Any]) -> dict[str, Any]:
    backfill = dict(backfill)
    backfill.pop("active_start_ms", None)
    backfill.pop("active_end_ms", None)
    backfill.pop("active_history_days", None)
    backfill.pop("active_before_post_id", None)
    backfill.pop("active_oldest_processed_post_id", None)
    return backfill


def sanitize_history_backfill(backfill: dict[str, Any]) -> dict[str, Any]:
    backfill = dict(backfill)
    active_start = _parse_optional_ms(backfill, "active_start_ms")
    active_end = _parse_optional_ms(backfill, "active_end_ms")
    covered_start = _parse_optional_ms(backfill, "covered_start_ms")
    active_history_days = _parse_active_history_days(backfill)
    active_before_post_id = backfill.get("active_before_post_id")
    if active_before_post_id is not None:
        active_before_post_id = str(active_before_post_id).strip()
        if not active_before_post_id:
            active_before_post_id = None

    covered_oldest_post_id = _parse_post_id(backfill, "covered_oldest_post_id")
    active_oldest_processed_post_id = _parse_post_id(
        backfill,
        "active_oldest_processed_post_id",
    )

    if covered_start is not None:
        backfill["covered_start_ms"] = covered_start
    else:
        backfill.pop("covered_start_ms", None)

    if covered_oldest_post_id is not None:
        backfill["covered_oldest_post_id"] = covered_oldest_post_id
    else:
        backfill.pop("covered_oldest_post_id", None)

    active_invalid = (
        active_start is None
        or active_end is None
        or active_start >= active_end
        or (_has_active_marker(backfill) and active_history_days is None)
        or (
            backfill.get("active_before_post_id") is not None
            and active_before_post_id is None
        )
    )
    if active_invalid:
        backfill = clear_active_history(backfill)
    else:
        backfill["active_start_ms"] = active_start
        backfill["active_end_ms"] = active_end
        backfill["active_history_days"] = active_history_days
        if active_before_post_id is not None:
            backfill["active_before_post_id"] = active_before_post_id
        else:
            backfill.pop("active_before_post_id", None)
        if active_oldest_processed_post_id is not None:
            backfill["active_oldest_processed_post_id"] = active_oldest_processed_post_id
        else:
            backfill.pop("active_oldest_processed_post_id", None)

    backfill["version"] = HISTORY_BACKFILL_VERSION
    return backfill


def sanitize_channel_history_state(channel_entry: dict[str, Any]) -> dict[str, Any]:
    entry = dict(channel_entry)
    backfill = entry.get(HISTORY_BACKFILL_KEY)
    if isinstance(backfill, dict):
        entry[HISTORY_BACKFILL_KEY] = sanitize_history_backfill(backfill)
    elif HISTORY_BACKFILL_KEY in entry:
        entry.pop(HISTORY_BACKFILL_KEY, None)
    return entry


def continue_active_scan(backfill: dict[str, Any]) -> MattermostHistoryActiveScan | None:
    backfill = sanitize_history_backfill(backfill)
    active_start = _parse_optional_ms(backfill, "active_start_ms")
    active_end = _parse_optional_ms(backfill, "active_end_ms")
    if active_start is None or active_end is None or active_start >= active_end:
        return None
    active_before = backfill.get("active_before_post_id")
    if active_before is not None:
        active_before = str(active_before).strip() or None
    oldest_processed = _parse_post_id(backfill, "active_oldest_processed_post_id")
    return MattermostHistoryActiveScan(
        active_start_ms=active_start,
        active_end_ms=active_end,
        active_before_post_id=active_before,
        active_oldest_processed_post_id=oldest_processed,
    )


def reconcile_active_scan(backfill: dict[str, Any], history_days: int) -> dict[str, Any]:
    backfill = sanitize_history_backfill(backfill)
    continuing = continue_active_scan(backfill)
    if continuing is None:
        return backfill

    active_history_days = _parse_active_history_days(backfill)
    if active_history_days is None:
        return clear_active_history(backfill)

    if history_days < active_history_days:
        return clear_active_history(backfill)

    return backfill


def plan_history_active_scan(
    backfill: dict[str, Any],
    history_days: int,
) -> MattermostHistoryBackfillPlan:
    backfill = reconcile_active_scan(backfill, history_days)
    continuing = continue_active_scan(backfill)
    if continuing is not None:
        return MattermostHistoryBackfillPlan(scan=continuing, backfill=backfill)

    desired_start, desired_end = desired_history_window_ms(history_days)
    covered_start = _parse_optional_ms(backfill, "covered_start_ms")

    if covered_start is None:
        if desired_start >= desired_end:
            return MattermostHistoryBackfillPlan(scan=None, backfill=backfill)
        return MattermostHistoryBackfillPlan(
            scan=MattermostHistoryActiveScan(
                active_start_ms=desired_start,
                active_end_ms=desired_end,
                active_before_post_id=None,
                active_oldest_processed_post_id=None,
            ),
            backfill=backfill,
        )

    if desired_start < covered_start:
        before_anchor = _parse_post_id(backfill, "covered_oldest_post_id")
        return MattermostHistoryBackfillPlan(
            scan=MattermostHistoryActiveScan(
                active_start_ms=desired_start,
                active_end_ms=covered_start,
                active_before_post_id=before_anchor,
                active_oldest_processed_post_id=None,
            ),
            backfill=backfill,
        )

    return MattermostHistoryBackfillPlan(scan=None, backfill=backfill)


def complete_active_history(backfill: dict[str, Any]) -> dict[str, Any]:
    backfill = sanitize_history_backfill(backfill)
    active_start = _parse_optional_ms(backfill, "active_start_ms")
    active_end = _parse_optional_ms(backfill, "active_end_ms")
    if active_start is None or active_end is None:
        return clear_active_history(backfill)

    covered_start = _parse_optional_ms(backfill, "covered_start_ms")
    oldest_processed = _parse_post_id(backfill, "active_oldest_processed_post_id")

    if covered_start is None:
        backfill["covered_start_ms"] = active_start
        if oldest_processed is not None:
            backfill["covered_oldest_post_id"] = oldest_processed
        return clear_active_history(backfill)

    if active_end == covered_start:
        backfill["covered_start_ms"] = active_start
        if oldest_processed is not None:
            backfill["covered_oldest_post_id"] = oldest_processed
        return clear_active_history(backfill)

    return clear_active_history(backfill)


def start_active_history_range(
    backfill: dict[str, Any],
    active_start_ms: int,
    active_end_ms: int,
    history_days: int,
    before_post_id: str | None = None,
) -> dict[str, Any]:
    if history_days <= 0:
        raise ValueError("history_days must be positive")
    if active_start_ms <= 0 or active_end_ms <= 0 or active_start_ms >= active_end_ms:
        raise ValueError("active history range must be positive and non-empty")
    backfill = dict(backfill)
    backfill["active_start_ms"] = active_start_ms
    backfill["active_end_ms"] = active_end_ms
    backfill["active_history_days"] = history_days
    if before_post_id is not None:
        before_post_id = before_post_id.strip()
        if before_post_id:
            backfill["active_before_post_id"] = before_post_id
        else:
            backfill.pop("active_before_post_id", None)
    else:
        backfill.pop("active_before_post_id", None)
    backfill.pop("active_oldest_processed_post_id", None)
    return sanitize_history_backfill(backfill)


def persist_active_before_post_id(
    backfill: dict[str, Any],
    before_post_id: str,
) -> dict[str, Any]:
    before_post_id = before_post_id.strip()
    if not before_post_id:
        raise ValueError("before_post_id must be non-empty")
    backfill = dict(backfill)
    backfill["active_before_post_id"] = before_post_id
    return sanitize_history_backfill(backfill)


def persist_active_oldest_processed_post_id(
    backfill: dict[str, Any],
    oldest_post_id: str,
) -> dict[str, Any]:
    oldest_post_id = oldest_post_id.strip()
    if not oldest_post_id:
        raise ValueError("oldest_post_id must be non-empty")
    backfill = dict(backfill)
    backfill["active_oldest_processed_post_id"] = oldest_post_id
    return sanitize_history_backfill(backfill)


def get_channel_entry(state: dict[str, Any], channel_id: str) -> dict[str, Any]:
    channels = state.get(CHANNELS_KEY)
    if not isinstance(channels, dict):
        return {}
    entry = channels.get(channel_id)
    if not isinstance(entry, dict):
        return {}
    return sanitize_channel_history_state(dict(entry))


def set_channel_entry(
    state: dict[str, Any],
    channel_id: str,
    channel_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    updated = dict(state)
    channels = dict(updated.get(CHANNELS_KEY) or {})
    if channel_entry is not None:
        channels[channel_id] = sanitize_channel_history_state(channel_entry)
    else:
        channels.pop(channel_id, None)
    if channels:
        updated[CHANNELS_KEY] = channels
    else:
        updated.pop(CHANNELS_KEY, None)
    return updated


def plan_channel_history(
    state: dict[str, Any],
    channel_id: str,
    history_days: int,
) -> tuple[MattermostHistoryBackfillPlan, dict[str, Any]]:
    entry = get_channel_entry(state, channel_id)
    backfill = get_history_backfill(entry)
    plan = plan_history_active_scan(backfill, history_days)
    if plan.scan is not None or backfill:
        entry = set_history_backfill(entry, plan.backfill)
    updated_state = set_channel_entry(state, channel_id, entry if entry else None)
    return plan, updated_state


def select_history_channel(
    state: dict[str, Any],
    channel_ids: list[str],
    history_days: int,
) -> tuple[str | None, MattermostHistoryBackfillPlan | None, dict[str, Any]]:
    if not channel_ids:
        return None, None, state

    last_channel_id = state.get(LAST_HISTORY_CHANNEL_ID_KEY)
    start_idx = 0
    if isinstance(last_channel_id, str) and last_channel_id in channel_ids:
        start_idx = channel_ids.index(last_channel_id) + 1
        if start_idx >= len(channel_ids):
            start_idx = 0

    for offset in range(len(channel_ids)):
        channel_id = channel_ids[(start_idx + offset) % len(channel_ids)]
        plan, state = plan_channel_history(state, channel_id, history_days)
        if plan.scan is not None:
            return channel_id, plan, state

    return None, None, state


def set_last_history_channel_id(state: dict[str, Any], channel_id: str) -> dict[str, Any]:
    updated = dict(state)
    updated[LAST_HISTORY_CHANNEL_ID_KEY] = channel_id
    return updated
