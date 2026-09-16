"""PHASE 28C-B2-C3-A — Mattermost stable history cursor foundation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import httpx
import pytest

from app.connectors.mattermost.mattermost_history_state import (
    complete_active_history,
    continue_active_scan,
    desired_history_window_ms,
    get_channel_entry,
    get_history_backfill,
    persist_active_before_post_id,
    persist_active_oldest_processed_post_id,
    plan_channel_history,
    plan_history_active_scan,
    reconcile_active_scan,
    sanitize_channel_history_state,
    sanitize_history_backfill,
    select_history_channel,
    set_channel_entry,
    set_history_backfill,
    set_last_history_channel_id,
    start_active_history_range,
)
from app.connectors.mattermost.transport import FakeMattermostTransport, MattermostHttpTransport

FIXED_NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)
FIXED_NOW_MS = int(FIXED_NOW.timestamp() * 1000)
CHANNEL_A = "channel-a"
CHANNEL_B = "channel-b"
CHANNEL_REMOVED = "channel-removed"


@pytest.fixture(autouse=True)
def fixed_utcnow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.connectors.mattermost.mattermost_history_state.utcnow",
        lambda: FIXED_NOW,
    )


def _ms(days: float) -> int:
    return int((FIXED_NOW - timedelta(days=days)).timestamp() * 1000)


def _post(post_id: str, channel_id: str, create_at_ms: int) -> dict:
    return {
        "id": post_id,
        "channel_id": channel_id,
        "user_id": "author-1",
        "message": post_id,
        "create_at": create_at_ms,
        "update_at": create_at_ms,
    }


def test_get_posts_before_http_params() -> None:
    client = MagicMock()
    response = MagicMock()
    response.status_code = 200
    response.content = b'{"order":[],"posts":{}}'
    response.json.return_value = {"order": [], "posts": {}}
    client.request.return_value = response

    transport = MattermostHttpTransport(
        "https://mm.example.com",
        "token",
        http_client=client,
    )
    transport.get_posts_before("ch-1", "post-8", 25)
    client.request.assert_called_once()
    call_kwargs = client.request.call_args.kwargs
    assert call_kwargs["params"] == {"before": "post-8", "page": 0, "per_page": 25}


def test_get_posts_before_validation() -> None:
    transport = FakeMattermostTransport()
    with pytest.raises(ValueError, match="channel_id"):
        transport.get_posts_before("", "post-1", 10)
    with pytest.raises(ValueError, match="before_post_id"):
        transport.get_posts_before("ch-1", "", 10)
    with pytest.raises(ValueError, match="per_page"):
        transport.get_posts_before("ch-1", "post-1", 0)


def test_before_cursor_is_exclusive() -> None:
    base_ms = _ms(10)
    posts = [
        _post("p6", "ch-1", base_ms + 1000),
        _post("p7", "ch-1", base_ms + 2000),
        _post("p8", "ch-1", base_ms + 3000),
        _post("p9", "ch-1", base_ms + 4000),
        _post("p10", "ch-1", base_ms + 5000),
    ]
    transport = FakeMattermostTransport(posts_by_channel={"ch-1": posts})
    page = transport.get_posts_before("ch-1", "p8", 10)
    assert set(page.order) == {"p6", "p7"}
    assert "p8" not in page.order


def test_before_cursor_stable_after_newer_posts_inserted() -> None:
    base_ms = _ms(10)
    initial_posts = [
        _post("p6", "ch-1", base_ms + 1000),
        _post("p7", "ch-1", base_ms + 2000),
        _post("p8", "ch-1", base_ms + 3000),
        _post("p9", "ch-1", base_ms + 4000),
        _post("p10", "ch-1", base_ms + 5000),
    ]
    transport = FakeMattermostTransport(posts_by_channel={"ch-1": list(initial_posts)})
    first = transport.get_posts_before("ch-1", "p8", 10)
    assert set(first.order) == {"p6", "p7"}

    transport.posts_by_channel["ch-1"].extend(
        [
            _post("p11", "ch-1", base_ms + 6000),
            _post("p12", "ch-1", base_ms + 7000),
        ]
    )
    second = transport.get_posts_before("ch-1", "p8", 10)
    assert set(second.order) == set(first.order)


def test_no_numeric_page_continuation_in_history_state() -> None:
    backfill = start_active_history_range(
        {},
        active_start_ms=_ms(14),
        active_end_ms=FIXED_NOW_MS,
        history_days=14,
    )
    backfill = persist_active_before_post_id(backfill, "post-anchor")
    assert "page" not in backfill
    channel_entry = set_history_backfill(
        {"bootstrap_complete": True},
        backfill,
    )
    history = channel_entry["history_backfill"]
    assert "page" not in history


def test_initial_14_day_plan() -> None:
    plan = plan_history_active_scan({}, history_days=14)
    assert plan.scan is not None
    assert plan.scan.active_start_ms == _ms(14)
    assert plan.scan.active_end_ms == FIXED_NOW_MS
    assert plan.scan.active_before_post_id is None


def test_completed_14_to_90_plans_only_missing_older_interval() -> None:
    covered_start = _ms(14)
    backfill = sanitize_history_backfill(
        {
            "covered_start_ms": covered_start,
            "covered_oldest_post_id": "p-old",
        }
    )
    plan = plan_history_active_scan(backfill, history_days=90)
    assert plan.scan is not None
    assert plan.scan.active_start_ms == _ms(90)
    assert plan.scan.active_end_ms == covered_start
    assert plan.scan.active_before_post_id == "p-old"


def test_completed_90_to_14_no_work() -> None:
    backfill = sanitize_history_backfill({"covered_start_ms": _ms(90)})
    plan = plan_history_active_scan(backfill, history_days=14)
    assert plan.scan is None


def test_increase_back_to_90_reuses_broader_truthful_coverage() -> None:
    backfill = sanitize_history_backfill({"covered_start_ms": _ms(90)})
    plan = plan_history_active_scan(backfill, history_days=90)
    assert plan.scan is None


def test_active_time_drift_preserves_cursor() -> None:
    backfill = start_active_history_range(
        {},
        active_start_ms=_ms(14),
        active_end_ms=FIXED_NOW_MS,
        history_days=14,
        before_post_id="p7",
    )
    with pytest.MonkeyPatch.context() as mp:
        later = FIXED_NOW + timedelta(days=3)
        mp.setattr(
            "app.connectors.mattermost.mattermost_history_state.utcnow",
            lambda: later,
        )
        reconciled = reconcile_active_scan(backfill, history_days=14)
        continuing = continue_active_scan(reconciled)
    assert continuing is not None
    assert continuing.active_start_ms == _ms(14)
    assert continuing.active_end_ms == FIXED_NOW_MS
    assert continuing.active_before_post_id == "p7"


def test_active_increase_preserves_cursor() -> None:
    backfill = start_active_history_range(
        {},
        active_start_ms=_ms(14),
        active_end_ms=FIXED_NOW_MS,
        history_days=14,
        before_post_id="p7",
    )
    reconciled = reconcile_active_scan(backfill, history_days=90)
    continuing = continue_active_scan(reconciled)
    assert continuing is not None
    assert continuing.active_before_post_id == "p7"
    assert continuing.active_start_ms == _ms(14)


def test_active_decrease_clears_cursor_without_changing_coverage() -> None:
    covered_start = _ms(90)
    backfill = start_active_history_range(
        {"covered_start_ms": covered_start},
        active_start_ms=_ms(14),
        active_end_ms=FIXED_NOW_MS,
        history_days=90,
        before_post_id="p7",
    )
    reconciled = reconcile_active_scan(backfill, history_days=14)
    assert continue_active_scan(reconciled) is None
    assert reconciled.get("covered_start_ms") == covered_start
    assert reconciled.get("active_before_post_id") is None


def test_exact_contiguous_completion_moves_covered_start_backward() -> None:
    covered_start = _ms(14)
    backfill = start_active_history_range(
        {"covered_start_ms": covered_start},
        active_start_ms=_ms(90),
        active_end_ms=covered_start,
        history_days=90,
        before_post_id="p-boundary",
    )
    backfill = persist_active_oldest_processed_post_id(backfill, "p-oldest")
    completed = complete_active_history(backfill)
    assert completed["covered_start_ms"] == _ms(90)
    assert completed["covered_oldest_post_id"] == "p-oldest"
    assert completed.get("active_start_ms") is None


def test_gap_completion_does_not_claim_coverage() -> None:
    covered_start = _ms(30)
    backfill = start_active_history_range(
        {"covered_start_ms": covered_start},
        active_start_ms=_ms(90),
        active_end_ms=_ms(60),
        history_days=90,
    )
    completed = complete_active_history(backfill)
    assert completed["covered_start_ms"] == covered_start
    assert completed.get("covered_oldest_post_id") is None
    assert completed.get("active_start_ms") is None


def test_oldest_processed_becomes_covered_boundary_only_on_truthful_completion() -> None:
    backfill = start_active_history_range(
        {},
        active_start_ms=_ms(14),
        active_end_ms=FIXED_NOW_MS,
        history_days=14,
    )
    backfill = persist_active_oldest_processed_post_id(backfill, "p-oldest")
    assert backfill.get("covered_oldest_post_id") is None
    completed = complete_active_history(backfill)
    assert completed["covered_oldest_post_id"] == "p-oldest"


def test_empty_interval_does_not_invent_post_id() -> None:
    backfill = start_active_history_range(
        {},
        active_start_ms=_ms(14),
        active_end_ms=FIXED_NOW_MS,
        history_days=14,
    )
    completed = complete_active_history(backfill)
    assert completed.get("covered_oldest_post_id") is None
    assert completed["covered_start_ms"] == _ms(14)


def test_malformed_active_state_clears_safely() -> None:
    backfill = sanitize_history_backfill(
        {
            "covered_start_ms": _ms(90),
            "active_start_ms": _ms(14),
            "active_end_ms": FIXED_NOW_MS,
            "active_history_days": 14,
            "active_before_post_id": "",
        }
    )
    assert backfill.get("active_start_ms") is None
    assert backfill.get("active_before_post_id") is None
    assert backfill["covered_start_ms"] == _ms(90)

    backfill = sanitize_history_backfill(
        {
            "covered_start_ms": _ms(90),
            "active_start_ms": FIXED_NOW_MS,
            "active_end_ms": _ms(30),
            "active_history_days": 90,
        }
    )
    assert backfill.get("active_start_ms") is None
    assert backfill["covered_start_ms"] == _ms(90)


def test_history_updates_preserve_forward_checkpoint_fields() -> None:
    entry = {
        "bootstrap_complete": True,
        "last_processed_post_id": "live-post",
        "last_processed_create_at_ms": FIXED_NOW_MS,
        "edit_sweep_watermark_ms": FIXED_NOW_MS - 1000,
        "custom_marker": True,
    }
    backfill = start_active_history_range(
        {},
        active_start_ms=_ms(14),
        active_end_ms=FIXED_NOW_MS,
        history_days=14,
    )
    updated = set_history_backfill(entry, backfill)
    sanitized = sanitize_channel_history_state(updated)
    assert sanitized["bootstrap_complete"] is True
    assert sanitized["last_processed_post_id"] == "live-post"
    assert sanitized["last_processed_create_at_ms"] == FIXED_NOW_MS
    assert sanitized["edit_sweep_watermark_ms"] == FIXED_NOW_MS - 1000
    assert sanitized["custom_marker"] is True


def test_channel_state_isolation() -> None:
    state: dict = {}
    state = set_channel_entry(
        state,
        CHANNEL_A,
        set_history_backfill(
            {"bootstrap_complete": True},
            {"covered_start_ms": _ms(14)},
        ),
    )
    state = set_channel_entry(
        state,
        CHANNEL_B,
        {"bootstrap_complete": True},
    )
    entry_a = get_channel_entry(state, CHANNEL_A)
    entry_b = get_channel_entry(state, CHANNEL_B)
    assert get_history_backfill(entry_a)["covered_start_ms"] == _ms(14)
    assert get_history_backfill(entry_b) == {}


def test_removed_channel_state_retained() -> None:
    state = set_channel_entry(
        {},
        CHANNEL_REMOVED,
        set_history_backfill({}, {"covered_start_ms": _ms(30)}),
    )
    channel_id, _plan, updated = select_history_channel(
        state,
        [CHANNEL_A],
        history_days=14,
    )
    assert channel_id == CHANNEL_A
    removed_entry = get_channel_entry(updated, CHANNEL_REMOVED)
    assert get_history_backfill(removed_entry)["covered_start_ms"] == _ms(30)


def test_new_channel_becomes_candidate() -> None:
    state = set_channel_entry(
        {},
        CHANNEL_A,
        set_history_backfill({}, {"covered_start_ms": _ms(14)}),
    )
    channel_id, plan, _ = select_history_channel(
        state,
        [CHANNEL_A, CHANNEL_B],
        history_days=14,
    )
    assert channel_id == CHANNEL_B
    assert plan is not None
    assert plan.scan is not None


def test_round_robin_order_and_wrap() -> None:
    state = {
        "channels": {
            CHANNEL_A: set_history_backfill(
                {},
                {"covered_start_ms": _ms(30)},
            ),
            CHANNEL_B: set_history_backfill(
                {},
                {"covered_start_ms": _ms(30)},
            ),
        },
        "last_history_channel_id": CHANNEL_A,
    }
    channel_id, plan, _ = select_history_channel(
        state,
        [CHANNEL_A, CHANNEL_B],
        history_days=90,
    )
    assert channel_id == CHANNEL_B
    assert plan is not None

    state = set_last_history_channel_id(state, CHANNEL_B)
    channel_id, plan, _ = select_history_channel(
        state,
        [CHANNEL_A, CHANNEL_B],
        history_days=90,
    )
    assert channel_id == CHANNEL_A
    assert plan is not None


def test_desired_history_window_uses_utc_now() -> None:
    start_ms, end_ms = desired_history_window_ms(14)
    assert end_ms == FIXED_NOW_MS
    assert start_ms == _ms(14)


def test_plan_channel_history_updates_state() -> None:
    state: dict = {}
    plan, updated = plan_channel_history(state, CHANNEL_A, history_days=14)
    assert plan.scan is not None
    entry = get_channel_entry(updated, CHANNEL_A)
    assert get_history_backfill(entry) == {"version": 1}


def test_initial_completion_sets_covered_start() -> None:
    backfill = start_active_history_range(
        {},
        active_start_ms=_ms(14),
        active_end_ms=FIXED_NOW_MS,
        history_days=14,
    )
    completed = complete_active_history(backfill)
    assert completed["covered_start_ms"] == _ms(14)


def test_http_transport_before_validation() -> None:
    client = httpx.Client()
    transport = MattermostHttpTransport("https://mm.example.com", "token", http_client=client)
    with pytest.raises(ValueError, match="before_post_id"):
        transport.get_posts_before("ch-1", "", 10)
    transport.close()
