"""Yandex recurring transient retries stay within a short bounded latency."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.core.config import settings
from app.db.models import Job
from app.jobs.constants import (
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_SYNC_GOOGLE_GMAIL,
    JOB_TYPE_SYNC_YANDEX_CALENDAR,
    JOB_TYPE_SYNC_YANDEX_MAIL,
    MAX_JOB_ATTEMPTS,
)
from app.jobs.recurring_job_finalization import finalize_recurring_job_failure
from app.services.job_queue_service import (
    YANDEX_TRANSIENT_RETRY_DELAYS_SECONDS,
    JobQueueService,
)
from app.services.source_status_service import SourceStatusService
from app.users.bootstrap import BOOTSTRAP_USER_ID

KEY = Fernet.generate_key().decode()
FIXED_NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def configured_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", KEY)


def _job(db_session, job_type: str) -> Job:
    return JobQueueService(db_session).enqueue(
        job_type,
        {"account_id": str(uuid4())},
        BOOTSTRAP_USER_ID,
    )


@pytest.mark.parametrize(
    ("job_type", "attempts", "expected_delay"),
    [
        (JOB_TYPE_SYNC_YANDEX_MAIL, 1, 10),
        (JOB_TYPE_SYNC_YANDEX_MAIL, 2, 30),
        (JOB_TYPE_SYNC_YANDEX_MAIL, 3, 60),
        (JOB_TYPE_SYNC_YANDEX_MAIL, 4, 60),
        (JOB_TYPE_SYNC_YANDEX_CALENDAR, 1, 10),
        (JOB_TYPE_SYNC_YANDEX_CALENDAR, 2, 30),
        (JOB_TYPE_SYNC_YANDEX_CALENDAR, 3, 60),
        (JOB_TYPE_SYNC_YANDEX_CALENDAR, 8, 60),
    ],
)
def test_yandex_transient_retry_uses_bounded_delay(
    db_session, monkeypatch, job_type, attempts, expected_delay
) -> None:
    monkeypatch.setattr("app.services.job_queue_service.utcnow", lambda: FIXED_NOW)
    job = _job(db_session, job_type)
    job.status = JOB_STATUS_RUNNING
    job.attempts = attempts
    job.locked_at = FIXED_NOW

    JobQueueService(db_session).mark_recurring_transient_retry(
        job.id, "Yandex temporary provider failure"
    )

    assert job.status == JOB_STATUS_PENDING
    assert job.locked_at is None
    assert job.run_after == FIXED_NOW + timedelta(seconds=expected_delay)
    assert job.payload["last_error_kind"] == "transient"
    assert job.payload["last_error_retryable"] is True
    assert job.last_error == "Yandex temporary provider failure"
    assert job.attempts <= MAX_JOB_ATTEMPTS - 1
    assert expected_delay <= YANDEX_TRANSIENT_RETRY_DELAYS_SECONDS[-1]


@pytest.mark.parametrize("job_type", [JOB_TYPE_SYNC_YANDEX_MAIL, JOB_TYPE_SYNC_YANDEX_CALENDAR])
def test_yandex_finalizer_routes_retryable_transient_without_failed_rearm(
    db_session, monkeypatch, job_type
) -> None:
    monkeypatch.setattr("app.services.job_queue_service.utcnow", lambda: FIXED_NOW)
    monkeypatch.setattr(settings, "source_sync_failed_rearm_seconds", 3600)
    job = _job(db_session, job_type)
    job.status = JOB_STATUS_RUNNING
    job.attempts = MAX_JOB_ATTEMPTS
    job.locked_at = FIXED_NOW

    finalize_recurring_job_failure(
        db_session,
        job.id,
        BOOTSTRAP_USER_ID,
        job_type,
        "temporary failure",
        retryable=True,
        failure_kind="transient",
    )

    assert job.status == JOB_STATUS_PENDING
    assert job.run_after == FIXED_NOW + timedelta(seconds=60)
    assert job.run_after < FIXED_NOW + timedelta(seconds=3600)


def test_stale_max_attempt_yandex_transient_is_rearmed_shortly(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.services.job_queue_service.utcnow", lambda: FIXED_NOW)
    job = _job(db_session, JOB_TYPE_SYNC_YANDEX_MAIL)
    job.status = JOB_STATUS_RUNNING
    job.attempts = MAX_JOB_ATTEMPTS
    job.locked_at = FIXED_NOW - timedelta(minutes=16)
    job.last_error = "temporary failure"
    job.payload = {
        **job.payload,
        "last_error_kind": "transient",
        "last_error_retryable": True,
    }
    db_session.flush()

    assert JobQueueService(db_session).claim_next() is None
    assert job.status == JOB_STATUS_PENDING
    assert job.run_after == FIXED_NOW + timedelta(seconds=60)


@pytest.mark.parametrize(
    "failure_kind",
    ["authentication", "permission", "unknown", "transient"],
)
def test_non_transient_or_non_retryable_yandex_failure_keeps_failed_rearm(
    db_session, monkeypatch, failure_kind
) -> None:
    monkeypatch.setattr("app.services.job_queue_service.utcnow", lambda: FIXED_NOW)
    monkeypatch.setattr(settings, "source_sync_failed_rearm_seconds", 3600)
    job = _job(db_session, JOB_TYPE_SYNC_YANDEX_MAIL)
    job.status = JOB_STATUS_RUNNING
    job.attempts = 1
    job.locked_at = FIXED_NOW

    finalize_recurring_job_failure(
        db_session,
        job.id,
        BOOTSTRAP_USER_ID,
        job.type,
        "conservative failure",
        retryable=failure_kind == "unknown",
        failure_kind=failure_kind,
    )

    assert job.status == JOB_STATUS_FAILED
    assert job.run_after == FIXED_NOW + timedelta(seconds=3600)


def test_success_resets_transient_metadata_and_uses_normal_interval(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.services.job_queue_service.utcnow", lambda: FIXED_NOW)
    job = _job(db_session, JOB_TYPE_SYNC_YANDEX_MAIL)
    job.status = JOB_STATUS_RUNNING
    job.attempts = MAX_JOB_ATTEMPTS
    job.payload = {
        **job.payload,
        "last_error_kind": "transient",
        "last_error_retryable": True,
    }
    db_session.flush()

    JobQueueService(db_session).mark_recurring_success(job.id, interval_seconds=120)

    assert job.status == JOB_STATUS_PENDING
    assert job.attempts == 0
    assert job.last_error is None
    assert "last_error_kind" not in job.payload
    assert "last_error_retryable" not in job.payload
    assert job.run_after == FIXED_NOW + timedelta(seconds=120)


def test_generic_google_recurring_retry_still_exhausts(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.services.job_queue_service.utcnow", lambda: FIXED_NOW)
    job = _job(db_session, JOB_TYPE_SYNC_GOOGLE_GMAIL)
    job.status = JOB_STATUS_RUNNING
    job.attempts = MAX_JOB_ATTEMPTS

    JobQueueService(db_session).mark_retry(job.id, "generic failure", retryable=True)

    assert job.status == JOB_STATUS_FAILED
    assert job.run_after == FIXED_NOW + timedelta(seconds=settings.source_sync_failed_rearm_seconds)


def test_source_status_retains_transient_error_and_short_next_sync(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.services.job_queue_service.utcnow", lambda: FIXED_NOW)
    account = YandexMailAccountStore(db_session, CredentialEncryption(KEY)).upsert_account(
        BOOTSTRAP_USER_ID,
        "retry-status@yandex.example",
        "dummy-app-password",
        "imap.yandex.ru",
        993,
    )
    job = JobQueueService(db_session).enqueue(
        JOB_TYPE_SYNC_YANDEX_MAIL,
        {
            "account_id": str(account.id),
            "last_error_kind": "transient",
            "last_error_retryable": True,
        },
        BOOTSTRAP_USER_ID,
        run_after=FIXED_NOW + timedelta(seconds=30),
    )
    job.last_error = "Yandex temporary provider failure"
    job.attempts = 2
    db_session.flush()

    row = next(
        item
        for item in SourceStatusService(db_session, BOOTSTRAP_USER_ID).list_status()
        if item.account_id == account.id
    )

    assert row.status == "error"
    assert row.error_kind == "transient"
    assert row.retryable is True
    assert row.last_error == "Yandex temporary provider failure"
    assert row.next_sync_at == job.run_after
