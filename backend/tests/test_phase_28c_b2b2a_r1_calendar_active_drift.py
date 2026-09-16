"""PHASE 28C-B2-B2-A-R1 — Calendar active pagination across time drift."""

from datetime import UTC, datetime, timedelta

import pytest

from app.connectors.google.calendar_history_state import (
    CalendarHistoryActiveWindow,
    clear_active_window,
    complete_active_window,
    format_stored_datetime,
    plan_history_active_window,
    reconcile_active_window,
    sanitize_calendar_backfill,
    start_active_window,
)

T0 = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)


def _active_entry(
    history_days: int,
    token: str = "page-token",
    at: datetime = T0,
) -> dict:
    return {
        "active_start": format_stored_datetime(at - timedelta(days=history_days)),
        "active_end": format_stored_datetime(at),
        "active_history_days": history_days,
        "next_page_token": token,
    }


def test_time_drift_five_minutes_preserves_token(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _active_entry(60)
    monkeypatch.setattr(
        "app.connectors.google.calendar_history_state.utcnow",
        lambda: T0 + timedelta(minutes=5),
    )
    reconciled = reconcile_active_window(entry, history_days=60)
    assert reconciled.get("next_page_token") == "page-token"
    plan = plan_history_active_window(reconciled, history_days=60)
    assert plan.window is not None
    assert plan.window.next_page_token == "page-token"


def test_day_drift_preserves_token(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _active_entry(60)
    monkeypatch.setattr(
        "app.connectors.google.calendar_history_state.utcnow",
        lambda: T0 + timedelta(days=1),
    )
    reconciled = reconcile_active_window(entry, history_days=60)
    assert reconciled.get("next_page_token") == "page-token"
    plan = plan_history_active_window(reconciled, history_days=60)
    assert plan.window is not None
    assert plan.window.next_page_token == "page-token"


def test_policy_narrowing_clears_active_and_token() -> None:
    entry = _active_entry(90)
    reconciled = reconcile_active_window(entry, history_days=14)
    assert reconciled.get("next_page_token") is None
    assert reconciled.get("active_start") is None
    assert reconciled.get("active_history_days") is None


def test_deployment_narrowing_equivalent_clears_active() -> None:
    entry = _active_entry(90)
    reconciled = reconcile_active_window(entry, history_days=30)
    assert reconciled.get("next_page_token") is None
    assert reconciled.get("active_history_days") is None


def test_policy_increase_preserves_token() -> None:
    active_start = T0 - timedelta(days=30)
    active_end = T0 - timedelta(days=15)
    entry = {
        "active_start": format_stored_datetime(active_start),
        "active_end": format_stored_datetime(active_end),
        "active_history_days": 30,
        "next_page_token": "keep-token",
    }
    plan = plan_history_active_window(entry, history_days=90)
    assert plan.window is not None
    assert plan.window.next_page_token == "keep-token"


def test_missing_active_history_days_discards_active() -> None:
    entry = {
        "active_start": format_stored_datetime(T0 - timedelta(days=60)),
        "active_end": format_stored_datetime(T0),
        "next_page_token": "legacy-token",
    }
    reconciled = reconcile_active_window(entry, history_days=60)
    assert reconciled.get("next_page_token") is None
    assert reconciled.get("active_start") is None


def test_invalid_active_history_days_discarded_safely() -> None:
    entry = {
        "active_start": format_stored_datetime(T0 - timedelta(days=60)),
        "active_end": format_stored_datetime(T0),
        "active_history_days": "bad",
        "next_page_token": "legacy-token",
    }
    sanitized = sanitize_calendar_backfill(entry)
    assert sanitized.get("next_page_token") is None
    assert sanitized.get("active_start") is None


def test_completion_removes_active_history_days() -> None:
    entry = {
        "active_start": format_stored_datetime(T0 - timedelta(days=10)),
        "active_end": format_stored_datetime(T0),
        "active_history_days": 60,
    }
    completed = complete_active_window(entry)
    assert completed.get("active_history_days") is None
    assert completed.get("scanned_start") is not None


def test_abandon_preserves_scanned_interval() -> None:
    scanned_start = T0 - timedelta(days=30)
    scanned_end = T0 - timedelta(days=5)
    entry = {
        "scanned_start": format_stored_datetime(scanned_start),
        "scanned_end": format_stored_datetime(scanned_end),
        "active_start": format_stored_datetime(scanned_end),
        "active_end": format_stored_datetime(T0),
        "active_history_days": 60,
        "next_page_token": "drop-me",
    }
    abandoned = clear_active_window(entry)
    assert abandoned.get("next_page_token") is None
    assert abandoned.get("active_history_days") is None
    assert abandoned.get("scanned_start") == format_stored_datetime(scanned_start)
    assert abandoned.get("scanned_end") == format_stored_datetime(scanned_end)


def test_start_active_window_persists_history_days() -> None:
    window = CalendarHistoryActiveWindow(
        active_start=T0 - timedelta(days=60),
        active_end=T0,
        next_page_token=None,
    )
    started = start_active_window({}, window, history_days=60, page_size=100)
    assert started["active_history_days"] == 60
    assert started["active_page_size"] == 100
