"""PHASE 28C-B2-C1-A — Yandex Mail bounded history foundation."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.connectors.yandex.errors import YandexImapError
from app.connectors.yandex.imap_transport import (
    FakeImapTransport,
    ImaplibTransport,
    history_uids_page_from_search,
    normalize_history_search_uids,
)
from app.connectors.yandex.mail_history_state import (
    MailHistoryActiveScan,
    clear_history_if_uidvalidity_changed,
    complete_active_window,
    continue_active_scan,
    desired_history_window,
    format_stored_date,
    get_history_backfill,
    persist_history_cursor,
    plan_history_active_scan,
    reconcile_active_scan,
    sanitize_history_backfill,
    set_history_backfill,
    start_active_window,
)

FIXED_TODAY = date(2026, 9, 2)
FIXED_NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_mail_utcnow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.connectors.yandex.mail_history_state.utcnow",
        lambda: FIXED_NOW,
    )


def test_history_first_page_returns_upper_bounded_uids() -> None:
    page = history_uids_page_from_search(
        b" ".join(str(uid).encode() for uid in range(1, 251)),
        before_uid=251,
        max_results=100,
    )
    assert page.uids == list(range(151, 251))
    assert page.next_before_uid == 151
    assert page.complete is False


def test_history_second_page_returns_lower_bounded_uids() -> None:
    page = history_uids_page_from_search(
        b" ".join(str(uid).encode() for uid in range(1, 151)),
        before_uid=151,
        max_results=100,
    )
    assert page.uids == list(range(51, 151))
    assert page.next_before_uid == 51
    assert page.complete is False


def test_history_final_page_complete() -> None:
    page = history_uids_page_from_search(
        b" ".join(str(uid).encode() for uid in range(1, 51)),
        before_uid=51,
        max_results=100,
    )
    assert page.uids == list(range(1, 51))
    assert page.next_before_uid is None
    assert page.complete is True


def test_imaplib_history_search_criteria_include_since_before_uid() -> None:
    captured: list[str] = []

    class HistorySearchImap:
        def select(self, folder: str, readonly: bool = True) -> tuple[str, list[bytes]]:
            return "OK", [b"42"]

        def response(self, code: str) -> tuple[str, list[bytes]]:
            if code == "UIDVALIDITY":
                return "UIDVALIDITY", [b"1"]
            return "NO", [b""]

        def uid(self, command: str, *args: object) -> tuple[str, list[bytes]]:
            if command == "search":
                captured.append(str(args[-1]))
                return "OK", [b"151 200 250"]
            raise AssertionError(f"unexpected uid command: {command}")

    transport = ImaplibTransport("imap.yandex.ru", 993, "user@yandex.ru", "pass")
    transport._imap = HistorySearchImap()
    transport._selected_folder = "INBOX"
    transport._uidvalidity = 1
    since = datetime(2026, 8, 1, tzinfo=UTC)
    before = datetime(2026, 9, 3, tzinfo=UTC)
    page = transport.search_uids_history_page("INBOX", since, before, 251, 100)
    assert page.uids == [151, 200, 250]
    criteria = captured[0]
    assert "SINCE" in criteria
    assert "BEFORE" in criteria
    assert "UID 1:250" in criteria


def test_history_page_excludes_uids_at_or_above_before_uid() -> None:
    uids = normalize_history_search_uids(b"100 150 200 251 300", before_uid=251)
    assert uids == [100, 150, 200]


def test_duplicate_and_malformed_uid_normalization() -> None:
    uids = normalize_history_search_uids(b"10 10 20 30", before_uid=100)
    assert uids == [10, 20, 30]
    with pytest.raises(YandexImapError, match="malformed imap uid search response"):
        normalize_history_search_uids(b"10 bad 20", before_uid=100)


def test_before_uid_one_returns_completed_empty_page() -> None:
    page = history_uids_page_from_search(b"1 2 3", before_uid=1, max_results=100)
    assert page.uids == []
    assert page.complete is True
    transport = FakeImapTransport(history_matching_uids=[1, 2, 3])
    fake_page = transport.search_uids_history_page(
        "INBOX",
        FIXED_NOW,
        FIXED_NOW + timedelta(days=1),
        before_uid=1,
        max_results=100,
    )
    assert fake_page.complete is True
    assert fake_page.uids == []
    assert transport.history_search_calls == []


def test_initial_planner_full_desired_interval() -> None:
    plan = plan_history_active_scan({}, history_days=30)
    assert plan.scan is not None
    desired_start, desired_end = desired_history_window(30)
    assert plan.scan.active_start_date == desired_start
    assert plan.scan.active_end_date == desired_end
    assert plan.scan.active_before_uid is None


def test_increase_plans_only_older_missing_interval() -> None:
    scanned_start = FIXED_TODAY - timedelta(days=30)
    backfill = {
        "scanned_start_date": format_stored_date(scanned_start),
        "scanned_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
    }
    plan = plan_history_active_scan(backfill, history_days=90)
    assert plan.scan is not None
    assert plan.scan.active_end_date == scanned_start
    assert plan.scan.active_start_date == FIXED_TODAY - timedelta(days=90)


def test_decrease_no_new_history_work() -> None:
    backfill = {
        "scanned_start_date": format_stored_date(FIXED_TODAY - timedelta(days=90)),
        "scanned_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
    }
    plan = plan_history_active_scan(backfill, history_days=14)
    assert plan.scan is None


def test_increase_again_reuses_broader_scanned_state() -> None:
    scanned_start = FIXED_TODAY - timedelta(days=90)
    backfill = {
        "scanned_start_date": format_stored_date(scanned_start),
        "scanned_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
    }
    plan = plan_history_active_scan(backfill, history_days=90)
    assert plan.scan is None


def test_time_drift_preserves_active_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    later = FIXED_NOW + timedelta(days=1)
    monkeypatch.setattr(
        "app.connectors.yandex.mail_history_state.utcnow",
        lambda: later,
    )
    backfill = {
        "active_start_date": format_stored_date(FIXED_TODAY - timedelta(days=30)),
        "active_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
        "active_history_days": 30,
        "active_before_uid": 500,
    }
    reconciled = reconcile_active_scan(backfill, history_days=30)
    assert continue_active_scan(reconciled) is not None
    assert reconciled.get("active_before_uid") == 500


def test_policy_narrowing_discards_active_preserves_scanned() -> None:
    scanned_start = FIXED_TODAY - timedelta(days=90)
    backfill = {
        "scanned_start_date": format_stored_date(scanned_start),
        "scanned_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
        "active_start_date": format_stored_date(FIXED_TODAY - timedelta(days=90)),
        "active_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
        "active_history_days": 90,
        "active_before_uid": 1000,
    }
    reconciled = reconcile_active_scan(backfill, history_days=14)
    assert reconciled.get("active_before_uid") is None
    assert reconciled.get("scanned_start_date") == format_stored_date(scanned_start)


def test_policy_increase_retains_active_cursor() -> None:
    backfill = {
        "active_start_date": format_stored_date(FIXED_TODAY - timedelta(days=30)),
        "active_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
        "active_history_days": 30,
        "active_before_uid": 250,
    }
    reconciled = reconcile_active_scan(backfill, history_days=90)
    assert reconciled.get("active_before_uid") == 250


def test_malformed_active_state_discarded_without_false_scanned() -> None:
    backfill = {"active_start_date": format_stored_date(FIXED_TODAY - timedelta(days=10))}
    sanitized = sanitize_history_backfill(backfill)
    assert sanitized.get("active_start_date") is None
    assert sanitized.get("scanned_start_date") is None


def test_contiguous_completion_merges_scanned_interval() -> None:
    scanned_start = FIXED_TODAY - timedelta(days=30)
    scanned_end = FIXED_TODAY + timedelta(days=1)
    active_start = FIXED_TODAY - timedelta(days=60)
    backfill = {
        "scanned_start_date": format_stored_date(scanned_start),
        "scanned_end_date": format_stored_date(scanned_end),
        "active_start_date": format_stored_date(active_start),
        "active_end_date": format_stored_date(scanned_start),
        "active_history_days": 30,
        "active_before_uid": 100,
    }
    completed = complete_active_window(backfill)
    assert completed.get("active_before_uid") is None
    assert completed.get("scanned_start_date") == format_stored_date(active_start)


def test_non_contiguous_completion_does_not_claim_gap() -> None:
    scanned_start = FIXED_TODAY - timedelta(days=60)
    scanned_end = FIXED_TODAY - timedelta(days=30)
    backfill = {
        "scanned_start_date": format_stored_date(scanned_start),
        "scanned_end_date": format_stored_date(scanned_end),
        "active_start_date": format_stored_date(FIXED_TODAY - timedelta(days=20)),
        "active_end_date": format_stored_date(FIXED_TODAY - timedelta(days=10)),
        "active_history_days": 30,
        "active_before_uid": 50,
    }
    completed = complete_active_window(backfill)
    assert completed.get("scanned_start_date") == format_stored_date(scanned_start)
    assert completed.get("scanned_end_date") == format_stored_date(scanned_end)
    assert completed.get("active_before_uid") is None


def test_root_state_preservation_when_updating_history() -> None:
    state = {
        "inbox_uidvalidity": 42,
        "inbox_last_uid": 999,
        "custom_marker": True,
    }
    backfill = {
        "version": 1,
        "scanned_start_date": format_stored_date(FIXED_TODAY - timedelta(days=7)),
        "scanned_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
    }
    updated = set_history_backfill(state, backfill)
    assert updated["inbox_uidvalidity"] == 42
    assert updated["inbox_last_uid"] == 999
    assert updated["custom_marker"] is True
    assert get_history_backfill(updated)["scanned_start_date"] is not None


def test_uidvalidity_reset_clears_history_only() -> None:
    state = {
        "inbox_uidvalidity": 10,
        "inbox_last_uid": 50,
        "history_backfill": {
            "version": 1,
            "inbox_uidvalidity": 10,
            "scanned_start_date": format_stored_date(FIXED_TODAY - timedelta(days=30)),
            "scanned_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
        },
    }
    cleared = clear_history_if_uidvalidity_changed(state, current_uidvalidity=11)
    assert cleared.get("history_backfill") is None
    assert cleared["inbox_uidvalidity"] == 10
    assert cleared["inbox_last_uid"] == 50


def test_start_and_persist_history_cursor_helpers() -> None:
    scan = MailHistoryActiveScan(
        active_start_date=FIXED_TODAY - timedelta(days=30),
        active_end_date=FIXED_TODAY + timedelta(days=1),
        active_before_uid=None,
    )
    started = start_active_window({}, scan, history_days=30, before_uid=251, inbox_uidvalidity=7)
    assert started["active_before_uid"] == 251
    assert started["inbox_uidvalidity"] == 7
    persisted = persist_history_cursor(started, 151)
    assert persisted["active_before_uid"] == 151


def test_fake_transport_history_page_integration() -> None:
    transport = FakeImapTransport(history_matching_uids=list(range(1, 251)))
    since = datetime(2026, 8, 1, tzinfo=UTC)
    before = datetime(2026, 9, 3, tzinfo=UTC)
    page1 = transport.search_uids_history_page("INBOX", since, before, 251, 100)
    assert page1.uids == list(range(151, 251))
    page2 = transport.search_uids_history_page("INBOX", since, before, 151, 100)
    assert page2.uids == list(range(51, 151))
