import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.schemas import ObjectCreate
from app.connectors.google.calendar_sync import build_calendar_sync_service
from app.connectors.google.constants import CALENDAR_READONLY_SCOPE, GMAIL_READONLY_SCOPE
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.gmail_sync import build_gmail_sync_service
from app.connectors.google.gmail_transport import GmailTransport
from app.connectors.yandex.caldav_transport import CalDavCalendar, FakeCalDavTransport
from app.connectors.yandex.calendar_credentials import YandexCalendarAccountStore
from app.connectors.yandex.calendar_sync import build_yandex_calendar_sync_service
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.connectors.yandex.imap_transport import FakeImapTransport
from app.connectors.yandex.mail_sync import build_yandex_mail_sync_service
from app.db.engine import engine
from app.db.models import GoogleAccount, Job, Object, User, UserSourcePreference, YandexCalendarAccount, YandexMailAccount
from app.jobs.constants import (
    JOB_STATUS_PENDING,
    JOB_TYPE_EMBED_OBJECT,
    JOB_TYPE_SYNC_GOOGLE_CALENDAR,
    JOB_TYPE_SYNC_GOOGLE_GMAIL,
    JOB_TYPE_SYNC_YANDEX_CALENDAR,
    JOB_TYPE_SYNC_YANDEX_MAIL,
)
from app.jobs.handlers import HANDLERS
from app.jobs.worker import process_one_job
from app.llm.embedding_service import FakeEmbeddingService
from app.services.graph_service import GraphService
from app.services.job_queue_service import JobQueueService, utcnow
from app.services.recent_source_service import RecentSourceService
from app.services.search_service import SearchService
from app.services.source_sync_scheduler import SourceSyncScheduler
from app.services.today_service import TodayService
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_google_calendar import FakeHttpClient as CalendarFakeHttpClient
from tests.test_google_calendar import _calendar_handlers, _sample_calendar_event
from tests.test_google_oauth import FakeHttpClient, _sample_gmail_message
from tests.test_yandex_calendar import CALENDAR_HREF
from tests.test_yandex_calendar import _event as _yandex_caldav_event
from tests.test_yandex_mail import _build_raw_email


@pytest.fixture(autouse=True)
def cleanup_persisted_jobs() -> None:
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
    session.execute(delete(Job))
    session.execute(delete(UserSourcePreference))
    session.execute(delete(GoogleAccount))
    session.execute(delete(YandexMailAccount))
    session.execute(delete(YandexCalendarAccount))
    trans.commit()
    conn.close()
    yield


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


@pytest.fixture
def google_settings(monkeypatch: pytest.MonkeyPatch, oauth_client_file: str, credential_key: str) -> None:
    monkeypatch.setattr("app.core.config.settings.google_oauth_client_file", oauth_client_file)
    monkeypatch.setattr(
        "app.core.config.settings.google_redirect_uri",
        "http://localhost:18080/auth/google/callback",
    )
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


def _persist_gmail_schedule(
    credential_key: str,
    scopes: list[str],
) -> uuid.UUID:
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
    store = GoogleAccountStore(session, CredentialEncryption(credential_key))
    account = store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=scopes,
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    SourceSyncScheduler(session).run_maintenance()
    trans.commit()
    conn.close()
    return account.id


def _google_account(
    db_session,
    credential_key: str,
    scopes: list[str],
) -> GoogleAccount:
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=scopes,
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()
    return account


def test_recurring_job_ensure_single_row(db_session, credential_key, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account = _google_account(db_session, credential_key, [GMAIL_READONLY_SCOPE])
    scheduler = SourceSyncScheduler(db_session)
    scheduler.run_maintenance()
    scheduler.run_maintenance()
    db_session.commit()
    jobs = list(
        db_session.scalars(
            select(Job).where(
                Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
                Job.user_id == BOOTSTRAP_USER_ID,
            )
        )
    )
    assert len(jobs) == 1
    assert jobs[0].payload["account_id"] == str(account.id)


def test_recurring_success_reschedules_same_row(
    db_session, credential_key, google_settings, fake_embedding_service
) -> None:
    account_id = _persist_gmail_schedule(credential_key, [GMAIL_READONLY_SCOPE])
    job = db_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
            Job.payload["account_id"].as_string() == str(account_id),
        )
    )
    job_id = job.id

    with patch.dict(HANDLERS, {JOB_TYPE_SYNC_GOOGLE_GMAIL: lambda s, e, p, u: None}):
        assert process_one_job(fake_embedding_service)

    db_session.expire_all()
    job = db_session.get(Job, job_id)
    assert job.status == JOB_STATUS_PENDING
    assert job.attempts == 0
    assert job.last_error is None
    assert "last_success_at" in job.payload
    assert job.run_after > utcnow()


def test_missing_gmail_scope_does_not_schedule_gmail_job(
    db_session, credential_key, monkeypatch
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    _google_account(db_session, credential_key, [CALENDAR_READONLY_SCOPE])
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()
    count = db_session.scalar(
        select(func.count()).select_from(Job).where(Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL)
    )
    assert count == 0


def test_manual_sync_now_without_duplicate_row(
    db_session, credential_key, monkeypatch
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    _google_account(db_session, credential_key, [GMAIL_READONLY_SCOPE])
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()
    triggered = SourceSyncScheduler(db_session).trigger_all_for_user(BOOTSTRAP_USER_ID)
    db_session.commit()
    assert triggered
    jobs = list(
        db_session.scalars(select(Job).where(Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL))
    )
    assert len(jobs) == 1
    assert jobs[0].run_after <= utcnow() + timedelta(seconds=1)


def test_gmail_auto_sync_creates_searchable_email(
    db_session, credential_key, google_settings, oauth_client_file, fake_embedding_service
) -> None:
    marker = "VPN_AUTOSYNC_UNIQUE_MARKER"
    account_id = _persist_gmail_schedule(credential_key, [GMAIL_READONLY_SCOPE])

    message_id = "marker-msg-1"
    handlers = {
        ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): lambda params, headers: httpx.Response(
            200,
            json={"messages": [{"id": message_id}]},
        ),
        (
            "GET",
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
        ): lambda params, headers: httpx.Response(
            200,
            json=_sample_gmail_message(message_id, marker),
        ),
    }

    def fake_gmail_service(session):
        return build_gmail_sync_service(
            session=session,
            credential_key=credential_key,
            client_file=oauth_client_file,
            redirect_uri="http://localhost:18080/auth/google/callback",
            sync_days=30,
            default_limit=10,
            max_limit=10,
            http_client=FakeHttpClient(handlers),
        )

    sync_service = fake_gmail_service(db_session)
    sync_service.sync_account(account_id, user_id=BOOTSTRAP_USER_ID)
    db_session.commit()

    email = db_session.scalar(
        select(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == "gmail",
            Object.kind == "email",
            Object.external_id == message_id,
        )
    )
    assert email is not None
    embed_count = db_session.scalar(
        select(func.count()).select_from(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)
    )
    assert embed_count >= 1

    results = SearchService(db_session, BOOTSTRAP_USER_ID).search(marker, limit=10)
    assert any(hit.id == email.id for hit in results)

    sync_service.sync_account(account_id, user_id=BOOTSTRAP_USER_ID)
    db_session.commit()
    duplicate_count = db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == "gmail",
            Object.kind == "email",
            Object.external_id == message_id,
        )
    )
    assert duplicate_count == 1


def test_today_includes_proposed_task_due_today(db_session) -> None:
    from zoneinfo import ZoneInfo

    reference = datetime(2026, 8, 31, 15, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    day_start = datetime.combine(
        reference.date(), datetime.min.time(), tzinfo=ZoneInfo("Europe/Moscow")
    )
    due_today = day_start + timedelta(hours=10)

    GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="task",
            title="Proposed today",
            origin="agent",
            state="proposed",
            status="open",
            confidence=0.9,
            due_at=due_today,
        )
    )
    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(
        reference_at=reference,
        timezone="Europe/Moscow",
    )
    assert any(task.title == "Proposed today" for task in snapshot["tasks"])


def test_recent_source_objects_exclude_rejected(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    graph.create_object(
        ObjectCreate(
            kind="email",
            title="Visible email",
            origin="source",
            state="confirmed",
            provider="gmail",
            external_id=f"ext-{uuid.uuid4()}",
            occurred_at=utcnow(),
        )
    )
    graph.create_object(
        ObjectCreate(
            kind="email",
            title="Rejected email",
            origin="source",
            state="rejected",
            provider="gmail",
            external_id=f"ext-{uuid.uuid4()}",
            occurred_at=utcnow(),
        )
    )
    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()
    titles = {row.title for row in rows}
    assert "Visible email" in titles
    assert "Rejected email" not in titles


def test_sources_status_api(auth_client, db_session, credential_key, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    _google_account(db_session, credential_key, [GMAIL_READONLY_SCOPE])
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()

    response = auth_client.get("/sources/status")
    assert response.status_code == 200
    body = response.json()
    assert len(body["sources"]) == 1
    row = body["sources"][0]
    assert row["provider"] == "gmail"
    assert row["account_label"] == "user@example.com"
    assert "access_token" not in json.dumps(body)
    assert "refresh_token" not in json.dumps(body)


def test_cross_user_cannot_trigger_other_user_jobs(
    db_session, credential_key, issue_bearer, monkeypatch
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    other_user_id = uuid.uuid4()
    db_session.add(User(id=other_user_id, display_name="Other"))
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    store.upsert_tokens(
        user_id=other_user_id,
        email="other@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="other-access",
        refresh_token="other-refresh",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()

    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import app
    from tests.conftest import AuthTestClient

    other_bearer = issue_bearer(other_user_id)
    other_headers = {"Authorization": f"Bearer {other_bearer}"}

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as raw:
        client = AuthTestClient(raw, other_headers)
        triggered = client.post("/sources/sync").json()["triggered"]
    app.dependency_overrides.clear()

    assert any("gmail:" in item for item in triggered)
    bootstrap_jobs = list(
        db_session.scalars(
            select(Job).where(
                Job.user_id == BOOTSTRAP_USER_ID,
                Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
            )
        )
    )
    assert bootstrap_jobs == []


def test_google_calendar_auto_sync_creates_event(
    db_session, credential_key, google_settings, oauth_client_file
) -> None:
    marker = "VPN_AUTOSYNC_CAL_MARKER"
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[CALENDAR_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    event = _sample_calendar_event("evt-auto-1", marker)
    fake_http = CalendarFakeHttpClient(_calendar_handlers(events=[event]))
    sync_service = build_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        http_client=fake_http,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)
    db_session.commit()

    obj = db_session.scalar(
        select(Object).where(
            Object.provider == "google_calendar",
            Object.external_id == "primary:evt-auto-1",
        )
    )
    assert obj is not None
    assert marker in obj.title

    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)
    db_session.commit()
    count = db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.external_id == "primary:evt-auto-1",
        )
    )
    assert count == 1


def test_yandex_mail_auto_sync_creates_searchable_email(
    db_session, credential_key, fake_embedding_service, monkeypatch
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    marker = "VPN_AUTOSYNC_YANDEX_MARKER"
    store = YandexMailAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="user@yandex.ru",
        app_password="app-password",
        imap_host="imap.yandex.ru",
        imap_port=993,
    )
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()

    transport = FakeImapTransport(
        uidvalidity=10,
        messages={1: _build_raw_email(subject=marker, body=marker, message_id="<autosync@yandex.test>")},
    )
    sync_service = build_yandex_mail_sync_service(
        session=db_session,
        credential_key=credential_key,
        sync_days=30,
        default_limit=50,
        max_limit=100,
        transport_factory=lambda snapshot: transport,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=10)
    db_session.commit()

    email = db_session.scalar(
        select(Object).where(
            Object.provider == "yandex_mail",
            Object.kind == "email",
            Object.title == marker,
        )
    )
    assert email is not None
    results = SearchService(db_session, BOOTSTRAP_USER_ID).search(marker, limit=10)
    assert any(hit.id == email.id for hit in results)

    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=10)
    db_session.commit()
    duplicate_count = db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.provider == "yandex_mail",
            Object.title == marker,
        )
    )
    assert duplicate_count == 1


def test_yandex_calendar_auto_sync_creates_event(
    db_session, credential_key, monkeypatch
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    marker = "VPN_AUTOSYNC_YCAL_MARKER"
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="user@yandex.ru",
        app_password="app-password",
        caldav_host="caldav.yandex.ru",
    )
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()

    cal_event = _yandex_caldav_event("evt-yandex-auto", marker)
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="t1")],
        query_events_by_calendar={CALENDAR_HREF: [cal_event]},
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)
    db_session.commit()

    obj = db_session.scalar(
        select(Object).where(
            Object.provider == "yandex_calendar",
            Object.kind == "event",
            Object.title == marker,
        )
    )
    assert obj is not None

    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)
    db_session.commit()
    count = db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.provider == "yandex_calendar",
            Object.title == marker,
        )
    )
    assert count == 1


def test_broken_gmail_job_does_not_block_calendar_job(
    credential_key, monkeypatch, fake_embedding_service
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    _persist_gmail_schedule(credential_key, [GMAIL_READONLY_SCOPE, CALENDAR_READONLY_SCOPE])
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
    SourceSyncScheduler(session).trigger_all_for_user(BOOTSTRAP_USER_ID)
    trans.commit()
    conn.close()

    def failing_gmail(session, embedding, payload, user_id):
        raise RuntimeError("gmail broken")

    with patch.dict(HANDLERS, {JOB_TYPE_SYNC_GOOGLE_GMAIL: failing_gmail}):
        assert process_one_job(fake_embedding_service)

    conn = engine.connect()
    session = Session(bind=conn)
    gmail_job = session.scalar(select(Job).where(Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL))
    assert gmail_job.last_error is not None
    assert gmail_job.attempts >= 1
    calendar_job_id = session.scalar(
        select(Job.id).where(Job.type == JOB_TYPE_SYNC_GOOGLE_CALENDAR)
    )
    conn.close()

    with patch.dict(HANDLERS, {JOB_TYPE_SYNC_GOOGLE_CALENDAR: lambda s, e, p, u: None}):
        assert process_one_job(fake_embedding_service)

    conn = engine.connect()
    session = Session(bind=conn)
    calendar_job = session.get(Job, calendar_job_id)
    assert calendar_job.status == JOB_STATUS_PENDING
    conn.close()


def test_inbox_endpoint(auth_client, db_session, credential_key, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="email",
            title="Inbox feed email",
            origin="source",
            state="confirmed",
            provider="gmail",
            external_id=f"ext-{uuid.uuid4()}",
            occurred_at=utcnow(),
        )
    )
    _google_account(db_session, credential_key, [GMAIL_READONLY_SCOPE])
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()

    response = auth_client.get("/inbox")
    assert response.status_code == 200
    body = response.json()
    assert "unresolved_notifications" in body
    assert any(
        item["title"] == "Inbox feed email" for item in body["recent_source_objects"]
    )
    assert len(body["source_sync_status"]) >= 1


def test_recurring_interval_seconds_reads_settings(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.source_sync_gmail_interval_seconds", 90)
    monkeypatch.setattr("app.core.config.settings.source_sync_yandex_mail_interval_seconds", 91)
    monkeypatch.setattr("app.core.config.settings.source_sync_google_calendar_interval_seconds", 400)
    monkeypatch.setattr("app.core.config.settings.source_sync_yandex_calendar_interval_seconds", 401)
    queue = JobQueueService(db_session)
    assert queue.recurring_interval_seconds(JOB_TYPE_SYNC_GOOGLE_GMAIL) == 90
    assert queue.recurring_interval_seconds(JOB_TYPE_SYNC_YANDEX_MAIL) == 91
    assert queue.recurring_interval_seconds(JOB_TYPE_SYNC_GOOGLE_CALENDAR) == 400
    assert queue.recurring_interval_seconds(JOB_TYPE_SYNC_YANDEX_CALENDAR) == 401


def test_source_sync_interval_minimum_validation() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from app.core.config import Settings

    with pytest.raises(PydanticValidationError):
        Settings(source_sync_gmail_interval_seconds=30)


def test_recurring_success_uses_configured_gmail_interval(
    credential_key, monkeypatch, fake_embedding_service
) -> None:
    custom_interval = 180
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    monkeypatch.setattr("app.core.config.settings.source_sync_gmail_interval_seconds", custom_interval)
    _persist_gmail_schedule(credential_key, [GMAIL_READONLY_SCOPE])

    conn = engine.connect()
    session = Session(bind=conn)
    job = session.scalar(select(Job).where(Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL))
    job.run_after = utcnow() - timedelta(seconds=1)
    conn.commit()
    conn.close()

    with patch.dict(HANDLERS, {JOB_TYPE_SYNC_GOOGLE_GMAIL: lambda s, e, p, u: None}):
        assert process_one_job(fake_embedding_service)

    conn = engine.connect()
    session = Session(bind=conn)
    job = session.scalar(select(Job).where(Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL))
    delta_seconds = (job.run_after - utcnow()).total_seconds()
    assert 170 <= delta_seconds <= 190
    conn.close()


def _patch_today_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    reference: datetime,
) -> None:
    original_snapshot = TodayService.snapshot

    def patched_snapshot(self, reference_at=None, timezone=None):
        return original_snapshot(self, reference_at=reference, timezone=timezone)

    monkeypatch.setattr(TodayService, "snapshot", patched_snapshot)


def test_today_api_proposed_due_today_moscow(
    auth_client, db_session, monkeypatch
) -> None:
    from zoneinfo import ZoneInfo

    moscow = ZoneInfo("Europe/Moscow")
    reference = datetime(2026, 8, 31, 12, 0, tzinfo=moscow)
    _patch_today_snapshot(monkeypatch, reference)
    due_today = datetime(2026, 8, 31, 14, 0, tzinfo=moscow)

    GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="task",
            title="Proposed due today API",
            origin="agent",
            state="proposed",
            status="open",
            confidence=0.9,
            due_at=due_today,
        )
    )
    db_session.commit()

    response = auth_client.get(
        "/today",
        params={"client_timezone_id": "Europe/Moscow", "client_utc_offset_minutes": 180},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["timezone"] == "Europe/Moscow"
    assert payload["date"] == "2026-08-31"
    tasks = [t for t in payload["tasks"] if t["title"] == "Proposed due today API"]
    assert len(tasks) == 1
    assert tasks[0]["state"] == "proposed"
    assert tasks[0]["status"] == "open"


def test_today_api_proposed_overdue_moscow(auth_client, db_session, monkeypatch) -> None:
    from zoneinfo import ZoneInfo

    moscow = ZoneInfo("Europe/Moscow")
    reference = datetime(2026, 8, 31, 12, 0, tzinfo=moscow)
    _patch_today_snapshot(monkeypatch, reference)
    due_yesterday = datetime(2026, 8, 30, 22, 0, tzinfo=moscow)

    GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="task",
            title="Proposed overdue API",
            origin="agent",
            state="proposed",
            status="open",
            confidence=0.9,
            due_at=due_yesterday,
        )
    )
    db_session.commit()

    response = auth_client.get(
        "/today",
        params={"client_timezone_id": "Europe/Moscow", "client_utc_offset_minutes": 180},
    )
    tasks = [t for t in response.json()["tasks"] if t["title"] == "Proposed overdue API"]
    assert len(tasks) == 1
    assert tasks[0]["state"] == "proposed"


def test_today_api_proposed_future_excluded_moscow(
    auth_client, db_session, monkeypatch
) -> None:
    from zoneinfo import ZoneInfo

    moscow = ZoneInfo("Europe/Moscow")
    reference = datetime(2026, 8, 31, 12, 0, tzinfo=moscow)
    _patch_today_snapshot(monkeypatch, reference)
    due_tomorrow = datetime(2026, 9, 1, 10, 0, tzinfo=moscow)

    GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="task",
            title="Proposed future API",
            origin="agent",
            state="proposed",
            status="open",
            confidence=0.9,
            due_at=due_tomorrow,
        )
    )
    db_session.commit()

    response = auth_client.get(
        "/today",
        params={"client_timezone_id": "Europe/Moscow", "client_utc_offset_minutes": 180},
    )
    titles = {t["title"] for t in response.json()["tasks"]}
    assert "Proposed future API" not in titles


def test_today_excludes_deleted_proposed_task(db_session) -> None:
    from zoneinfo import ZoneInfo

    moscow = ZoneInfo("Europe/Moscow")
    reference = datetime(2026, 8, 31, 12, 0, tzinfo=moscow)
    due_today = datetime(2026, 8, 31, 14, 0, tzinfo=moscow)

    task = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="task",
            title="PHASE26B smoke revert fixture",
            origin="agent",
            state="proposed",
            status="deleted",
            confidence=0.9,
            due_at=due_today,
        )
    )
    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(
        reference_at=reference,
        timezone="Europe/Moscow",
    )
    assert all(obj.id != task.id for obj in snapshot["tasks"])


def test_inbox_recent_future_events_are_capped_by_created_at(db_session) -> None:
    from zoneinfo import ZoneInfo

    moscow = ZoneInfo("Europe/Moscow")
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    earlier = utcnow() - timedelta(days=2)
    later = utcnow() - timedelta(minutes=1)

    graph.create_object(
        ObjectCreate(
            kind="event",
            title="Future event A",
            origin="source",
            state="observed",
            provider="yandex_calendar",
            external_id=f"ycal-a-{uuid.uuid4()}",
            start_at=datetime(2026, 9, 1, 10, 0, tzinfo=moscow),
            due_at=datetime(2026, 9, 1, 11, 0, tzinfo=moscow),
            occurred_at=datetime(2026, 9, 1, 10, 0, tzinfo=moscow),
        )
    )
    event_a = db_session.scalar(
        select(Object).where(Object.title == "Future event A")
    )
    event_a.created_at = earlier
    event_a.updated_at = earlier
    graph.create_object(
        ObjectCreate(
            kind="event",
            title="Future event B",
            origin="source",
            state="observed",
            provider="yandex_calendar",
            external_id=f"ycal-b-{uuid.uuid4()}",
            start_at=datetime(2026, 9, 22, 10, 0, tzinfo=moscow),
            due_at=datetime(2026, 9, 22, 11, 0, tzinfo=moscow),
            occurred_at=datetime(2026, 9, 22, 10, 0, tzinfo=moscow),
        )
    )
    event_b = db_session.scalar(
        select(Object).where(Object.title == "Future event B")
    )
    event_b.created_at = earlier - timedelta(hours=1)
    event_b.updated_at = earlier - timedelta(hours=1)

    graph.create_object(
        ObjectCreate(
            kind="email",
            title="Fresh email C",
            origin="source",
            state="confirmed",
            provider="gmail",
            external_id=f"gmail-c-{uuid.uuid4()}",
            occurred_at=later,
        )
    )
    email_c = db_session.scalar(select(Object).where(Object.title == "Fresh email C"))
    email_c.created_at = later
    email_c.updated_at = later
    db_session.commit()

    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()
    titles = [row.title for row in rows]
    assert titles.index("Fresh email C") < titles.index("Future event B")
    assert titles.index("Future event B") < titles.index("Future event A")


def test_inbox_recent_materially_updated_event_does_not_promote_above_newer_created(
    db_session,
) -> None:
    from zoneinfo import ZoneInfo

    moscow = ZoneInfo("Europe/Moscow")
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    stale = utcnow() - timedelta(days=5)
    fresh = utcnow() - timedelta(minutes=2)

    graph.create_object(
        ObjectCreate(
            kind="event",
            title="Old event updated",
            origin="source",
            state="observed",
            provider="yandex_calendar",
            external_id=f"ycal-old-{uuid.uuid4()}",
            start_at=datetime(2026, 8, 1, 10, 0, tzinfo=moscow),
            due_at=datetime(2026, 8, 1, 11, 0, tzinfo=moscow),
            occurred_at=datetime(2026, 8, 1, 10, 0, tzinfo=moscow),
        )
    )
    old_event = db_session.scalar(select(Object).where(Object.title == "Old event updated"))
    old_event.created_at = stale
    old_event.updated_at = stale

    graph.create_object(
        ObjectCreate(
            kind="email",
            title="Stable email",
            origin="source",
            state="confirmed",
            provider="gmail",
            external_id=f"gmail-stable-{uuid.uuid4()}",
            occurred_at=fresh - timedelta(hours=1),
        )
    )
    stable_email = db_session.scalar(select(Object).where(Object.title == "Stable email"))
    stable_email.created_at = fresh - timedelta(hours=1)
    stable_email.updated_at = fresh - timedelta(hours=1)
    db_session.commit()

    old_event.title = "Old event updated (material)"
    old_event.updated_at = fresh
    db_session.commit()

    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()
    titles = [row.title for row in rows]
    assert titles.index("Stable email") < titles.index("Old event updated (material)")


def test_inbox_recent_unchanged_repeat_sync_does_not_reorder(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    base = utcnow() - timedelta(days=1)

    graph.create_object(
        ObjectCreate(
            kind="email",
            title="First ingested",
            origin="source",
            state="confirmed",
            provider="gmail",
            external_id=f"gmail-first-{uuid.uuid4()}",
            occurred_at=base,
        )
    )
    first = db_session.scalar(select(Object).where(Object.title == "First ingested"))
    first.created_at = base
    first.updated_at = base

    graph.create_object(
        ObjectCreate(
            kind="email",
            title="Second ingested",
            origin="source",
            state="confirmed",
            provider="yandex_mail",
            external_id=f"ymail-second-{uuid.uuid4()}",
            occurred_at=base + timedelta(minutes=30),
        )
    )
    second = db_session.scalar(select(Object).where(Object.title == "Second ingested"))
    second.created_at = base + timedelta(minutes=30)
    second.updated_at = base + timedelta(minutes=30)
    db_session.commit()

    before = [row.title for row in RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()]
    assert before.index("Second ingested") < before.index("First ingested")

    after = [row.title for row in RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()]
    assert after == before
    excerpt = RecentSourceService.excerpt("Строка 1\\nСтрока 2")
    assert excerpt == "Строка 1 Строка 2"
    assert "\\n" not in excerpt


def _create_recent_source(
    graph: GraphService,
    db_session: Session,
    *,
    kind: str,
    title: str,
    provider: str,
    updated_at: datetime,
    external_id: str | None = None,
) -> Object:
    graph.create_object(
        ObjectCreate(
            kind=kind,
            title=title,
            origin="source",
            state="observed",
            provider=provider,
            external_id=external_id or f"ext-{uuid.uuid4()}",
            occurred_at=updated_at,
        )
    )
    obj = db_session.scalar(select(Object).where(Object.title == title))
    obj.created_at = updated_at
    obj.updated_at = updated_at
    return obj


def test_recent_source_feed_balances_google_calendar_backfill(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    newest = utcnow()
    older = newest - timedelta(hours=2)

    for index in range(100):
        _create_recent_source(
            graph,
            db_session,
            kind="event",
            title=f"GC backfill {index}",
            provider="google_calendar",
            updated_at=newest - timedelta(seconds=index),
        )
    for index in range(5):
        _create_recent_source(
            graph,
            db_session,
            kind="email",
            title=f"Gmail feed {index}",
            provider="gmail",
            updated_at=older - timedelta(minutes=index),
        )
        _create_recent_source(
            graph,
            db_session,
            kind="email",
            title=f"Yandex mail feed {index}",
            provider="yandex_mail",
            updated_at=older - timedelta(minutes=index),
        )
        _create_recent_source(
            graph,
            db_session,
            kind="event",
            title=f"Yandex cal feed {index}",
            provider="yandex_calendar",
            updated_at=older - timedelta(minutes=index),
        )
    db_session.commit()

    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent(limit=30)
    providers = {row.provider for row in rows}
    assert providers == {"google_calendar"}
    assert all(row.title.startswith("GC backfill") for row in rows)


def test_recent_source_feed_single_provider_fills_limit(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    base = utcnow()
    for index in range(40):
        _create_recent_source(
            graph,
            db_session,
            kind="email",
            title=f"Gmail only {index}",
            provider="gmail",
            updated_at=base - timedelta(minutes=index),
        )
    db_session.commit()

    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent(limit=30)
    assert len(rows) == 30
    assert all(row.provider == "gmail" for row in rows)


def test_recent_source_feed_fresh_email_wins_after_calendar_backfill(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    newest = utcnow()
    older = newest - timedelta(hours=3)

    for index in range(50):
        _create_recent_source(
            graph,
            db_session,
            kind="event",
            title=f"GC dominance {index}",
            provider="google_calendar",
            updated_at=newest - timedelta(seconds=index),
        )
    for index in range(5):
        _create_recent_source(
            graph,
            db_session,
            kind="email",
            title=f"Older gmail {index}",
            provider="gmail",
            updated_at=older - timedelta(minutes=index),
        )
    _create_recent_source(
        graph,
        db_session,
        kind="email",
        title="Fresh arrival gmail",
        provider="gmail",
        updated_at=newest + timedelta(minutes=1),
    )
    db_session.commit()

    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent(limit=30)
    titles = [row.title for row in rows]
    assert titles[0] == "Fresh arrival gmail"


def test_google_calendar_resync_unchanged_preserves_updated_at(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[CALENDAR_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    fake_http = CalendarFakeHttpClient(
        _calendar_handlers(events=[_sample_calendar_event("evt-updated-at")])
    )
    sync_service = build_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        http_client=fake_http,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    obj = db_session.scalar(
        select(Object).where(
            Object.provider == "google_calendar",
            Object.external_id == "primary:evt-updated-at",
        )
    )
    updated_before = obj.updated_at
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    db_session.refresh(obj)
    assert obj.updated_at == updated_before


def test_recent_source_feed_cross_user_isolation(db_session) -> None:
    other_user_id = uuid.uuid4()
    db_session.add(User(id=other_user_id, display_name="Other"))
    db_session.flush()

    other_graph = GraphService(db_session, other_user_id)
    other_graph.create_object(
        ObjectCreate(
            kind="email",
            title="Other user secret email",
            origin="source",
            state="observed",
            provider="gmail",
            external_id=f"other-{uuid.uuid4()}",
            occurred_at=utcnow(),
        )
    )

    bootstrap_graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    _create_recent_source(
        bootstrap_graph,
        db_session,
        kind="email",
        title="Bootstrap visible email",
        provider="gmail",
        updated_at=utcnow() - timedelta(days=1),
    )
    db_session.commit()

    titles = {row.title for row in RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()}
    assert "Bootstrap visible email" in titles
    assert "Other user secret email" not in titles


def _create_gmail_with_labels(
    graph: GraphService,
    db_session: Session,
    title: str,
    labels: list[str],
    updated_at: datetime,
) -> Object:
    graph.create_object(
        ObjectCreate(
            kind="email",
            title=title,
            origin="source",
            state="observed",
            provider="gmail",
            external_id=f"ext-{uuid.uuid4()}",
            occurred_at=updated_at,
            metadata={"labels": labels},
        )
    )
    obj = db_session.scalar(select(Object).where(Object.title == title))
    obj.created_at = updated_at
    obj.updated_at = updated_at
    return obj


def test_gmail_list_query_excludes_spam_and_low_value_categories() -> None:
    from app.connectors.google.constants import build_gmail_list_query

    query = build_gmail_list_query("2026/08/01")
    assert "after:2026/08/01" in query
    assert "-in:spam" in query
    assert "-in:trash" in query
    assert "-category:promotions" in query
    assert "-category:social" in query
    assert "-category:forums" in query


def test_gmail_transport_list_message_ids_sets_includeSpamTrash_false() -> None:
    captured: dict[str, object] = {}

    def list_handler(params, headers):
        captured.update(params)
        return httpx.Response(200, json={"messages": []})

    transport = GmailTransport(
        http_client=FakeHttpClient(
            {
                (
                    "GET",
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                ): list_handler,
            }
        )
    )
    transport.list_message_ids("token", "me", "after:2026/01/01", 10)
    assert captured.get("includeSpamTrash") is False


def test_recent_source_feed_excludes_gmail_noise_labels(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    now = utcnow()

    visible_titles = {
        "Gmail primary mail",
        "Yandex normal mail",
        "Google cal event",
        "Yandex cal event",
    }
    _create_gmail_with_labels(
        graph,
        db_session,
        "Gmail primary mail",
        ["INBOX", "CATEGORY_PERSONAL"],
        now,
    )
    _create_gmail_with_labels(
        graph,
        db_session,
        "Gmail promotions mail",
        ["CATEGORY_PROMOTIONS"],
        now - timedelta(minutes=1),
    )
    _create_gmail_with_labels(
        graph,
        db_session,
        "Gmail social mail",
        ["CATEGORY_SOCIAL"],
        now - timedelta(minutes=2),
    )
    _create_gmail_with_labels(
        graph,
        db_session,
        "Gmail forums mail",
        ["CATEGORY_FORUMS"],
        now - timedelta(minutes=3),
    )
    _create_gmail_with_labels(
        graph,
        db_session,
        "Gmail spam mail",
        ["SPAM"],
        now - timedelta(minutes=4),
    )
    _create_gmail_with_labels(
        graph,
        db_session,
        "Gmail trash mail",
        ["TRASH"],
        now - timedelta(minutes=5),
    )
    _create_recent_source(
        graph,
        db_session,
        kind="email",
        title="Yandex normal mail",
        provider="yandex_mail",
        updated_at=now - timedelta(minutes=10),
    )
    _create_recent_source(
        graph,
        db_session,
        kind="event",
        title="Google cal event",
        provider="google_calendar",
        updated_at=now - timedelta(minutes=11),
    )
    _create_recent_source(
        graph,
        db_session,
        kind="event",
        title="Yandex cal event",
        provider="yandex_calendar",
        updated_at=now - timedelta(minutes=12),
    )
    db_session.commit()

    titles = {row.title for row in RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()}
    assert visible_titles <= titles
    assert "Gmail promotions mail" not in titles
    assert "Gmail social mail" not in titles
    assert "Gmail forums mail" not in titles
    assert "Gmail spam mail" not in titles
    assert "Gmail trash mail" not in titles


def test_gmail_noise_objects_do_not_consume_reserved_feed_slots(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    newest = utcnow()
    older = newest - timedelta(hours=2)

    for index in range(10):
        _create_gmail_with_labels(
            graph,
            db_session,
            f"Noise promo {index}",
            ["CATEGORY_PROMOTIONS"],
            newest - timedelta(seconds=index),
        )
    for index in range(3):
        _create_gmail_with_labels(
            graph,
            db_session,
            f"Primary gmail {index}",
            ["CATEGORY_PERSONAL"],
            older - timedelta(minutes=index),
        )
    for index in range(5):
        _create_recent_source(
            graph,
            db_session,
            kind="email",
            title=f"Yandex visible {index}",
            provider="yandex_mail",
            updated_at=older - timedelta(minutes=index),
        )
    db_session.commit()

    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent(limit=30)
    titles = {row.title for row in rows}
    assert not any(title.startswith("Noise promo") for title in titles)
    assert any(title.startswith("Primary gmail") for title in titles)
    assert any(title.startswith("Yandex visible") for title in titles)
    gmail_count = sum(1 for row in rows if row.provider == "gmail")
    yandex_count = sum(1 for row in rows if row.provider == "yandex_mail")
    assert gmail_count == 3
    assert yandex_count == 5


def test_recurring_success_uses_configured_yandex_calendar_interval(
    credential_key, monkeypatch, fake_embedding_service
) -> None:
    custom_interval = 75
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    monkeypatch.setattr(
        "app.core.config.settings.source_sync_yandex_calendar_interval_seconds",
        custom_interval,
    )
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
    store = YandexCalendarAccountStore(session, CredentialEncryption(credential_key))
    store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="user@yandex.ru",
        app_password="app-password",
        caldav_host="caldav.yandex.ru",
    )
    SourceSyncScheduler(session).run_maintenance()
    job = session.scalar(select(Job).where(Job.type == JOB_TYPE_SYNC_YANDEX_CALENDAR))
    assert job is not None
    job.run_after = utcnow() - timedelta(seconds=1)
    trans.commit()
    conn.close()

    with patch.dict(HANDLERS, {JOB_TYPE_SYNC_YANDEX_CALENDAR: lambda s, e, p, u: None}):
        assert process_one_job(fake_embedding_service)

    conn = engine.connect()
    session = Session(bind=conn)
    job = session.scalar(select(Job).where(Job.type == JOB_TYPE_SYNC_YANDEX_CALENDAR))
    delta_seconds = (job.run_after - utcnow()).total_seconds()
    conn.close()
    assert 65 <= delta_seconds <= 85


def test_yandex_calendar_scheduled_sync_event_appears_in_today_api(
    auth_client, db_session, credential_key, monkeypatch
) -> None:
    from zoneinfo import ZoneInfo

    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    moscow = ZoneInfo("Europe/Moscow")
    reference = datetime(2026, 8, 31, 12, 0, tzinfo=moscow)
    start_at = reference + timedelta(minutes=30)
    end_at = start_at + timedelta(minutes=30)
    marker = "YCAL_TODAY_SCHEDULED"

    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="user@yandex.ru",
        app_password="app-password",
        caldav_host="caldav.yandex.ru",
    )
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()

    from app.connectors.yandex.caldav_transport import CalDavEvent
    from tests.test_yandex_calendar import _sample_ical

    ical = _sample_ical(
        "evt-today-sched",
        marker,
        "Daily sync",
        start_at.strftime("%Y%m%dT%H%M%SZ"),
        end_at.strftime("%Y%m%dT%H%M%SZ"),
    )
    cal_event = CalDavEvent(
        event_href=f"{CALENDAR_HREF}evt-today-sched.ics",
        etag='"evt-today-sched"',
        calendar_data=ical,
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="t1")],
        query_events_by_calendar={CALENDAR_HREF: [cal_event]},
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)
    db_session.commit()

    _patch_today_snapshot(monkeypatch, reference)
    response = auth_client.get(
        "/today",
        params={"client_timezone_id": "Europe/Moscow", "client_utc_offset_minutes": 180},
    )
    events = [e for e in response.json()["calendar_events"] if e["title"] == marker]
    assert len(events) == 1

    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)
    db_session.commit()
    count = db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.provider == "yandex_calendar",
            Object.title == marker,
        )
    )
    assert count == 1


@pytest.fixture
def fake_embedding_service() -> FakeEmbeddingService:
    return FakeEmbeddingService()
