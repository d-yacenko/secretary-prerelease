"""PHASE 28C-B2-C2-B — Yandex Calendar history preference runtime."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.deps import get_db
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.yandex.caldav_transport import (
    CalDavCalendar,
    CalDavFetchResult,
    FakeCalDavTransport,
)
from app.connectors.yandex.calendar_credentials import YandexCalendarAccountStore
from app.connectors.yandex.calendar_history_state import format_stored_datetime
from app.connectors.yandex.calendar_normalize import build_external_id, normalize_caldav_event
from app.connectors.yandex.calendar_sync import build_yandex_calendar_sync_service
from app.connectors.yandex.constants import CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION
from app.core.config import settings
from app.db.engine import engine
from app.db.models import (
    GoogleAccount,
    Job,
    Object,
    User,
    UserSourcePreference,
    YandexCalendarAccount,
)
from app.jobs.constants import JOB_TYPE_SYNC_YANDEX_CALENDAR
from app.jobs.handlers import HANDLERS
from app.jobs.worker import process_one_job
from app.main import app
from app.services.source_sync_preference_service import SourceSyncPreferenceService
from app.services.source_sync_scheduler import SourceSyncScheduler
from app.source_sync.constants import SOURCE_YANDEX_CALENDAR
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_yandex_calendar import (
    CALENDAR_HREF,
    _event,
    _steady_sync_state,
)

CAL_B = "/calendars/user@yandex.ru/events-2/"
CAL_C = "/calendars/user@yandex.ru/events-3/"
CAL_REMOVED = "/calendars/user@yandex.ru/events-removed/"

FIXED_NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


@pytest.fixture(autouse=True)
def cleanup_tables() -> None:
    conn = engine.connect()
    trans = conn.begin()
    session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    session.execute(delete(Job))
    session.execute(delete(Object))
    session.execute(delete(UserSourcePreference))
    session.execute(delete(YandexCalendarAccount))
    session.execute(delete(GoogleAccount))
    trans.commit()
    conn.close()
    yield


@pytest.fixture(autouse=True)
def fixed_calendar_utcnow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.connectors.yandex.calendar_sync.utcnow", lambda: FIXED_NOW)
    monkeypatch.setattr(
        "app.connectors.yandex.calendar_history_state.utcnow",
        lambda: FIXED_NOW,
    )


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


def _upsert_account(db_session, credential_key: str, *, sync_state: dict | None = None) -> YandexCalendarAccount:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="user@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    if sync_state is not None:
        store.update_sync_state(account, sync_state)
    db_session.flush()
    return account


def _build_service(
    db_session,
    credential_key: str,
    transport: FakeCalDavTransport,
    days_back: int = 60,
) -> object:
    return build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=days_back,
        days_forward=settings.calendar_sync_days_forward,
        default_limit=settings.calendar_sync_default_limit,
        max_limit=settings.calendar_sync_max_limit,
        max_calendars=settings.calendar_sync_max_calendars,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: FIXED_NOW,
    )


def test_effective_history_user_a_seven_user_b_default(
    db_session,
    credential_key: str,
) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()
    account_a = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state({CALENDAR_HREF: {"sync_token": "t-a"}}),
    )
    account_b = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state({CALENDAR_HREF: {"sync_token": "t-a"}}),
    )
    store_b = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account_b = store_b.upsert_account(
        user_id=user_b_id,
        email="user-b@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    store_b.update_sync_state(
        account_b,
        _steady_sync_state({CALENDAR_HREF: {"sync_token": "t-b"}}),
    )
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_YANDEX_CALENDAR,
        history_days=7,
        history_days_specified=True,
    )
    transport_a = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="A", sync_token="a")],
        sync_batches_by_calendar={
            CALENDAR_HREF: {"t-a": CalDavFetchResult(events=[], sync_token="t-a")}
        },
    )
    service_a = _build_service(db_session, credential_key, transport_a, days_back=7)
    service_a.sync_account(account_a.id, BOOTSTRAP_USER_ID)
    assert transport_a.query_calls or transport_a.sync_collection_calls

    transport_b = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="B", sync_token="b")],
        sync_batches_by_calendar={
            CALENDAR_HREF: {"t-b": CalDavFetchResult(events=[], sync_token="t-b")}
        },
    )
    service_b = _build_service(
        db_session,
        credential_key,
        transport_b,
        days_back=settings.calendar_sync_days_back,
    )
    service_b.sync_account(account_b.id, user_b_id)


def test_days_forward_unchanged_by_history_preference(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "token",
                    "covered_window_end": (
                        FIXED_NOW + timedelta(days=settings.calendar_sync_days_forward)
                    ).isoformat(),
                }
            }
        ),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token")],
        sync_batches_by_calendar={
            CALENDAR_HREF: {"token": CalDavFetchResult(events=[], sync_token="token")}
        },
    )
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_YANDEX_CALENDAR,
        history_days=7,
        history_days_specified=True,
    )
    service = _build_service(db_session, credential_key, transport, days_back=7)
    service.sync_account(account.id, BOOTSTRAP_USER_ID)
    expected_forward = FIXED_NOW + timedelta(days=settings.calendar_sync_days_forward)
    assert expected_forward > FIXED_NOW - timedelta(days=7)


def test_direct_endpoint_live_only_no_history_query(
    db_session,
    credential_key: str,
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.conftest import AuthTestClient

    account = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "direct-token",
                    "covered_window_end": (FIXED_NOW + timedelta(days=90)).isoformat(),
                }
            }
        ),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token")],
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "direct-token": CalDavFetchResult(events=[], sync_token="direct-token")
            }
        },
    )
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_YANDEX_CALENDAR,
        history_days=14,
        history_days_specified=True,
    )

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with patch(
        "app.api.yandex.build_yandex_calendar_sync_service",
        lambda **kwargs: _build_service(db_session, credential_key, transport, days_back=14),
    ), TestClient(app) as test_client:
        client = AuthTestClient(test_client, auth_headers)
        response = client.post(f"/connectors/yandex/calendar/sync?account_id={account.id}")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert len(transport.query_calls) == 1


def test_worker_live_before_history_query(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "steady",
                    "covered_window_end": (FIXED_NOW + timedelta(days=90)).isoformat(),
                }
            }
        ),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="steady")],
        query_events_by_calendar={CALENDAR_HREF: [_event("hist-1")]},
        sync_batches_by_calendar={
            CALENDAR_HREF: {"steady": CalDavFetchResult(events=[], sync_token="steady")}
        },
    )
    call_order: list[str] = []
    original_sync = transport.sync_collection
    original_query = transport.query_events

    def track_sync(*args, **kwargs):
        call_order.append("sync_collection")
        return original_sync(*args, **kwargs)

    def track_query(*args, **kwargs):
        call_order.append("query_events")
        return original_query(*args, **kwargs)

    transport.sync_collection = track_sync
    transport.query_events = track_query
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert call_order == ["query_events", "sync_collection", "query_events"]


def test_legacy_missing_start_incremental_then_history(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "legacy-token",
                    "covered_window_end": (FIXED_NOW + timedelta(days=90)).isoformat(),
                }
            }
        ),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token")],
        query_events_by_calendar={CALENDAR_HREF: [_event("hist-legacy")]},
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "legacy-token": CalDavFetchResult(events=[], sync_token="legacy-token")
            }
        },
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    stored = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    state = stored.sync_state["calendars"][CALENDAR_HREF]
    assert state.get("covered_window_start") is None
    assert transport.sync_collection_calls
    assert CALENDAR_HREF in transport.query_calls


def test_initial_history_state_persisted_before_provider_query(
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "token",
                    "covered_window_end": (FIXED_NOW + timedelta(days=90)).isoformat(),
                }
            }
        ),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token")],
        query_events_by_calendar={CALENDAR_HREF: []},
        sync_batches_by_calendar={
            CALENDAR_HREF: {"token": CalDavFetchResult(events=[], sync_token="token")}
        },
    )
    service = _build_service(db_session, credential_key, transport)
    captured: list[dict] = []
    original_persist = service._persist_calendar_state

    def capture_persist(account_id, user_id, sync_state_root, calendar_state):
        for entry in calendar_state.values():
            if entry.get("history_backfill_start"):
                captured.append(dict(entry))
        original_persist(account_id, user_id, sync_state_root, calendar_state)

    monkeypatch.setattr(service, "_persist_calendar_state", capture_persist)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert captured
    assert captured[0].get("history_backfill_start") is not None
    assert captured[0].get("history_backfill_days") == 60


def test_one_history_parent_slice_step_per_run(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(db_session, credential_key)
    many_events = [_event(f"hist-{i}") for i in range(20)]
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="t")],
        query_events_by_calendar={CALENDAR_HREF: many_events},
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True, limit=5)
    history_queries = [c for c in transport.query_calls if c == CALENDAR_HREF]
    assert len(history_queries) >= 1


def test_non_final_history_step_persists_cursor(
    db_session,
    credential_key: str,
) -> None:
    window_min = FIXED_NOW - timedelta(days=60)
    events = [
        _event(
            f"hist-{i}",
            dtstart=(window_min + timedelta(days=i)).strftime("%Y%m%dT%H%M%SZ"),
            dtend=(window_min + timedelta(days=i, hours=1)).strftime("%Y%m%dT%H%M%SZ"),
        )
        for i in range(10)
    ]
    account = _upsert_account(db_session, credential_key)
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="t")],
        query_events_by_calendar={CALENDAR_HREF: events},
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True, limit=1)
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    state = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID).sync_state["calendars"][CALENDAR_HREF]
    assert state.get("history_backfill_cursor") is not None


def test_final_history_step_establishes_covered_window_start(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(db_session, credential_key)
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="t")],
        query_events_by_calendar={CALENDAR_HREF: [_event("only-one")]},
    )
    service = _build_service(db_session, credential_key, transport, days_back=7)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True, limit=100)
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    state = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID).sync_state["calendars"][CALENDAR_HREF]
    assert state.get("covered_window_start") is not None
    assert state.get("history_backfill_start") is None


def test_exact_contiguous_extension_moves_covered_start(
    db_session,
    credential_key: str,
) -> None:
    covered_start = FIXED_NOW - timedelta(days=30)
    active_end = covered_start
    active_start = covered_start - timedelta(days=1)
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "token",
                    "covered_window_start": format_stored_datetime(covered_start),
                    "covered_window_end": (FIXED_NOW + timedelta(days=90)).isoformat(),
                    "history_backfill_start": format_stored_datetime(active_start),
                    "history_backfill_end": format_stored_datetime(active_end),
                    "history_backfill_days": 90,
                }
            }
        ),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token")],
        query_events_by_calendar={
            CALENDAR_HREF: [_event("old-1", dtstart="20260601T100000Z", dtend="20260601T110000Z")]
        },
        sync_batches_by_calendar={
            CALENDAR_HREF: {"token": CalDavFetchResult(events=[], sync_token="token")}
        },
    )
    service = _build_service(db_session, credential_key, transport, days_back=90)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    state = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID).sync_state["calendars"][CALENDAR_HREF]
    assert state["covered_window_start"] == format_stored_datetime(active_start)


def test_gap_completion_does_not_claim_coverage(
    db_session,
    credential_key: str,
) -> None:
    covered_start = datetime(2026, 8, 1, tzinfo=UTC)
    covered_end = datetime(2026, 9, 1, tzinfo=UTC)
    active_start = datetime(2026, 6, 1, tzinfo=UTC)
    active_end = datetime(2026, 7, 1, tzinfo=UTC)
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "token",
                    "covered_window_start": format_stored_datetime(covered_start),
                    "covered_window_end": format_stored_datetime(covered_end),
                    "history_backfill_start": format_stored_datetime(active_start),
                    "history_backfill_end": format_stored_datetime(active_end),
                    "history_backfill_days": 90,
                }
            }
        ),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token")],
        query_events_by_calendar={CALENDAR_HREF: [_event("gap-1")]},
        sync_batches_by_calendar={
            CALENDAR_HREF: {"token": CalDavFetchResult(events=[], sync_token="token")}
        },
    )
    service = _build_service(db_session, credential_key, transport, days_back=90)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    state = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID).sync_state["calendars"][CALENDAR_HREF]
    assert state["covered_window_start"] == format_stored_datetime(covered_start)


def test_history_increase_plans_missing_older_only(
    db_session,
    credential_key: str,
) -> None:
    covered_start = FIXED_NOW - timedelta(days=30)
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "token",
                    "covered_window_start": format_stored_datetime(covered_start),
                    "covered_window_end": (FIXED_NOW + timedelta(days=90)).isoformat(),
                }
            }
        ),
    )
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_YANDEX_CALENDAR,
        history_days=90,
        history_days_specified=True,
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token")],
        query_events_by_calendar={CALENDAR_HREF: [_event("older-1")]},
        sync_batches_by_calendar={
            CALENDAR_HREF: {"token": CalDavFetchResult(events=[], sync_token="token")}
        },
    )
    service = _build_service(db_session, credential_key, transport, days_back=90)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    state = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID).sync_state["calendars"][CALENDAR_HREF]
    assert state["sync_token"] == "token"
    assert state["covered_window_start"] == format_stored_datetime(covered_start)


def test_history_decrease_abandons_active_before_provider(
    db_session,
    credential_key: str,
) -> None:
    old_obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="event",
        provider="yandex_calendar",
        external_id=build_external_id(CALENDAR_HREF, "old-event"),
        origin="source",
        state="observed",
        title="old",
    )
    db_session.add(old_obj)
    db_session.flush()
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "token",
                    "covered_window_start": format_stored_datetime(FIXED_NOW - timedelta(days=90)),
                    "covered_window_end": (FIXED_NOW + timedelta(days=90)).isoformat(),
                    "history_backfill_start": format_stored_datetime(FIXED_NOW - timedelta(days=90)),
                    "history_backfill_end": format_stored_datetime(FIXED_NOW),
                    "history_backfill_days": 90,
                    "history_backfill_cursor": format_stored_datetime(FIXED_NOW - timedelta(days=45)),
                }
            }
        ),
    )
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_YANDEX_CALENDAR,
        history_days=14,
        history_days_specified=True,
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token")],
        query_events_by_calendar={CALENDAR_HREF: [_event("should-not-run")]},
        sync_batches_by_calendar={
            CALENDAR_HREF: {"token": CalDavFetchResult(events=[], sync_token="token")}
        },
    )
    service = _build_service(db_session, credential_key, transport, days_back=14)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert transport.query_calls == [CALENDAR_HREF]
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    state = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID).sync_state["calendars"][CALENDAR_HREF]
    assert state.get("history_backfill_cursor") is None
    assert db_session.get(Object, old_obj.id) is not None


def test_time_drift_preserves_frozen_history_range(
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen_start = FIXED_NOW - timedelta(days=60)
    frozen_end = FIXED_NOW
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "token",
                    "history_backfill_start": format_stored_datetime(frozen_start),
                    "history_backfill_end": format_stored_datetime(frozen_end),
                    "history_backfill_days": 60,
                    "history_backfill_cursor": format_stored_datetime(
                        frozen_start + timedelta(days=10)
                    ),
                }
            }
        ),
    )
    later = FIXED_NOW + timedelta(days=1)
    monkeypatch.setattr("app.connectors.yandex.calendar_sync.utcnow", lambda: later)
    monkeypatch.setattr("app.connectors.yandex.calendar_history_state.utcnow", lambda: later)
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token")],
        query_events_by_calendar={CALENDAR_HREF: [_event("drift-1")]},
        sync_batches_by_calendar={
            CALENDAR_HREF: {"token": CalDavFetchResult(events=[], sync_token="token")}
        },
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    state = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID).sync_state["calendars"][CALENDAR_HREF]
    assert state["history_backfill_start"] == format_stored_datetime(frozen_start)
    assert state["history_backfill_end"] == format_stored_datetime(frozen_end)


def test_history_query_does_not_modify_sync_token(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(db_session, credential_key)
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="steady")],
        query_events_by_calendar={CALENDAR_HREF: [_event("hist-token")]},
        sync_tokens_by_calendar={CALENDAR_HREF: "new-from-query"},
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    state = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID).sync_state["calendars"][CALENDAR_HREF]
    assert state.get("sync_token") is None or state.get("sync_token") != "new-from-query"


def test_history_event_created_once_with_embed(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(db_session, credential_key)
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="t")],
        query_events_by_calendar={CALENDAR_HREF: [_event("embed-once")]},
    )
    service = _build_service(db_session, credential_key, transport, days_back=7)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    obj = db_session.scalar(
        select(Object).where(
            Object.external_id == build_external_id(CALENDAR_HREF, "embed-once")
        )
    )
    assert obj is not None
    embed_jobs = list(db_session.scalars(select(Job).where(Job.type == "embed_object")))
    assert len(embed_jobs) == 1


def test_unchanged_history_event_no_duplicate_embed(
    db_session,
    credential_key: str,
) -> None:
    normalized = normalize_caldav_event(
        _event("unchanged-hist").calendar_data,
        calendar_href=CALENDAR_HREF,
        calendar_summary="Work",
        etag='"unchanged-hist"',
        event_href=f"{CALENDAR_HREF}unchanged-hist.ics",
    )
    existing = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind=normalized["kind"],
        provider=normalized["provider"],
        external_id=normalized["external_id"],
        origin=normalized["origin"],
        state=normalized["state"],
        title=normalized["title"],
        body=normalized.get("body"),
        start_at=normalized.get("start_at"),
        due_at=normalized.get("due_at"),
        metadata_=normalized["metadata"],
    )
    db_session.add(existing)
    db_session.flush()
    account = _upsert_account(db_session, credential_key)
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="t")],
        query_events_by_calendar={CALENDAR_HREF: [_event("unchanged-hist")]},
    )
    service = _build_service(db_session, credential_key, transport, days_back=7)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    embed_jobs = list(db_session.scalars(select(Job).where(Job.type == "embed_object")))
    assert len(embed_jobs) == 0


def test_crash_before_materialization_keeps_history_cursor(
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen_start = FIXED_NOW - timedelta(days=30)
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "token",
                    "history_backfill_start": format_stored_datetime(frozen_start),
                    "history_backfill_end": format_stored_datetime(FIXED_NOW),
                    "history_backfill_days": 30,
                    "history_backfill_cursor": format_stored_datetime(
                        frozen_start + timedelta(days=5)
                    ),
                }
            }
        ),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token")],
        query_events_by_calendar={CALENDAR_HREF: [_event("crash-1"), _event("crash-2")]},
        sync_batches_by_calendar={
            CALENDAR_HREF: {"token": CalDavFetchResult(events=[], sync_token="token")}
        },
    )
    service = _build_service(db_session, credential_key, transport)

    def crash_apply(**kwargs):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(service, "_apply_fetch_batch", crash_apply)
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    state = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID).sync_state["calendars"][CALENDAR_HREF]
    assert state["history_backfill_cursor"] == format_stored_datetime(
        frozen_start + timedelta(days=5)
    )


def test_multi_calendar_fairness_rotation(
    db_session,
    credential_key: str,
) -> None:
    covered = format_stored_datetime(FIXED_NOW - timedelta(days=30))
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={
            "normalization_version": CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION,
            "calendars": {
                CALENDAR_HREF: {
                    "sync_token": "a",
                    "covered_window_start": covered,
                    "covered_window_end": (FIXED_NOW + timedelta(days=90)).isoformat(),
                },
                CAL_B: {
                    "sync_token": "b",
                    "covered_window_start": covered,
                    "covered_window_end": (FIXED_NOW + timedelta(days=90)).isoformat(),
                },
                CAL_C: {
                    "sync_token": "c",
                    "covered_window_start": covered,
                    "covered_window_end": (FIXED_NOW + timedelta(days=90)).isoformat(),
                },
            },
            "last_history_calendar_href": CALENDAR_HREF,
        },
    )
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_YANDEX_CALENDAR,
        history_days=90,
        history_days_specified=True,
    )
    transport = FakeCalDavTransport(
        calendars=[
            CalDavCalendar(href=CALENDAR_HREF, display_name="A", sync_token="a"),
            CalDavCalendar(href=CAL_B, display_name="B", sync_token="b"),
            CalDavCalendar(href=CAL_C, display_name="C", sync_token="c"),
        ],
        calendar_order=[CALENDAR_HREF, CAL_B, CAL_C],
        query_events_by_calendar={
            CALENDAR_HREF: [_event("a-1")],
            CAL_B: [_event("b-1")],
            CAL_C: [_event("c-1")],
        },
        sync_batches_by_calendar={
            CALENDAR_HREF: {"a": CalDavFetchResult(events=[], sync_token="a")},
            CAL_B: {"b": CalDavFetchResult(events=[], sync_token="b")},
            CAL_C: {"c": CalDavFetchResult(events=[], sync_token="c")},
        },
    )
    service = _build_service(db_session, credential_key, transport, days_back=90)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    root = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID).sync_state
    assert root.get("last_history_calendar_href") == CAL_B


def test_removed_calendar_state_retained(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state(
            {
                CAL_REMOVED: {"sync_token": "removed-token"},
                CALENDAR_HREF: {"sync_token": "active-token"},
            }
        ),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Active", sync_token="active-token")],
        query_events_by_calendar={CALENDAR_HREF: [_event("active-1")]},
        sync_batches_by_calendar={
            CALENDAR_HREF: {"active-token": CalDavFetchResult(events=[], sync_token="active-token")}
        },
    )
    service = _build_service(db_session, credential_key, transport, days_back=7)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    calendars = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID).sync_state["calendars"]
    assert calendars[CAL_REMOVED]["sync_token"] == "removed-token"
    assert CAL_REMOVED not in transport.query_calls


def test_stale_sync_token_clears_coverage_before_recovery(
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state=_steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "stale-token",
                    "covered_window_start": format_stored_datetime(FIXED_NOW - timedelta(days=30)),
                    "covered_window_end": "2026-12-31T00:00:00+00:00",
                    "history_backfill_start": format_stored_datetime(FIXED_NOW - timedelta(days=60)),
                    "history_backfill_end": format_stored_datetime(FIXED_NOW),
                    "history_backfill_days": 60,
                }
            }
        ),
    )
    cleared_before_recovery = False
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="fresh")],
        query_events_by_calendar={CALENDAR_HREF: [_event("recover-1")]},
        sync_tokens_by_calendar={CALENDAR_HREF: "fresh"},
        stale_sync_tokens={"stale-token"},
    )
    service = _build_service(db_session, credential_key, transport)

    original_persist = service._persist_calendar_state

    def check_persist(account_id, user_id, sync_state_root, calendar_state):
        nonlocal cleared_before_recovery
        entry = calendar_state.get(CALENDAR_HREF, {})
        if entry.get("backfill_cursor") and not entry.get("covered_window_end"):
            cleared_before_recovery = True
        original_persist(account_id, user_id, sync_state_root, calendar_state)

    monkeypatch.setattr(service, "_persist_calendar_state", check_persist)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert cleared_before_recovery
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    state = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID).sync_state["calendars"][CALENDAR_HREF]
    assert state.get("sync_token") == "fresh"
    assert state.get("history_backfill_start") is None


def test_disabled_yandex_calendar_worker_skips_caldav(
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_embedding_service,
) -> None:
    handler_calls = 0

    def fake_handler(session, embedding_service, payload, user_id) -> None:
        nonlocal handler_calls
        handler_calls += 1

    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    conn = engine.connect()
    trans = conn.begin()
    persist_session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    store = YandexCalendarAccountStore(persist_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="user@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    SourceSyncScheduler(persist_session).run_maintenance()
    SourceSyncPreferenceService.build(persist_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_YANDEX_CALENDAR,
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
            Job.type == JOB_TYPE_SYNC_YANDEX_CALENDAR,
            Job.payload["account_id"].as_string() == str(account.id),
        )
    )
    job.run_after = utcnow() - timedelta(seconds=1)
    trans.commit()
    conn.close()

    with patch.dict(HANDLERS, {JOB_TYPE_SYNC_YANDEX_CALENDAR: fake_handler}):
        assert process_one_job(fake_embedding_service)

    assert handler_calls == 0
