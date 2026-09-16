"""PHASE 28C-B2-B2-A — Google Calendar history pagination foundation."""

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
import pytest
from cryptography.fernet import Fernet

from app.connectors.google.calendar_history_state import (
    complete_active_window,
    desired_history_window,
    format_stored_datetime,
    get_history_backfill,
    plan_calendar_history,
    plan_history_active_window,
    reconcile_active_window,
    sanitize_calendar_backfill,
    set_calendar_backfill,
)
from app.connectors.google.calendar_transport import CalendarTransport
from app.connectors.google.constants import CALENDAR_API_BASE, CALENDAR_READONLY_SCOPE
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.db.models import GoogleAccount
from app.users.bootstrap import BOOTSTRAP_USER_ID

FIXED_NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def fixed_utcnow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.connectors.google.calendar_history_state.utcnow",
        lambda: FIXED_NOW,
    )


class FakeHttpClient:
    def __init__(self, handlers: dict) -> None:
        self._handlers = handlers
        self.calls: list[tuple] = []

    def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        **kwargs,
    ) -> httpx.Response:
        self.calls.append(("GET", url, params, headers))
        handler = self._handlers.get(("GET", url))
        if handler is None:
            raise AssertionError(f"unexpected GET {url}")
        return handler(params, headers)


def test_transport_first_page_parses_events_and_token() -> None:
    captured: dict[str, object] = {}

    def events_handler(params, headers):
        captured.update(params)
        return httpx.Response(
            200,
            json={
                "items": [{"id": "evt-1"}],
                "nextPageToken": "page-2",
            },
        )

    transport = CalendarTransport(
        http_client=FakeHttpClient(
            {
                (
                    "GET",
                    f"{CALENDAR_API_BASE}/calendars/primary/events",
                ): events_handler,
            }
        )
    )
    time_min = FIXED_NOW - timedelta(days=30)
    page = transport.list_events_page(
        "token",
        "primary",
        time_min,
        FIXED_NOW,
        100,
    )
    assert page.events == [{"id": "evt-1"}]
    assert page.next_page_token == "page-2"
    assert "pageToken" not in captured


def test_transport_continuation_sends_page_token_and_frozen_bounds() -> None:
    calls: list[dict] = []
    time_min = FIXED_NOW - timedelta(days=30)
    time_max = FIXED_NOW

    def events_handler(params, headers):
        calls.append(dict(params))
        if params.get("pageToken") == "page-2":
            return httpx.Response(200, json={"items": [{"id": "evt-2"}]})
        return httpx.Response(
            200,
            json={"items": [{"id": "evt-1"}], "nextPageToken": "page-2"},
        )

    transport = CalendarTransport(
        http_client=FakeHttpClient(
            {
                (
                    "GET",
                    f"{CALENDAR_API_BASE}/calendars/primary/events",
                ): events_handler,
            }
        )
    )
    page1 = transport.list_events_page(
        "token", "primary", time_min, time_max, 100
    )
    assert page1.next_page_token == "page-2"
    page2 = transport.list_events_page(
        "token", "primary", time_min, time_max, 100, page_token="page-2"
    )
    assert page2.events == [{"id": "evt-2"}]
    assert calls[1]["pageToken"] == "page-2"
    assert calls[0]["timeMin"] == calls[1]["timeMin"]
    assert calls[0]["timeMax"] == calls[1]["timeMax"]
    assert calls[0]["singleEvents"] == "true"
    assert calls[0]["orderBy"] == "startTime"


def test_calendar_state_independent_from_gmail_state(
    db_session,
    credential_key: str,
) -> None:
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[CALENDAR_READONLY_SCOPE],
        access_token="access",
        refresh_token="refresh",
        token_expiry=FIXED_NOW + timedelta(hours=1),
    )
    account.gmail_sync_state = {"history_backfill": {"version": 1, "token": "gmail"}}
    account.calendar_sync_state = {}
    db_session.flush()
    calendar_state = {
        "history_backfill": {
            "version": 1,
            "calendars": {"cal-a": {"scanned_start": "2026-01-01T00:00:00Z"}},
        }
    }
    store.update_calendar_sync_state(account.id, account.user_id, calendar_state)
    db_session.flush()
    refreshed = db_session.get(GoogleAccount, account.id)
    assert refreshed.gmail_sync_state["history_backfill"]["token"] == "gmail"
    assert get_history_backfill(refreshed.calendar_sync_state)["calendars"]["cal-a"]


def test_per_calendar_isolation() -> None:
    backfill = {
        "version": 1,
        "calendars": {
            "cal-a": {
                "active_start": format_stored_datetime(FIXED_NOW - timedelta(days=90)),
                "active_end": format_stored_datetime(FIXED_NOW),
                "active_history_days": 90,
                "next_page_token": "token-a",
            },
            "cal-b": {
                "scanned_start": format_stored_datetime(FIXED_NOW - timedelta(days=30)),
                "scanned_end": format_stored_datetime(FIXED_NOW),
            },
        },
    }
    updated = set_calendar_backfill(
        backfill,
        "cal-a",
        {"scanned_start": format_stored_datetime(FIXED_NOW - timedelta(days=60))},
    )
    assert updated["calendars"]["cal-b"]["scanned_start"] is not None
    assert "next_page_token" not in updated["calendars"]["cal-a"]


def test_initial_plan_full_desired_interval() -> None:
    plan = plan_history_active_window({}, history_days=60)
    assert plan.window is not None
    desired_start, desired_end = desired_history_window(60)
    assert plan.window.active_start == desired_start
    assert plan.window.active_end == desired_end


def test_increase_plans_only_older_missing_interval() -> None:
    scanned_start = FIXED_NOW - timedelta(days=30)
    entry = {
        "scanned_start": format_stored_datetime(scanned_start),
        "scanned_end": format_stored_datetime(FIXED_NOW),
    }
    plan = plan_history_active_window(entry, history_days=90)
    assert plan.window is not None
    assert plan.window.active_end == scanned_start
    assert plan.window.active_start == FIXED_NOW - timedelta(days=90)


def test_decrease_retains_broader_scanned_state() -> None:
    scanned_start = FIXED_NOW - timedelta(days=90)
    entry = {
        "scanned_start": format_stored_datetime(scanned_start),
        "scanned_end": format_stored_datetime(FIXED_NOW),
    }
    plan = plan_history_active_window(entry, history_days=14)
    assert plan.window is None
    assert plan.calendar_backfill["scanned_start"] == format_stored_datetime(scanned_start)


def test_forward_catch_up_plans_contiguous_extension() -> None:
    scanned_end = FIXED_NOW - timedelta(days=2)
    entry = {
        "scanned_start": format_stored_datetime(FIXED_NOW - timedelta(days=30)),
        "scanned_end": format_stored_datetime(scanned_end),
    }
    plan = plan_history_active_window(entry, history_days=30)
    assert plan.window is not None
    assert plan.window.active_start == scanned_end
    assert plan.window.active_end == FIXED_NOW


def test_active_narrowing_discards_out_of_policy_token() -> None:
    entry = {
        "active_start": format_stored_datetime(FIXED_NOW - timedelta(days=90)),
        "active_end": format_stored_datetime(FIXED_NOW),
        "active_history_days": 90,
        "next_page_token": "old-token",
    }
    reconciled = reconcile_active_window(entry, history_days=14)
    assert reconciled.get("next_page_token") is None
    plan = plan_history_active_window(entry, history_days=14)
    assert plan.window is None or plan.window.next_page_token is None


def test_deployment_narrowing_discards_token() -> None:
    entry = {
        "active_start": format_stored_datetime(FIXED_NOW - timedelta(days=90)),
        "active_end": format_stored_datetime(FIXED_NOW),
        "active_history_days": 90,
        "next_page_token": "old-token",
    }
    reconciled = reconcile_active_window(entry, history_days=30)
    assert reconciled.get("next_page_token") is None


def test_valid_increase_preserves_token() -> None:
    active_start = FIXED_NOW - timedelta(days=30)
    active_end = FIXED_NOW - timedelta(days=15)
    entry = {
        "active_start": format_stored_datetime(active_start),
        "active_end": format_stored_datetime(active_end),
        "active_history_days": 30,
        "next_page_token": "keep-token",
    }
    plan = plan_history_active_window(entry, history_days=90)
    assert plan.window is not None
    assert plan.window.next_page_token == "keep-token"


def test_malformed_partial_active_state_safely_replanned() -> None:
    entry = {"active_start": format_stored_datetime(FIXED_NOW - timedelta(days=10))}
    sanitized = sanitize_calendar_backfill(entry)
    assert sanitized.get("active_start") is None
    plan = plan_history_active_window(entry, history_days=60)
    assert plan.window is not None


def test_inverted_active_not_marked_scanned() -> None:
    entry = {
        "active_start": format_stored_datetime(FIXED_NOW),
        "active_end": format_stored_datetime(FIXED_NOW - timedelta(days=1)),
        "next_page_token": "bad",
    }
    completed = complete_active_window(entry)
    assert completed.get("scanned_start") is None
    assert completed.get("next_page_token") is None


def test_invalid_date_safe_recovery() -> None:
    entry = {
        "scanned_start": "not-a-date",
        "active_start": "also-bad",
        "next_page_token": "token",
    }
    sanitized = sanitize_calendar_backfill(entry)
    assert sanitized.get("scanned_start") is None
    assert sanitized.get("active_start") is None
    assert sanitized.get("next_page_token") is None
    plan = plan_history_active_window(entry, history_days=30)
    assert plan.window is not None


def test_final_page_merges_into_scanned_coverage() -> None:
    active_start = FIXED_NOW - timedelta(days=10)
    active_end = FIXED_NOW
    entry = {
        "active_start": format_stored_datetime(active_start),
        "active_end": format_stored_datetime(active_end),
        "active_history_days": 60,
    }
    completed = complete_active_window(entry)
    assert completed.get("active_start") is None
    assert completed.get("active_history_days") is None
    assert completed.get("scanned_start") == format_stored_datetime(active_start)
    assert completed.get("scanned_end") == format_stored_datetime(active_end)


def test_non_contiguous_completion_does_not_claim_gap() -> None:
    scanned_start = FIXED_NOW - timedelta(days=60)
    scanned_end = FIXED_NOW - timedelta(days=30)
    active_start = FIXED_NOW - timedelta(days=20)
    active_end = FIXED_NOW - timedelta(days=10)
    entry = {
        "scanned_start": format_stored_datetime(scanned_start),
        "scanned_end": format_stored_datetime(scanned_end),
        "active_start": format_stored_datetime(active_start),
        "active_end": format_stored_datetime(active_end),
    }
    completed = complete_active_window(entry)
    assert completed.get("scanned_start") == format_stored_datetime(scanned_start)
    assert completed.get("scanned_end") == format_stored_datetime(scanned_end)
    assert completed.get("active_start") is None


def test_plan_calendar_history_updates_state_without_gmail() -> None:
    state = {"marker": True}
    plan, updated = plan_calendar_history(state, "cal-x", history_days=60)
    assert plan.window is not None
    assert updated["marker"] is True
    backfill = get_history_backfill(updated)
    assert "calendars" in backfill
    assert "cal-x" in backfill["calendars"]


def test_list_events_wrapper_returns_first_page_events() -> None:
    transport = CalendarTransport(
        http_client=FakeHttpClient(
            {
                (
                    "GET",
                    f"{CALENDAR_API_BASE}/calendars/{quote('primary', safe='')}/events",
                ): lambda params, headers: httpx.Response(
                    200,
                    json={"items": [{"id": "evt-1"}], "nextPageToken": "more"},
                ),
            }
        )
    )
    events = transport.list_events(
        "token",
        "primary",
        FIXED_NOW - timedelta(days=1),
        FIXED_NOW,
        50,
    )
    assert events == [{"id": "evt-1"}]
