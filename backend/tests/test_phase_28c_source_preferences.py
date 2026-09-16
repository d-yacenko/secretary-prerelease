"""PHASE 28C-A — per-user source enablement and sync cadence."""

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.connectors.google.constants import GMAIL_READONLY_SCOPE
from app.core.config import settings
from app.db.engine import engine
from app.db.models import Job, User, UserSourcePreference
from app.jobs.constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_SYNC_GOOGLE_GMAIL,
    JOB_TYPE_SYNC_YANDEX_CALENDAR,
    JOB_TYPE_SYNC_YANDEX_MAIL,
)
from app.jobs.handlers import HANDLERS
from app.jobs.recurring_job_finalization import (
    finalize_recurring_job_failure,
    finalize_recurring_job_success,
)
from app.jobs.worker import process_one_job
from app.services.job_queue_service import JobQueueService, utcnow
from app.services.source_status_service import SourceStatusService
from app.services.source_sync_preference_service import SourceSyncPreferenceService
from app.services.source_sync_scheduler import SourceSyncScheduler
from app.source_sync.constants import SOURCE_GMAIL
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient
from tests.test_phase_27a import _google_account, _persist_gmail_schedule


@pytest.fixture(autouse=True)
def cleanup_user_source_preferences() -> None:
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
    session.execute(delete(Job))
    session.execute(delete(UserSourcePreference))
    trans.commit()
    conn.close()
    yield


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


def _gmail_account_id(db_session, credential_key: str, monkeypatch) -> uuid.UUID:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account = _google_account(db_session, credential_key, [GMAIL_READONLY_SCOPE])
    return account.id


def test_defaults_all_sources_enabled_with_deployment_cadence(
    auth_client: AuthTestClient,
) -> None:
    response = auth_client.get("/me/source-preferences")
    assert response.status_code == 200
    body = response.json()
    assert len(body["preferences"]) == 6
    gmail = next(item for item in body["preferences"] if item["source"] == SOURCE_GMAIL)
    assert gmail["enabled"] is True
    assert gmail["sync_interval_seconds"] == settings.source_sync_gmail_interval_seconds
    assert (
        gmail["default_sync_interval_seconds"]
        == settings.source_sync_gmail_interval_seconds
    )
    assert gmail["min_sync_interval_seconds"] == settings.source_sync_user_min_interval_seconds
    assert gmail["max_sync_interval_seconds"] == settings.source_sync_user_max_interval_seconds


@pytest.mark.parametrize(
    "job_type",
    [JOB_TYPE_SYNC_YANDEX_MAIL, JOB_TYPE_SYNC_YANDEX_CALENDAR],
)
def test_yandex_recurring_failure_persists_and_clears_typed_metadata(
    db_session, job_type: str,
) -> None:
    queue = JobQueueService(db_session)
    job = queue.enqueue(
        job_type,
        {
            "account_id": str(uuid.uuid4()),
            "last_success_at": "2026-09-16T10:00:00+00:00",
        },
        BOOTSTRAP_USER_ID,
    )
    job.status = JOB_STATUS_RUNNING
    job.attempts = 1
    queue.mark_recurring_failure(
        job.id,
        "temporary provider failure",
        failure_kind="transient",
        retryable=True,
    )
    assert job.status == JOB_STATUS_FAILED
    assert job.payload["last_success_at"] == "2026-09-16T10:00:00+00:00"
    assert job.payload["last_error_kind"] == "transient"
    assert job.payload["last_error_retryable"] is True

    job.run_after = utcnow() - timedelta(seconds=1)
    assert queue.rearm_failed_recurring_job(job, cooldown_seconds=3600) is True
    assert job.status == JOB_STATUS_PENDING
    assert job.last_error is None
    assert "last_error_kind" not in job.payload
    assert "last_error_retryable" not in job.payload


def test_legacy_source_failure_status_fails_closed_to_unknown() -> None:
    job = Job(
        user_id=BOOTSTRAP_USER_ID,
        type=JOB_TYPE_SYNC_YANDEX_MAIL,
        payload={"account_id": str(uuid.uuid4())},
        status=JOB_STATUS_FAILED,
        attempts=1,
        last_error="invalid password",
    )
    assert SourceStatusService._failure_metadata(job) == ("unknown", False)


def test_patch_isolation_between_users(
    auth_client: AuthTestClient,
    db_session,
    issue_bearer,
) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()
    user_b_client = AuthTestClient(
        auth_client._client,
        {"Authorization": f"Bearer {issue_bearer(user_b_id)}"},
    )

    patch_a = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"enabled": False, "sync_interval_seconds": 900},
    )
    assert patch_a.status_code == 200

    get_b = user_b_client.get("/me/source-preferences")
    gmail_b = next(
        item for item in get_b.json()["preferences"] if item["source"] == SOURCE_GMAIL
    )
    assert gmail_b["enabled"] is True
    assert gmail_b["sync_interval_seconds"] == settings.source_sync_gmail_interval_seconds


def test_bounds_min_max_accepted(auth_client: AuthTestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.source_sync_user_min_interval_seconds", 60)
    monkeypatch.setattr("app.core.config.settings.source_sync_user_max_interval_seconds", 86400)
    min_resp = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"sync_interval_seconds": 60},
    )
    max_resp = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"sync_interval_seconds": 86400},
    )
    assert min_resp.status_code == 200
    assert max_resp.status_code == 200


def test_bounds_below_min_rejected(auth_client: AuthTestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.source_sync_user_min_interval_seconds", 60)
    response = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"sync_interval_seconds": 30},
    )
    assert response.status_code == 422


def test_bounds_above_max_rejected(auth_client: AuthTestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.source_sync_user_max_interval_seconds", 86400)
    response = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"sync_interval_seconds": 90000},
    )
    assert response.status_code == 422


def test_scheduler_disabled_does_not_create_gmail_job(
    db_session, credential_key, monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account_id = _gmail_account_id(db_session, credential_key, monkeypatch)
    service = SourceSyncPreferenceService.build(db_session)
    service.update_preference(
        BOOTSTRAP_USER_ID, SOURCE_GMAIL, enabled=False, enabled_specified=True
    )
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()
    job = JobQueueService(db_session).find_recurring_source_job(
        BOOTSTRAP_USER_ID,
        JOB_TYPE_SYNC_GOOGLE_GMAIL,
        account_id,
    )
    assert job is None


def test_existing_pending_job_retired_when_disabled(
    db_session, credential_key, monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account_id = _gmail_account_id(db_session, credential_key, monkeypatch)
    SourceSyncScheduler(db_session).run_maintenance()
    service = SourceSyncPreferenceService.build(db_session)
    service.update_preference(
        BOOTSTRAP_USER_ID, SOURCE_GMAIL, enabled=False, enabled_specified=True
    )
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()
    job = db_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
            Job.payload["account_id"].as_string() == str(account_id),
        )
    )
    assert job is not None
    assert job.status == JOB_STATUS_DONE


def test_manual_aggregate_sync_skips_disabled_gmail(
    db_session, credential_key, monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    _gmail_account_id(db_session, credential_key, monkeypatch)
    SourceSyncScheduler(db_session).run_maintenance()
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID, SOURCE_GMAIL, enabled=False, enabled_specified=True
    )
    triggered = SourceSyncScheduler(db_session).trigger_all_for_user(BOOTSTRAP_USER_ID)
    assert not any(item.startswith("gmail:") for item in triggered)


def test_running_success_finalize_does_not_rearm_when_disabled(
    db_session, credential_key, monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account_id = _persist_gmail_schedule(credential_key, [GMAIL_READONLY_SCOPE])
    job = db_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
            Job.payload["account_id"].as_string() == str(account_id),
        )
    )
    job.status = JOB_STATUS_RUNNING
    job.locked_at = utcnow()
    db_session.flush()
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID, SOURCE_GMAIL, enabled=False, enabled_specified=True
    )
    finalize_recurring_job_success(
        db_session,
        job.id,
        BOOTSTRAP_USER_ID,
        JOB_TYPE_SYNC_GOOGLE_GMAIL,
    )
    db_session.expire_all()
    updated = db_session.get(Job, job.id)
    assert updated.status == JOB_STATUS_DONE


def test_running_failure_finalize_does_not_retry_when_disabled(
    db_session, credential_key, monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account_id = _persist_gmail_schedule(credential_key, [GMAIL_READONLY_SCOPE])
    job = db_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
            Job.payload["account_id"].as_string() == str(account_id),
        )
    )
    job.status = JOB_STATUS_RUNNING
    job.locked_at = utcnow()
    db_session.flush()
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID, SOURCE_GMAIL, enabled=False, enabled_specified=True
    )
    finalize_recurring_job_failure(
        db_session,
        job.id,
        BOOTSTRAP_USER_ID,
        JOB_TYPE_SYNC_GOOGLE_GMAIL,
        "temporary failure",
        retryable=True,
    )
    db_session.expire_all()
    updated = db_session.get(Job, job.id)
    assert updated.status == JOB_STATUS_DONE
    assert updated.last_error is None


def test_user_interval_used_after_success(
    db_session, credential_key, monkeypatch, fake_embedding_service,
) -> None:
    custom_interval = 900
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    monkeypatch.setattr("app.core.config.settings.source_sync_gmail_interval_seconds", 120)
    account_id = _persist_gmail_schedule(credential_key, [GMAIL_READONLY_SCOPE])
    conn = engine.connect()
    trans = conn.begin()
    persist_session = Session(bind=conn)
    SourceSyncPreferenceService.build(persist_session).update_preference(
        BOOTSTRAP_USER_ID, SOURCE_GMAIL, sync_interval_seconds=custom_interval,
        sync_interval_specified=True,
    )
    trans.commit()
    conn.close()
    conn = engine.connect()
    trans = conn.begin()
    ready_session = Session(bind=conn)
    ready_job = ready_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
            Job.payload["account_id"].as_string() == str(account_id),
        )
    )
    ready_job.run_after = utcnow() - timedelta(seconds=1)
    trans.commit()
    conn.close()
    job = db_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
            Job.payload["account_id"].as_string() == str(account_id),
        )
    )
    before = utcnow()
    with patch.dict(HANDLERS, {JOB_TYPE_SYNC_GOOGLE_GMAIL: lambda s, e, p, u: None}):
        assert process_one_job(fake_embedding_service)
    db_session.expire_all()
    job = db_session.get(Job, job.id)
    assert job.status == JOB_STATUS_PENDING
    assert job.run_after >= before + timedelta(seconds=custom_interval - 2)


def test_reenable_restores_single_recurring_job(
    db_session, credential_key, monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account_id = _gmail_account_id(db_session, credential_key, monkeypatch)
    service = SourceSyncPreferenceService.build(db_session)
    SourceSyncScheduler(db_session).run_maintenance()
    service.update_preference(
        BOOTSTRAP_USER_ID, SOURCE_GMAIL, enabled=False, enabled_specified=True
    )
    SourceSyncScheduler(db_session).run_maintenance()
    service.update_preference(
        BOOTSTRAP_USER_ID, SOURCE_GMAIL, enabled=True, enabled_specified=True
    )
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()
    jobs = list(
        db_session.scalars(
            select(Job).where(
                Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
                Job.user_id == BOOTSTRAP_USER_ID,
            )
        )
    )
    active = [job for job in jobs if job.status != JOB_STATUS_DONE]
    assert len(active) == 1
    assert active[0].payload["account_id"] == str(account_id)
    assert active[0].status == JOB_STATUS_PENDING
    assert active[0].attempts == 0
    assert active[0].last_error is None


def test_disabled_status_shape(
    db_session, credential_key, monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account_id = _gmail_account_id(db_session, credential_key, monkeypatch)
    SourceSyncScheduler(db_session).run_maintenance()
    job = db_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
            Job.payload["account_id"].as_string() == str(account_id),
        )
    )
    job.last_error = "old provider error"
    job.status = JOB_STATUS_FAILED
    db_session.flush()
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID, SOURCE_GMAIL, enabled=False, enabled_specified=True
    )
    SourceSyncScheduler(db_session).run_maintenance()
    rows = SourceStatusService(db_session, BOOTSTRAP_USER_ID).list_status()
    gmail_rows = [row for row in rows if row.source == SOURCE_GMAIL]
    assert len(gmail_rows) == 1
    row = gmail_rows[0]
    assert row.enabled is False
    assert row.status == "disabled"
    assert row.next_sync_at is None
    assert row.last_error is None


def test_reenable_status_no_duplicate_rows(
    db_session, credential_key, monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    _gmail_account_id(db_session, credential_key, monkeypatch)
    service = SourceSyncPreferenceService.build(db_session)
    SourceSyncScheduler(db_session).run_maintenance()
    service.update_preference(
        BOOTSTRAP_USER_ID, SOURCE_GMAIL, enabled=False, enabled_specified=True
    )
    SourceSyncScheduler(db_session).run_maintenance()
    service.update_preference(
        BOOTSTRAP_USER_ID, SOURCE_GMAIL, enabled=True, enabled_specified=True
    )
    SourceSyncScheduler(db_session).run_maintenance()
    rows = SourceStatusService(db_session, BOOTSTRAP_USER_ID).list_status()
    gmail_rows = [row for row in rows if row.source == SOURCE_GMAIL]
    assert len(gmail_rows) == 1


def test_connected_provider_without_preference_row_unchanged(
    db_session, credential_key, monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account_id = _gmail_account_id(db_session, credential_key, monkeypatch)
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()
    pref_count = db_session.scalar(
        select(func.count()).select_from(UserSourcePreference)
    )
    assert pref_count == 0
    job = JobQueueService(db_session).find_recurring_source_job(
        BOOTSTRAP_USER_ID,
        JOB_TYPE_SYNC_GOOGLE_GMAIL,
        account_id,
    )
    assert job is not None
    assert job.status == JOB_STATUS_PENDING


def test_unsupported_source_returns_404(auth_client: AuthTestClient) -> None:
    response = auth_client.patch(
        "/me/source-preferences/google_drive",
        json={"enabled": False},
    )
    assert response.status_code == 404


def test_empty_patch_returns_422(auth_client: AuthTestClient) -> None:
    response = auth_client.patch("/me/source-preferences/gmail", json={})
    assert response.status_code == 422


def test_patch_disable_immediately_retires_pending_without_maintenance(
    auth_client: AuthTestClient,
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account_id = _gmail_account_id(db_session, credential_key, monkeypatch)
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.flush()
    job = JobQueueService(db_session).find_recurring_source_job(
        BOOTSTRAP_USER_ID,
        JOB_TYPE_SYNC_GOOGLE_GMAIL,
        account_id,
    )
    assert job is not None
    assert job.status == JOB_STATUS_PENDING

    response = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"enabled": False},
    )
    assert response.status_code == 200
    db_session.expire_all()
    stored = db_session.get(Job, job.id)
    assert stored is not None
    assert stored.status == JOB_STATUS_DONE


def test_patch_enable_immediately_reactivates_without_maintenance(
    auth_client: AuthTestClient,
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account_id = _gmail_account_id(db_session, credential_key, monkeypatch)
    SourceSyncScheduler(db_session).run_maintenance()
    auth_client.patch("/me/source-preferences/gmail", json={"enabled": False})

    response = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"enabled": True},
    )
    assert response.status_code == 200
    jobs = list(
        db_session.scalars(
            select(Job).where(
                Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
                Job.user_id == BOOTSTRAP_USER_ID,
            )
        )
    )
    active = [job for job in jobs if job.status != JOB_STATUS_DONE]
    assert len(active) == 1
    assert active[0].payload["account_id"] == str(account_id)
    assert active[0].status == JOB_STATUS_PENDING
    assert active[0].attempts == 0
    assert active[0].last_error is None
    assert active[0].run_after <= utcnow() + timedelta(seconds=2)


def test_worker_skips_handler_when_disabled_before_execution(
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_embedding_service,
) -> None:
    handler_calls = 0

    def fake_handler(session, embedding_service, payload, user_id) -> None:
        nonlocal handler_calls
        handler_calls += 1

    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account_id = _persist_gmail_schedule(credential_key, [GMAIL_READONLY_SCOPE])
    conn = engine.connect()
    trans = conn.begin()
    persist_session = Session(bind=conn)
    SourceSyncPreferenceService.build(persist_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_GMAIL,
        enabled=False,
        enabled_specified=True,
    )
    trans.commit()
    conn.close()

    conn = engine.connect()
    trans = conn.begin()
    ready_session = Session(bind=conn)
    job = ready_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
            Job.payload["account_id"].as_string() == str(account_id),
        )
    )
    job.run_after = utcnow() - timedelta(seconds=1)
    trans.commit()
    conn.close()

    with patch.dict(HANDLERS, {JOB_TYPE_SYNC_GOOGLE_GMAIL: fake_handler}):
        assert process_one_job(fake_embedding_service)

    assert handler_calls == 0
    conn = engine.connect()
    stored = Session(bind=conn).scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
            Job.payload["account_id"].as_string() == str(account_id),
        )
    )
    conn.close()
    assert stored is not None
    assert stored.status == JOB_STATUS_DONE


def test_disabled_before_connect_shows_status_without_job(
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_GMAIL,
        enabled=False,
        enabled_specified=True,
    )
    _gmail_account_id(db_session, credential_key, monkeypatch)
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.flush()
    job = db_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
            Job.user_id == BOOTSTRAP_USER_ID,
        )
    )
    assert job is None
    rows = SourceStatusService(db_session, BOOTSTRAP_USER_ID).list_status()
    gmail_rows = [row for row in rows if row.source == SOURCE_GMAIL]
    assert len(gmail_rows) == 1
    assert gmail_rows[0].enabled is False
    assert gmail_rows[0].status == "disabled"
    assert gmail_rows[0].next_sync_at is None
    assert gmail_rows[0].last_error is None


def test_disconnected_account_with_retired_job_has_no_status_row(
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import GoogleAccount

    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account_id = _gmail_account_id(db_session, credential_key, monkeypatch)
    SourceSyncScheduler(db_session).run_maintenance()
    account = db_session.get(GoogleAccount, account_id)
    db_session.delete(account)
    db_session.flush()
    rows = SourceStatusService(db_session, BOOTSTRAP_USER_ID).list_status()
    assert not any(row.source == SOURCE_GMAIL for row in rows)


def test_patch_clear_sync_interval_returns_deployment_default(
    auth_client: AuthTestClient,
    db_session,
) -> None:
    custom = settings.source_sync_gmail_interval_seconds + 300
    set_resp = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"sync_interval_seconds": custom},
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["sync_interval_seconds"] == custom

    clear_resp = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"sync_interval_seconds": None},
    )
    assert clear_resp.status_code == 200
    assert (
        clear_resp.json()["sync_interval_seconds"]
        == settings.source_sync_gmail_interval_seconds
    )
    pref_count = db_session.scalar(
        select(func.count()).select_from(UserSourcePreference)
    )
    assert pref_count == 0


def test_patch_clear_enabled_returns_default_enabled(
    auth_client: AuthTestClient,
    db_session,
) -> None:
    disable_resp = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"enabled": False},
    )
    assert disable_resp.status_code == 200
    assert disable_resp.json()["enabled"] is False

    clear_resp = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"enabled": None},
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["enabled"] is True
    pref_count = db_session.scalar(
        select(func.count()).select_from(UserSourcePreference)
    )
    assert pref_count == 0
