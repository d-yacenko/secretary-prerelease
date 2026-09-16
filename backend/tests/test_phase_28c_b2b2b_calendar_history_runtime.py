"""PHASE 28C-B2-B2-B — Google Calendar bounded history runtime."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.api.deps import get_db
from app.connectors.google.calendar_history_state import (
    format_stored_datetime,
    get_calendar_backfill,
    get_history_backfill,
    plan_history_active_window,
)
from app.connectors.google.calendar_normalize import normalize_calendar_event
from app.connectors.google.calendar_sync import build_calendar_sync_service
from app.connectors.google.constants import CALENDAR_API_BASE, CALENDAR_READONLY_SCOPE
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.core.config import settings
from app.db.engine import engine
from app.db.models import GoogleAccount, Job, Object, User, UserSourcePreference
from app.jobs.constants import JOB_TYPE_SYNC_GOOGLE_CALENDAR
from app.jobs.handlers import HANDLERS
from app.jobs.worker import process_one_job
from app.main import app
from app.services.source_sync_preference_service import SourceSyncPreferenceService
from app.source_sync.constants import SOURCE_GOOGLE_CALENDAR
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_phase_27a import _persist_gmail_schedule

FIXED_NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


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
        self.calls.append(("GET", url, dict(params or {}), headers))
        handler = self._handlers.get(("GET", url))
        if handler is None:
            raise AssertionError(f"unexpected GET {url} params={params}")
        return handler(params, headers)


def _sample_calendar_event(
    event_id: str,
    summary: str = "Team sync",
    description: str = "Discuss roadmap",
) -> dict:
    return {
        "id": event_id,
        "status": "confirmed",
        "summary": summary,
        "description": description,
        "start": {"dateTime": "2026-08-29T10:00:00+02:00"},
        "end": {"dateTime": "2026-08-29T11:00:00+02:00"},
        "location": "Room A",
        "htmlLink": "https://calendar.google.com/event?eid=" + event_id,
        "organizer": {"email": "owner@example.com"},
        "attendees": [{"email": "guest@example.com", "responseStatus": "accepted"}],
        "updated": "2026-08-28T08:00:00Z",
    }


def _events_url(calendar_id: str) -> str:
    return f"{CALENDAR_API_BASE}/calendars/{quote(calendar_id, safe='')}/events"


def _calendar_list_handler(calendars: list[dict]) -> dict:
    return {
        ("GET", f"{CALENDAR_API_BASE}/users/me/calendarList"): lambda params, headers: httpx.Response(
            200,
            json={"items": calendars},
        )
    }


def _live_events_handler(
    calendar_id: str,
    events: list[dict] | None = None,
) -> dict:
    events = events or []
    return {
        ("GET", _events_url(calendar_id)): lambda params, headers: httpx.Response(
            200,
            json={"items": events},
        )
    }


@pytest.fixture(autouse=True)
def cleanup_tables() -> None:
    conn = engine.connect()
    trans = conn.begin()
    session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    session.execute(delete(Job))
    session.execute(delete(Object))
    session.execute(delete(UserSourcePreference))
    session.execute(delete(GoogleAccount))
    trans.commit()
    conn.close()
    yield


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def oauth_client_file(tmp_path: Path) -> str:
    path = tmp_path / "google-oauth-client.json"
    path.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "test-client-id",
                    "client_secret": "test-client-secret",
                }
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture(autouse=True)
def fixed_calendar_utcnow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.connectors.google.calendar_sync.utcnow",
        lambda: FIXED_NOW,
    )
    monkeypatch.setattr(
        "app.connectors.google.calendar_history_state.utcnow",
        lambda: FIXED_NOW,
    )


def _upsert_calendar_account(
    db_session,
    credential_key: str,
    *,
    calendar_sync_state: dict | None = None,
    user_id: uuid.UUID = BOOTSTRAP_USER_ID,
) -> GoogleAccount:
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_tokens(
        user_id=user_id,
        email=f"user-{user_id}@example.com",
        scopes=[CALENDAR_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    if calendar_sync_state is not None:
        account.calendar_sync_state = calendar_sync_state
    db_session.flush()
    return account


def _build_service(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    fake_http: FakeHttpClient,
    days_back: int = 60,
) -> object:
    return build_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        days_back=days_back,
        days_forward=settings.calendar_sync_days_forward,
        default_limit=settings.calendar_sync_default_limit,
        max_limit=settings.calendar_sync_max_limit,
        max_calendars=settings.calendar_sync_max_calendars,
        http_client=fake_http,
    )


def test_effective_history_user_a_seven_user_b_default(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()
    account_a = _upsert_calendar_account(db_session, credential_key)
    account_b = _upsert_calendar_account(db_session, credential_key, user_id=user_b_id)
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_GOOGLE_CALENDAR,
        history_days=7,
        history_days_specified=True,
    )
    captured: list[dict] = []

    def events_handler(params, headers):
        captured.append(dict(params))
        return httpx.Response(200, json={"items": []})

    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {("GET", _events_url("primary")): events_handler}
    )
    service_a = _build_service(db_session, credential_key, oauth_client_file, fake_http, days_back=7)
    service_a.sync_account(account_a.id, BOOTSTRAP_USER_ID)
    expected_a_min = FIXED_NOW - timedelta(days=1)
    assert captured[0]["timeMin"].startswith(expected_a_min.strftime("%Y-%m-%d"))

    captured.clear()
    service_b = _build_service(
        db_session,
        credential_key,
        oauth_client_file,
        fake_http,
        days_back=settings.calendar_sync_days_back,
    )
    service_b.sync_account(account_b.id, user_b_id)
    expected_b_min = FIXED_NOW - timedelta(days=1)
    assert captured[0]["timeMin"].startswith(expected_b_min.strftime("%Y-%m-%d"))


def test_future_horizon_unchanged_when_history_days_changes(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)
    captured: list[dict] = []

    def events_handler(params, headers):
        captured.append(dict(params))
        return httpx.Response(200, json={"items": []})

    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {("GET", _events_url("primary")): events_handler}
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http, days_back=14)
    service.sync_account(account.id, BOOTSTRAP_USER_ID)
    expected_max = FIXED_NOW + timedelta(days=settings.calendar_sync_days_forward)
    assert captured[0]["timeMax"].startswith(expected_max.strftime("%Y-%m-%d"))


def test_direct_endpoint_live_only_no_history_page(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    monkeypatch.setattr(settings, "google_oauth_client_file", oauth_client_file)
    monkeypatch.setattr(settings, "google_redirect_uri", "http://localhost/callback")
    account = _upsert_calendar_account(db_session, credential_key)
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_GOOGLE_CALENDAR,
        history_days=7,
        history_days_specified=True,
    )
    history_calls = 0
    live_forward = FIXED_NOW + timedelta(days=settings.calendar_sync_days_forward)

    def events_handler(params, headers):
        nonlocal history_calls
        time_max = str(params.get("timeMax", ""))
        if not time_max.startswith(live_forward.strftime("%Y-%m-%d")):
            history_calls += 1
        return httpx.Response(200, json={"items": []})

    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {("GET", _events_url("primary")): events_handler}
    )

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(
        "app.api.google.build_calendar_sync_service",
        lambda **kwargs: _build_service(
            db_session,
            credential_key,
            oauth_client_file,
            fake_http,
            days_back=7,
        ),
    )
    with TestClient(app) as client:
        response = client.post(
            f"/connectors/google/calendar/sync?account_id={account.id}",
            headers=auth_headers,
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert history_calls == 0


def test_worker_live_pass_before_history_page(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)
    call_order: list[str] = []

    def events_handler(params, headers):
        if params.get("timeMax", "").startswith(
            (FIXED_NOW + timedelta(days=settings.calendar_sync_days_forward)).strftime("%Y-%m-%d")
        ):
            call_order.append("live")
        else:
            call_order.append("history")
        return httpx.Response(200, json={"items": []})

    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {("GET", _events_url("primary")): events_handler}
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert call_order[0] == "live"
    assert "history" in call_order


def test_one_history_page_per_recurring_run(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)
    history_calls = 0

    def events_handler(params, headers):
        nonlocal history_calls
        if not params.get("timeMax", "").startswith(
            (FIXED_NOW + timedelta(days=settings.calendar_sync_days_forward)).strftime("%Y-%m-%d")
        ):
            history_calls += 1
        return httpx.Response(200, json={"items": []})

    fake_http = FakeHttpClient(
        _calendar_list_handler(
            [
                {"id": "cal-a", "summary": "A"},
                {"id": "cal-b", "summary": "B"},
            ]
        )
        | {
            ("GET", _events_url("cal-a")): events_handler,
            ("GET", _events_url("cal-b")): events_handler,
        }
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert history_calls == 1


def test_initial_history_persists_active_before_provider_call(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)
    persisted_before_call = False

    def events_handler(params, headers):
        nonlocal persisted_before_call
        if not params.get("timeMax", "").startswith(
            (FIXED_NOW + timedelta(days=settings.calendar_sync_days_forward)).strftime("%Y-%m-%d")
        ):
            stored = db_session.get(GoogleAccount, account.id)
            entry = get_calendar_backfill(
                get_history_backfill(stored.calendar_sync_state),
                "primary",
            )
            persisted_before_call = (
                entry.get("active_start") is not None
                and entry.get("active_history_days") == 60
                and entry.get("active_page_size") == 100
            )
        return httpx.Response(200, json={"items": []})

    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {("GET", _events_url("primary")): events_handler}
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert persisted_before_call


def test_page_continuation_persists_token_b_after_full_processing(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(
        db_session,
        credential_key,
        calendar_sync_state={
            "history_backfill": {
                "version": 1,
                "calendars": {
                    "primary": {
                        "active_start": format_stored_datetime(FIXED_NOW - timedelta(days=60)),
                        "active_end": format_stored_datetime(FIXED_NOW),
                        "active_history_days": 60,
                        "active_page_size": 100,
                        "next_page_token": "token-a",
                    }
                },
            }
        },
    )

    def events_handler(params, headers):
        if params.get("pageToken") == "token-a":
            return httpx.Response(
                200,
                json={
                    "items": [_sample_calendar_event("evt-h1")],
                    "nextPageToken": "token-b",
                },
            )
        return httpx.Response(200, json={"items": []})

    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {("GET", _events_url("primary")): events_handler}
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(GoogleAccount, account.id)
    entry = get_calendar_backfill(
        get_history_backfill(stored.calendar_sync_state),
        "primary",
    )
    assert entry.get("next_page_token") == "token-b"


def test_final_page_completes_interval(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(
        db_session,
        credential_key,
        calendar_sync_state={
            "history_backfill": {
                "version": 1,
                "calendars": {
                    "primary": {
                        "active_start": format_stored_datetime(FIXED_NOW - timedelta(days=10)),
                        "active_end": format_stored_datetime(FIXED_NOW),
                        "active_history_days": 60,
                        "active_page_size": 100,
                    }
                },
            }
        },
    )
    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {
            ("GET", _events_url("primary")): lambda params, headers: httpx.Response(
                200,
                json={"items": [_sample_calendar_event("evt-final")]},
            )
        }
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(GoogleAccount, account.id)
    entry = get_calendar_backfill(
        get_history_backfill(stored.calendar_sync_state),
        "primary",
    )
    assert entry.get("active_start") is None
    assert entry.get("scanned_start") is not None
    assert entry.get("scanned_end") is not None


def test_crash_mid_page_keeps_token_a(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _upsert_calendar_account(
        db_session,
        credential_key,
        calendar_sync_state={
            "history_backfill": {
                "version": 1,
                "calendars": {
                    "primary": {
                        "active_start": format_stored_datetime(FIXED_NOW - timedelta(days=60)),
                        "active_end": format_stored_datetime(FIXED_NOW),
                        "active_history_days": 60,
                        "active_page_size": 100,
                        "next_page_token": "token-a",
                    }
                },
            }
        },
    )

    def events_handler(params, headers):
        if params.get("pageToken") == "token-a":
            return httpx.Response(
                200,
                json={
                    "items": [
                        _sample_calendar_event("evt-1"),
                        _sample_calendar_event("evt-2"),
                    ],
                    "nextPageToken": "token-b",
                },
            )
        return httpx.Response(200, json={"items": []})

    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {("GET", _events_url("primary")): events_handler}
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)

    original_materialize = service._materialize_calendar_events

    def crash_wrapper(**kwargs):
        raw_events = kwargs["raw_events"]
        if len(raw_events) > 1:
            original_materialize(
                raw_events=raw_events[:1],
                owner_user_id=kwargs["owner_user_id"],
                calendar_id=kwargs["calendar_id"],
                calendar_summary=kwargs["calendar_summary"],
                remaining=kwargs["remaining"],
            )
            raise RuntimeError("simulated crash")
        return original_materialize(**kwargs)

    monkeypatch.setattr(service, "_materialize_calendar_events", crash_wrapper)
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(GoogleAccount, account.id)
    entry = get_calendar_backfill(
        get_history_backfill(stored.calendar_sync_state),
        "primary",
    )
    assert entry.get("next_page_token") == "token-a"
    assert db_session.scalar(
        select(Object).where(Object.external_id == "primary:evt-1")
    ) is not None


def test_new_historical_event_created_once_with_embed(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)
    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {
            ("GET", _events_url("primary")): lambda params, headers: httpx.Response(
                200,
                json={
                    "items": [_sample_calendar_event("hist-new")],
                },
            )
        }
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    obj = db_session.scalar(
        select(Object).where(Object.external_id == "primary:hist-new")
    )
    assert obj is not None
    embed_jobs = list(
        db_session.scalars(
            select(Job).where(Job.type == "embed_object")
        )
    )
    assert len(embed_jobs) == 1


def test_unchanged_historical_event_no_duplicate_embed(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)
    normalized = normalize_calendar_event(
        _sample_calendar_event("hist-same"),
        calendar_id="primary",
        calendar_summary="Primary",
    )
    existing = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="event",
        provider="google_calendar",
        external_id="primary:hist-same",
        origin="source",
        state="observed",
        title=normalized["title"],
        body=normalized.get("body"),
        start_at=normalized.get("start_at"),
        due_at=normalized.get("due_at"),
        occurred_at=normalized.get("occurred_at"),
        metadata_=normalized["metadata"],
    )
    db_session.add(existing)
    db_session.flush()
    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {
            ("GET", _events_url("primary")): lambda params, headers: httpx.Response(
                200,
                json={"items": [_sample_calendar_event("hist-same")]},
            )
        }
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    before = db_session.scalar(select(func.count()).select_from(Job).where(Job.type == "embed_object"))
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    after = db_session.scalar(select(func.count()).select_from(Job).where(Job.type == "embed_object"))
    assert after == before


def test_changed_historical_event_updates_and_embeds_once(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)
    existing = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="event",
        provider="google_calendar",
        external_id="primary:hist-changed",
        origin="source",
        state="observed",
        title="Old title",
        body="Discuss roadmap",
        metadata_={"calendar_id": "primary", "event_id": "hist-changed"},
    )
    db_session.add(existing)
    db_session.flush()
    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {
            ("GET", _events_url("primary")): lambda params, headers: httpx.Response(
                200,
                json={"items": [_sample_calendar_event("hist-changed", summary="New title")]},
            )
        }
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    db_session.refresh(existing)
    assert existing.title == "New title"
    embed_jobs = list(db_session.scalars(select(Job).where(Job.type == "embed_object")))
    assert len(embed_jobs) == 1


def test_history_increase_plans_older_extension(
    db_session,
    credential_key: str,
) -> None:
    scanned_start = FIXED_NOW - timedelta(days=30)
    entry = {
        "scanned_start": format_stored_datetime(scanned_start),
        "scanned_end": format_stored_datetime(FIXED_NOW),
    }
    window = plan_history_active_window(entry, history_days=90).window
    assert window is not None
    assert window.active_end == scanned_start
    assert window.active_start == FIXED_NOW - timedelta(days=90)


def test_history_decrease_abandons_token_without_deleting_objects(
    db_session,
    credential_key: str,
) -> None:
    old_obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="event",
        provider="google_calendar",
        external_id="primary:old-event",
        origin="source",
        state="observed",
        title="old",
    )
    db_session.add(old_obj)
    db_session.flush()
    entry = {
        "active_start": format_stored_datetime(FIXED_NOW - timedelta(days=90)),
        "active_end": format_stored_datetime(FIXED_NOW),
        "active_history_days": 90,
        "active_page_size": 100,
        "next_page_token": "old-token",
        "scanned_start": format_stored_datetime(FIXED_NOW - timedelta(days=90)),
        "scanned_end": format_stored_datetime(FIXED_NOW),
    }
    from app.connectors.google.calendar_history_state import reconcile_active_window

    reconciled = reconcile_active_window(entry, history_days=14, max_limit=100, effective_limit=100)
    assert reconciled.get("next_page_token") is None
    assert db_session.get(Object, old_obj.id) is not None


def test_time_drift_preserves_active_token(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _upsert_calendar_account(
        db_session,
        credential_key,
        calendar_sync_state={
            "history_backfill": {
                "version": 1,
                "calendars": {
                    "primary": {
                        "active_start": format_stored_datetime(FIXED_NOW - timedelta(days=60)),
                        "active_end": format_stored_datetime(FIXED_NOW),
                        "active_history_days": 60,
                        "active_page_size": 100,
                        "next_page_token": "drift-token",
                    }
                },
            }
        },
    )
    later = FIXED_NOW + timedelta(days=1)
    monkeypatch.setattr(
        "app.connectors.google.calendar_sync.utcnow",
        lambda: later,
    )
    monkeypatch.setattr(
        "app.connectors.google.calendar_history_state.utcnow",
        lambda: later,
    )
    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {
            ("GET", _events_url("primary")): lambda params, headers: httpx.Response(
                200,
                json={"items": [], "nextPageToken": "drift-token"},
            )
        }
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(GoogleAccount, account.id)
    entry = get_calendar_backfill(
        get_history_backfill(stored.calendar_sync_state),
        "primary",
    )
    assert entry.get("next_page_token") == "drift-token"


def test_active_page_size_frozen_across_continuation(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(
        db_session,
        credential_key,
        calendar_sync_state={
            "history_backfill": {
                "version": 1,
                "calendars": {
                    "primary": {
                        "active_start": format_stored_datetime(FIXED_NOW - timedelta(days=60)),
                        "active_end": format_stored_datetime(FIXED_NOW),
                        "active_history_days": 60,
                        "active_page_size": 50,
                        "next_page_token": "token-a",
                    }
                },
            }
        },
    )
    seen_max: list[int] = []

    def events_handler(params, headers):
        if params.get("pageToken") == "token-a":
            seen_max.append(int(params["maxResults"]))
        return httpx.Response(200, json={"items": []})

    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {("GET", _events_url("primary")): events_handler}
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert seen_max == [50]


def test_page_size_decrease_abandons_old_token(
    db_session,
    credential_key: str,
) -> None:
    from app.connectors.google.calendar_history_state import reconcile_active_window

    entry = {
        "active_start": format_stored_datetime(FIXED_NOW - timedelta(days=60)),
        "active_end": format_stored_datetime(FIXED_NOW),
        "active_history_days": 60,
        "active_page_size": 100,
        "next_page_token": "old-token",
    }
    reconciled = reconcile_active_window(entry, history_days=60, max_limit=100, effective_limit=50)
    assert reconciled.get("next_page_token") is None
    assert reconciled.get("active_page_size") is None


def test_page_size_increase_continues_with_smaller_stored_size(
    db_session,
    credential_key: str,
) -> None:
    from app.connectors.google.calendar_history_state import reconcile_active_window

    entry = {
        "active_start": format_stored_datetime(FIXED_NOW - timedelta(days=60)),
        "active_end": format_stored_datetime(FIXED_NOW),
        "active_history_days": 60,
        "active_page_size": 50,
        "next_page_token": "keep-token",
    }
    reconciled = reconcile_active_window(entry, history_days=60, max_limit=100, effective_limit=100)
    assert reconciled.get("next_page_token") == "keep-token"
    assert reconciled.get("active_page_size") == 50


def _is_history_params(params: dict) -> bool:
    live_forward = FIXED_NOW + timedelta(days=settings.calendar_sync_days_forward)
    return not str(params.get("timeMax", "")).startswith(live_forward.strftime("%Y-%m-%d"))


def _multi_page_history_handler(
    cal_id: str,
    continuation_token: str,
    selected: list[str],
    page_tokens: list[str],
) -> object:
    def events_handler(params, headers):
        if not _is_history_params(params):
            return httpx.Response(200, json={"items": []})
        selected.append(cal_id)
        page_tokens.append(str(params.get("pageToken") or ""))
        return httpx.Response(
            200,
            json={"items": [], "nextPageToken": continuation_token},
        )

    return events_handler


def test_fairness_rotates_across_calendars_with_multi_page_backlog(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)
    selected: list[str] = []
    page_tokens: list[str] = []

    fake_http = FakeHttpClient(
        _calendar_list_handler(
            [
                {"id": "cal-a", "summary": "A"},
                {"id": "cal-b", "summary": "B"},
                {"id": "cal-c", "summary": "C"},
            ]
        )
        | {
            ("GET", _events_url("cal-a")): _multi_page_history_handler(
                "cal-a", "a2", selected, page_tokens
            ),
            ("GET", _events_url("cal-b")): _multi_page_history_handler(
                "cal-b", "b2", selected, page_tokens
            ),
            ("GET", _events_url("cal-c")): _multi_page_history_handler(
                "cal-c", "c2", selected, page_tokens
            ),
        }
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    for _ in range(3):
        service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert selected == ["cal-a", "cal-b", "cal-c"]
    assert page_tokens == ["", "", ""]

    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert selected[3] == "cal-a"
    assert page_tokens[3] == "a2"

    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert selected[4] == "cal-b"
    assert page_tokens[4] == "b2"

    stored = db_session.get(GoogleAccount, account.id)
    backfill = get_history_backfill(stored.calendar_sync_state)
    assert get_calendar_backfill(backfill, "cal-a").get("next_page_token") == "a2"
    assert get_calendar_backfill(backfill, "cal-b").get("next_page_token") == "b2"
    assert get_calendar_backfill(backfill, "cal-c").get("next_page_token") == "c2"


def test_single_calendar_multi_page_continues_on_successive_runs(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)
    selected: list[str] = []
    page_tokens: list[str] = []

    def events_handler(params, headers):
        if not _is_history_params(params):
            return httpx.Response(200, json={"items": []})
        selected.append("cal-a")
        page_tokens.append(str(params.get("pageToken") or ""))
        token = str(params.get("pageToken") or "")
        if token == "a2":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(200, json={"items": [], "nextPageToken": "a2"})

    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "cal-a", "summary": "A"}])
        | {("GET", _events_url("cal-a")): events_handler}
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert selected == ["cal-a", "cal-a"]
    assert page_tokens == ["", "a2"]
    stored = db_session.get(GoogleAccount, account.id)
    backfill = get_history_backfill(stored.calendar_sync_state)
    assert backfill.get("last_history_calendar_id") == "cal-a"


def test_non_final_page_advances_round_robin_cursor(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)
    fake_http = FakeHttpClient(
        _calendar_list_handler(
            [
                {"id": "cal-a", "summary": "A"},
                {"id": "cal-b", "summary": "B"},
            ]
        )
        | {
            ("GET", _events_url("cal-a")): lambda params, headers: httpx.Response(
                200,
                json={"items": [], "nextPageToken": "a2"},
            )
            if _is_history_params(params)
            else httpx.Response(200, json={"items": []}),
            ("GET", _events_url("cal-b")): lambda params, headers: httpx.Response(
                200,
                json={"items": []},
            ),
        }
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(GoogleAccount, account.id)
    backfill = get_history_backfill(stored.calendar_sync_state)
    assert backfill.get("last_history_calendar_id") == "cal-a"
    assert get_calendar_backfill(backfill, "cal-a").get("next_page_token") == "a2"


def test_final_page_advances_round_robin_cursor(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)
    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "cal-a", "summary": "A"}])
        | {
            ("GET", _events_url("cal-a")): lambda params, headers: httpx.Response(
                200,
                json={"items": []},
            ),
        }
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(GoogleAccount, account.id)
    backfill = get_history_backfill(stored.calendar_sync_state)
    assert backfill.get("last_history_calendar_id") == "cal-a"
    assert get_calendar_backfill(backfill, "cal-a").get("active_start") is None


def test_mid_page_crash_does_not_advance_round_robin_cursor(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)

    def events_handler(params, headers):
        if _is_history_params(params):
            return httpx.Response(
                200,
                json={
                    "items": [
                        _sample_calendar_event("evt-1"),
                        _sample_calendar_event("evt-2"),
                    ],
                    "nextPageToken": "token-b",
                },
            )
        return httpx.Response(200, json={"items": []})

    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "cal-a", "summary": "A"}])
        | {("GET", _events_url("cal-a")): events_handler}
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    original_materialize = service._materialize_calendar_events

    def crash_wrapper(**kwargs):
        raw_events = kwargs["raw_events"]
        if len(raw_events) > 1:
            original_materialize(
                raw_events=raw_events[:1],
                owner_user_id=kwargs["owner_user_id"],
                calendar_id=kwargs["calendar_id"],
                calendar_summary=kwargs["calendar_summary"],
                remaining=kwargs["remaining"],
            )
            raise RuntimeError("simulated crash")
        return original_materialize(**kwargs)

    monkeypatch.setattr(service, "_materialize_calendar_events", crash_wrapper)
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(GoogleAccount, account.id)
    backfill = get_history_backfill(stored.calendar_sync_state)
    assert backfill.get("last_history_calendar_id") is None
    entry = get_calendar_backfill(backfill, "cal-a")
    assert entry.get("next_page_token") is None


def test_crash_does_not_advance_round_robin_cursor(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)

    def events_handler(params, headers):
        if not params.get("timeMax", "").startswith(
            (FIXED_NOW + timedelta(days=settings.calendar_sync_days_forward)).strftime("%Y-%m-%d")
        ):
            raise RuntimeError("provider crash")
        return httpx.Response(200, json={"items": []})

    fake_http = FakeHttpClient(
        _calendar_list_handler(
            [
                {"id": "cal-a", "summary": "A"},
                {"id": "cal-b", "summary": "B"},
            ]
        )
        | {
            ("GET", _events_url("cal-a")): events_handler,
            ("GET", _events_url("cal-b")): events_handler,
        }
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    with pytest.raises(RuntimeError, match="provider crash"):
        service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(GoogleAccount, account.id)
    backfill = get_history_backfill(stored.calendar_sync_state)
    assert backfill.get("last_history_calendar_id") is None


def test_removed_calendar_state_retained_no_provider_call(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(
        db_session,
        credential_key,
        calendar_sync_state={
            "history_backfill": {
                "version": 1,
                "calendars": {
                    "removed-cal": {
                        "scanned_start": format_stored_datetime(FIXED_NOW - timedelta(days=30)),
                        "scanned_end": format_stored_datetime(FIXED_NOW),
                    }
                },
            }
        },
    )
    history_calls: list[str] = []

    def events_handler(params, headers, cal_id="primary"):
        if not params.get("timeMax", "").startswith(
            (FIXED_NOW + timedelta(days=settings.calendar_sync_days_forward)).strftime("%Y-%m-%d")
        ):
            history_calls.append(cal_id)
        return httpx.Response(200, json={"items": []})

    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | {
            ("GET", _events_url("primary")): lambda params, headers: events_handler(
                params, headers, "primary"
            ),
        }
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert history_calls == ["primary"]
    stored = db_session.get(GoogleAccount, account.id)
    backfill = get_history_backfill(stored.calendar_sync_state)
    assert "removed-cal" in backfill["calendars"]


def test_new_calendar_becomes_history_candidate(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    account = _upsert_calendar_account(db_session, credential_key)
    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "new-cal", "summary": "New"}])
        | {
            ("GET", _events_url("new-cal")): lambda params, headers: httpx.Response(
                200,
                json={"items": []},
            )
        }
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(GoogleAccount, account.id)
    entry = get_calendar_backfill(
        get_history_backfill(stored.calendar_sync_state),
        "new-cal",
    )
    assert entry.get("active_start") is not None or entry.get("scanned_start") is not None


def test_gmail_sync_state_unchanged_by_calendar_history(
    db_session,
    credential_key: str,
    oauth_client_file: str,
) -> None:
    gmail_state = {"history_backfill": {"version": 1, "token": "gmail-only"}}
    account = _upsert_calendar_account(db_session, credential_key)
    account.gmail_sync_state = gmail_state
    db_session.flush()
    fake_http = FakeHttpClient(
        _calendar_list_handler([{"id": "primary", "summary": "Primary"}])
        | _live_events_handler("primary")
    )
    service = _build_service(db_session, credential_key, oauth_client_file, fake_http)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(GoogleAccount, account.id)
    assert stored.gmail_sync_state == gmail_state


def test_disabled_calendar_worker_skips_provider_calls(
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_embedding_service,
) -> None:
    handler_calls = 0

    def fake_handler(session, embedding_service, payload, user_id) -> None:
        nonlocal handler_calls
        handler_calls += 1

    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account_id = _persist_gmail_schedule(credential_key, [CALENDAR_READONLY_SCOPE])
    conn = engine.connect()
    trans = conn.begin()
    persist_session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    SourceSyncPreferenceService.build(persist_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_GOOGLE_CALENDAR,
        enabled=False,
        enabled_specified=True,
    )
    trans.commit()
    conn.close()

    conn = engine.connect()
    trans = conn.begin()
    ready_session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    job = ready_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_GOOGLE_CALENDAR,
            Job.payload["account_id"].as_string() == str(account_id),
        )
    )
    job.run_after = utcnow() - timedelta(seconds=1)
    trans.commit()
    conn.close()

    with patch.dict(HANDLERS, {JOB_TYPE_SYNC_GOOGLE_CALENDAR: fake_handler}):
        assert process_one_job(fake_embedding_service)

    assert handler_calls == 0
