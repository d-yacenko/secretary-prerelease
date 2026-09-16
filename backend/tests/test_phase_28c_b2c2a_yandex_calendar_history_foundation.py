"""PHASE 28C-B2-C2-A — Yandex Calendar past-coverage foundation."""

from datetime import UTC, datetime, timedelta

import pytest

from app.connectors.yandex.calendar_history_state import (
    clear_stale_reset_coverage,
    complete_active_history_range,
    continue_active_history_range,
    desired_past_history_window,
    format_stored_datetime,
    get_calendar_entry,
    mark_initial_coverage_complete,
    plan_calendar_history,
    plan_history_active_range,
    reconcile_active_history_range,
    sanitize_calendar_history_state,
    select_history_calendar,
    set_calendar_entry,
    set_last_history_calendar_href,
    start_active_history_range,
)

FIXED_NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)
CAL_A = "/calendars/user/a/"
CAL_B = "/calendars/user/b/"
CAL_REMOVED = "/calendars/user/removed/"


@pytest.fixture(autouse=True)
def fixed_utcnow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.connectors.yandex.calendar_history_state.utcnow",
        lambda: FIXED_NOW,
    )


def test_missing_covered_window_start_stays_unknown() -> None:
    entry = {
        "sync_token": "token-1",
        "covered_window_end": format_stored_datetime(FIXED_NOW + timedelta(days=30)),
    }
    sanitized = sanitize_calendar_history_state(entry)
    assert sanitized.get("covered_window_start") is None
    assert sanitized["sync_token"] == "token-1"


def test_never_infer_start_from_sync_token_or_end() -> None:
    covered_end = FIXED_NOW + timedelta(days=60)
    entry = {
        "sync_token": "steady-token",
        "covered_window_end": format_stored_datetime(covered_end),
        "backfill_cursor": format_stored_datetime(FIXED_NOW - timedelta(days=60)),
    }
    plan = plan_history_active_range(entry, history_days=60)
    assert plan.range is not None
    assert plan.range.active_end == FIXED_NOW
    assert sanitize_calendar_history_state(entry).get("covered_window_start") is None


def test_initial_desired_history_plans_full_past_window() -> None:
    entry = {"sync_token": "token"}
    plan = plan_history_active_range(entry, history_days=60)
    assert plan.range is not None
    assert plan.range.active_start == FIXED_NOW - timedelta(days=60)
    assert plan.range.active_end == FIXED_NOW


def test_increase_plans_only_missing_older_interval() -> None:
    covered_start = FIXED_NOW - timedelta(days=30)
    entry = {
        "covered_window_start": format_stored_datetime(covered_start),
        "covered_window_end": format_stored_datetime(FIXED_NOW + timedelta(days=30)),
    }
    plan = plan_history_active_range(entry, history_days=90)
    assert plan.range is not None
    assert plan.range.active_end == covered_start
    assert plan.range.active_start == FIXED_NOW - timedelta(days=90)


def test_decrease_plans_no_older_work() -> None:
    covered_start = FIXED_NOW - timedelta(days=90)
    entry = {
        "covered_window_start": format_stored_datetime(covered_start),
        "covered_window_end": format_stored_datetime(FIXED_NOW),
    }
    plan = plan_history_active_range(entry, history_days=14)
    assert plan.range is None
    assert get_calendar_entry({"calendars": {CAL_A: entry}}, CAL_A)["covered_window_start"] == (
        format_stored_datetime(covered_start)
    )


def test_increase_reuses_truthful_broader_coverage() -> None:
    covered_start = FIXED_NOW - timedelta(days=90)
    entry = {
        "covered_window_start": format_stored_datetime(covered_start),
        "covered_window_end": format_stored_datetime(FIXED_NOW),
    }
    plan = plan_history_active_range(entry, history_days=90)
    assert plan.range is None


def test_time_drift_preserves_active_frozen_range(monkeypatch: pytest.MonkeyPatch) -> None:
    later = FIXED_NOW + timedelta(days=1)
    monkeypatch.setattr(
        "app.connectors.yandex.calendar_history_state.utcnow",
        lambda: later,
    )
    frozen_start = FIXED_NOW - timedelta(days=60)
    frozen_end = FIXED_NOW
    entry = {
        "history_backfill_start": format_stored_datetime(frozen_start),
        "history_backfill_end": format_stored_datetime(frozen_end),
        "history_backfill_days": 60,
        "history_backfill_cursor": format_stored_datetime(frozen_start + timedelta(days=10)),
    }
    reconciled = reconcile_active_history_range(entry, history_days=60)
    continuing = continue_active_history_range(reconciled)
    assert continuing is not None
    assert continuing.active_start == frozen_start
    assert continuing.active_end == frozen_end
    assert continuing.history_backfill_cursor == frozen_start + timedelta(days=10)


def test_policy_narrowing_abandons_active_without_changing_coverage() -> None:
    covered_start = FIXED_NOW - timedelta(days=90)
    entry = {
        "covered_window_start": format_stored_datetime(covered_start),
        "covered_window_end": format_stored_datetime(FIXED_NOW),
        "sync_token": "keep-token",
        "history_backfill_start": format_stored_datetime(FIXED_NOW - timedelta(days=90)),
        "history_backfill_end": format_stored_datetime(FIXED_NOW),
        "history_backfill_days": 90,
        "history_backfill_cursor": format_stored_datetime(FIXED_NOW - timedelta(days=45)),
    }
    reconciled = reconcile_active_history_range(entry, history_days=14)
    assert reconciled.get("history_backfill_cursor") is None
    assert reconciled.get("history_backfill_start") is None
    assert reconciled["sync_token"] == "keep-token"
    assert reconciled["covered_window_start"] == format_stored_datetime(covered_start)


def test_policy_increase_preserves_active_range() -> None:
    active_start = FIXED_NOW - timedelta(days=30)
    active_end = FIXED_NOW - timedelta(days=15)
    entry = {
        "history_backfill_start": format_stored_datetime(active_start),
        "history_backfill_end": format_stored_datetime(active_end),
        "history_backfill_days": 30,
        "history_backfill_cursor": format_stored_datetime(active_start + timedelta(days=5)),
    }
    plan = plan_history_active_range(entry, history_days=90)
    assert plan.range is not None
    assert plan.range.active_start == active_start
    assert plan.range.history_backfill_cursor == active_start + timedelta(days=5)


def test_older_gap_completion_does_not_move_covered_start() -> None:
    covered_start = datetime(2026, 8, 1, tzinfo=UTC)
    covered_end = datetime(2026, 9, 1, tzinfo=UTC)
    active_start = datetime(2026, 6, 1, tzinfo=UTC)
    active_end = datetime(2026, 7, 1, tzinfo=UTC)
    entry = {
        "covered_window_start": format_stored_datetime(covered_start),
        "covered_window_end": format_stored_datetime(covered_end),
        "history_backfill_start": format_stored_datetime(active_start),
        "history_backfill_end": format_stored_datetime(active_end),
        "history_backfill_days": 90,
        "history_backfill_cursor": format_stored_datetime(active_start + timedelta(days=5)),
    }
    completed = complete_active_history_range(entry)
    assert completed["covered_window_start"] == format_stored_datetime(covered_start)
    assert completed["covered_window_end"] == format_stored_datetime(covered_end)
    assert completed.get("history_backfill_start") is None
    assert completed.get("history_backfill_cursor") is None


def test_contiguous_completion_moves_covered_window_start_backward() -> None:
    covered_start = FIXED_NOW - timedelta(days=30)
    active_start = FIXED_NOW - timedelta(days=90)
    active_end = covered_start
    entry = {
        "covered_window_start": format_stored_datetime(covered_start),
        "covered_window_end": format_stored_datetime(FIXED_NOW),
        "history_backfill_start": format_stored_datetime(active_start),
        "history_backfill_end": format_stored_datetime(active_end),
        "history_backfill_days": 90,
    }
    completed = complete_active_history_range(entry)
    assert completed.get("history_backfill_start") is None
    assert completed["covered_window_start"] == format_stored_datetime(active_start)


def test_first_completion_establishes_covered_window_start() -> None:
    active_start = FIXED_NOW - timedelta(days=60)
    active_end = FIXED_NOW
    entry = {
        "covered_window_end": format_stored_datetime(FIXED_NOW + timedelta(days=30)),
        "history_backfill_start": format_stored_datetime(active_start),
        "history_backfill_end": format_stored_datetime(active_end),
        "history_backfill_days": 60,
    }
    completed = complete_active_history_range(entry)
    assert completed["covered_window_start"] == format_stored_datetime(active_start)
    assert completed.get("history_backfill_start") is None


def test_overlap_out_of_order_does_not_move_covered_start() -> None:
    covered_start = FIXED_NOW - timedelta(days=30)
    covered_end = FIXED_NOW
    active_start = FIXED_NOW - timedelta(days=20)
    active_end = FIXED_NOW - timedelta(days=5)
    entry = {
        "covered_window_start": format_stored_datetime(covered_start),
        "covered_window_end": format_stored_datetime(covered_end),
        "history_backfill_start": format_stored_datetime(active_start),
        "history_backfill_end": format_stored_datetime(active_end),
        "history_backfill_days": 60,
    }
    completed = complete_active_history_range(entry)
    assert completed["covered_window_start"] == format_stored_datetime(covered_start)
    assert completed["covered_window_end"] == format_stored_datetime(covered_end)
    assert completed.get("history_backfill_start") is None


def test_non_contiguous_completion_does_not_claim_gap() -> None:
    covered_start = FIXED_NOW - timedelta(days=60)
    covered_end = FIXED_NOW - timedelta(days=30)
    active_start = FIXED_NOW - timedelta(days=20)
    active_end = FIXED_NOW - timedelta(days=10)
    entry = {
        "covered_window_start": format_stored_datetime(covered_start),
        "covered_window_end": format_stored_datetime(covered_end),
        "history_backfill_start": format_stored_datetime(active_start),
        "history_backfill_end": format_stored_datetime(active_end),
        "history_backfill_days": 60,
    }
    completed = complete_active_history_range(entry)
    assert completed["covered_window_start"] == format_stored_datetime(covered_start)
    assert completed["covered_window_end"] == format_stored_datetime(covered_end)
    assert completed.get("history_backfill_start") is None


def test_inverted_coverage_pair_clears_start_preserves_end_and_token() -> None:
    covered_end = FIXED_NOW
    entry = {
        "covered_window_start": format_stored_datetime(FIXED_NOW),
        "covered_window_end": format_stored_datetime(covered_end),
        "sync_token": "steady-token",
    }
    sanitized = sanitize_calendar_history_state(entry)
    assert sanitized.get("covered_window_start") is None
    assert sanitized["covered_window_end"] == format_stored_datetime(covered_end)
    assert sanitized["sync_token"] == "steady-token"


def test_malformed_active_state_clears_safely() -> None:
    entry = {
        "history_backfill_start": format_stored_datetime(FIXED_NOW - timedelta(days=10)),
        "sync_token": "token",
        "backfill_cursor": format_stored_datetime(FIXED_NOW - timedelta(days=30)),
    }
    sanitized = sanitize_calendar_history_state(entry)
    assert sanitized.get("history_backfill_start") is None
    assert sanitized["sync_token"] == "token"
    assert sanitized.get("backfill_cursor") is not None


def test_valid_sync_token_survives_malformed_history_state() -> None:
    entry = {
        "sync_token": "steady",
        "pending_sync_token": "pending",
        "history_backfill_start": "bad-date",
        "history_backfill_end": format_stored_datetime(FIXED_NOW),
    }
    sanitized = sanitize_calendar_history_state(entry)
    assert sanitized["sync_token"] == "steady"
    assert sanitized["pending_sync_token"] == "pending"
    assert sanitized.get("history_backfill_start") is None


def test_calendar_a_b_state_isolation() -> None:
    state = {
        "calendars": {
            CAL_A: {
                "covered_window_start": format_stored_datetime(FIXED_NOW - timedelta(days=30)),
                "sync_token": "a-token",
            },
            CAL_B: {"sync_token": "b-token"},
        }
    }
    entry_b = dict(state["calendars"][CAL_B])
    entry_b["history_backfill_start"] = format_stored_datetime(FIXED_NOW - timedelta(days=14))
    entry_b["history_backfill_end"] = format_stored_datetime(FIXED_NOW)
    entry_b["history_backfill_days"] = 14
    updated = set_calendar_entry(state, CAL_B, entry_b)
    assert updated["calendars"][CAL_A]["sync_token"] == "a-token"
    assert updated["calendars"][CAL_B]["history_backfill_start"] is not None


def test_removed_calendar_state_retained() -> None:
    state = {
        "calendars": {
            CAL_REMOVED: {
                "sync_token": "removed-token",
                "covered_window_end": format_stored_datetime(FIXED_NOW),
            }
        }
    }
    updated = set_calendar_entry(
        state,
        CAL_A,
        {"sync_token": "new-token"},
    )
    assert updated["calendars"][CAL_REMOVED]["sync_token"] == "removed-token"


def test_round_robin_candidate_order_and_wrap() -> None:
    state = {
        "calendars": {
            CAL_A: {
                "covered_window_start": format_stored_datetime(FIXED_NOW - timedelta(days=30)),
            },
            CAL_B: {
                "covered_window_start": format_stored_datetime(FIXED_NOW - timedelta(days=30)),
            },
        },
        "last_history_calendar_href": CAL_A,
    }
    href, plan, _ = select_history_calendar(state, [CAL_A, CAL_B], history_days=90)
    assert href == CAL_B
    assert plan is not None
    assert plan.range is not None

    state = set_last_history_calendar_href(state, CAL_B)
    href2, plan2, _ = select_history_calendar(state, [CAL_A, CAL_B], history_days=90)
    assert href2 == CAL_A
    assert plan2 is not None


def test_root_state_and_unknown_key_preservation() -> None:
    state = {
        "normalization_version": 2,
        "custom_marker": True,
        "calendars": {CAL_A: {"sync_token": "token"}},
    }
    plan, updated = plan_calendar_history(state, CAL_A, history_days=60)
    assert plan.range is not None
    assert updated["normalization_version"] == 2
    assert updated["custom_marker"] is True


def test_stale_reset_helper_clears_coverage_and_history_only() -> None:
    entry = {
        "sync_token": "token",
        "pending_sync_token": "pending",
        "backfill_cursor": format_stored_datetime(FIXED_NOW - timedelta(days=30)),
        "covered_window_start": format_stored_datetime(FIXED_NOW - timedelta(days=60)),
        "covered_window_end": format_stored_datetime(FIXED_NOW),
        "history_backfill_start": format_stored_datetime(FIXED_NOW - timedelta(days=90)),
        "history_backfill_end": format_stored_datetime(FIXED_NOW - timedelta(days=60)),
        "history_backfill_days": 90,
        "display_name": "Work",
    }
    reset = clear_stale_reset_coverage(entry)
    assert reset.get("covered_window_start") is None
    assert reset.get("covered_window_end") is None
    assert reset.get("history_backfill_start") is None
    assert reset["sync_token"] == "token"
    assert reset["pending_sync_token"] == "pending"
    assert reset.get("backfill_cursor") is not None
    assert reset["display_name"] == "Work"


def test_mark_initial_coverage_complete_helper() -> None:
    entry = {"sync_token": "token"}
    range_start = FIXED_NOW - timedelta(days=30)
    range_end = FIXED_NOW + timedelta(days=30)
    marked = mark_initial_coverage_complete(entry, range_start, range_end)
    assert marked["covered_window_start"] == format_stored_datetime(range_start)
    assert marked["covered_window_end"] == format_stored_datetime(range_end)
    assert marked["sync_token"] == "token"


def test_start_active_history_range_freezes_fields() -> None:
    entry = {"sync_token": "token"}
    start = FIXED_NOW - timedelta(days=60)
    end = FIXED_NOW
    started = start_active_history_range(entry, start, end, history_days=60)
    assert started["history_backfill_start"] == format_stored_datetime(start)
    assert started["history_backfill_end"] == format_stored_datetime(end)
    assert started["history_backfill_days"] == 60
    assert started.get("history_backfill_cursor") is None


def test_desired_past_history_window_uses_now_not_future_horizon() -> None:
    start, end = desired_past_history_window(30)
    assert end == FIXED_NOW
    assert start == FIXED_NOW - timedelta(days=30)


def test_cursor_outside_frozen_range_cleared() -> None:
    entry = {
        "history_backfill_start": format_stored_datetime(FIXED_NOW - timedelta(days=30)),
        "history_backfill_end": format_stored_datetime(FIXED_NOW),
        "history_backfill_days": 30,
        "history_backfill_cursor": format_stored_datetime(FIXED_NOW + timedelta(days=1)),
    }
    sanitized = sanitize_calendar_history_state(entry)
    assert sanitized.get("history_backfill_cursor") is None
