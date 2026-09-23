import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.connectors.google.api_errors import (
    parse_google_retry_after,
    raise_for_google_response,
)
from app.connectors.google.errors import (
    GoogleApiError,
    GoogleOAuthError,
    classify_google_sync_failure,
)
from app.connectors.google.gmail_transport import GmailTransport
from app.connectors.google.oauth_service import GoogleOAuthService
from app.db.models import Job
from app.jobs.constants import (
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_SYNC_GOOGLE_CALENDAR,
    JOB_TYPE_SYNC_GOOGLE_GMAIL,
    MAX_JOB_ATTEMPTS,
)
from app.jobs.recurring_job_finalization import finalize_recurring_job_failure
from app.services.job_queue_service import JobQueueService, sanitize_job_error, utcnow
from app.services.source_status_service import (
    SourceStatusService,
    _ConnectedSourceAccount,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _google_response(status: int, reason: str, *, headers: dict[str, str] | None = None):
    return httpx.Response(
        status,
        json={
            "error": {
                "code": status,
                "message": "provider failure",
                "status": "PERMISSION_DENIED" if status == 403 else None,
                "errors": [{"reason": reason, "message": "provider failure"}],
            }
        },
        headers=headers,
    )


def _recurring_job(db_session, job_type: str) -> Job:
    queue = JobQueueService(db_session)
    job = queue.ensure_recurring_source_job(job_type, uuid.uuid4(), BOOTSTRAP_USER_ID)
    job.status = JOB_STATUS_RUNNING
    job.attempts = 1
    db_session.flush()
    return job


@pytest.mark.parametrize("job_type", [JOB_TYPE_SYNC_GOOGLE_GMAIL, JOB_TYPE_SYNC_GOOGLE_CALENDAR])
def test_google_transient_retry_tiers_and_bound(db_session, job_type: str) -> None:
    job = _recurring_job(db_session, job_type)
    expected = (10, 30, 60, 60)
    for index, delay in enumerate(expected):
        job.attempts = index + 1
        before = utcnow()
        finalize_recurring_job_failure(
            db_session,
            job.id,
            BOOTSTRAP_USER_ID,
            job_type,
            "provider failure",
            failure_kind="transient",
            retryable=True,
        )
        assert job.status == JOB_STATUS_PENDING
        assert job.locked_at is None
        assert job.payload["last_error_kind"] == "transient"
        assert job.payload["last_error_retryable"] is True
        seconds = (job.run_after - before).total_seconds()
        assert delay - 1 <= seconds <= delay + 1


def test_google_retry_at_max_attempts_does_not_use_failed_cooldown(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.source_sync_failed_rearm_seconds", 3600)
    job = _recurring_job(db_session, JOB_TYPE_SYNC_GOOGLE_GMAIL)
    job.attempts = MAX_JOB_ATTEMPTS
    job.payload = {
        "account_id": job.payload["account_id"],
        "last_error_kind": "transient",
        "last_error_retryable": True,
    }
    job.locked_at = utcnow() - timedelta(minutes=16)
    job.status = JOB_STATUS_RUNNING
    job.run_after = utcnow() - timedelta(seconds=1)
    db_session.flush()

    assert JobQueueService(db_session).claim_next(include_types={JOB_TYPE_SYNC_GOOGLE_GMAIL}) is None
    assert job.status == JOB_STATUS_PENDING
    assert (job.run_after - utcnow()).total_seconds() <= 61
    assert job.attempts == MAX_JOB_ATTEMPTS - 1


def test_google_retry_after_delta_and_http_date() -> None:
    now = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)
    assert parse_google_retry_after("75", now=now) == 75
    assert parse_google_retry_after("-1", now=now) is None
    assert parse_google_retry_after("invalid", now=now) is None
    assert parse_google_retry_after("Thu, 17 Sep 2026 10:02:00 GMT", now=now) == 120
    assert parse_google_retry_after("Thu, 17 Sep 2026 09:59:59 GMT", now=now) is None


def test_google_provider_retry_after_over_60_is_honored(db_session) -> None:
    job = _recurring_job(db_session, JOB_TYPE_SYNC_GOOGLE_CALENDAR)
    finalize_recurring_job_failure(
        db_session,
        job.id,
        BOOTSTRAP_USER_ID,
        JOB_TYPE_SYNC_GOOGLE_CALENDAR,
        "rate limited",
        failure_kind="transient",
        retryable=True,
        retry_after_seconds=120,
    )
    assert 119 <= (job.run_after - utcnow()).total_seconds() <= 121


@pytest.mark.parametrize(
    ("status", "reason", "kind", "retryable"),
    [
        (429, "rateLimitExceeded", "transient", True),
        (503, "backendError", "transient", True),
        (500, "internalError", "transient", True),
        (401, "authError", "authentication", False),
        (403, "insufficientPermissions", "permission", False),
        (403, "userRateLimitExceeded", "transient", True),
    ],
)
def test_google_failure_classification(status, reason, kind, retryable) -> None:
    with pytest.raises(GoogleApiError) as exc_info:
        raise_for_google_response(_google_response(status, reason), "sync")
    assert classify_google_sync_failure(exc_info.value)[:2] == (kind, retryable)


def test_google_auth_and_transport_failure_classification() -> None:
    assert classify_google_sync_failure(GoogleOAuthError("expired")) == (
        "authentication",
        False,
        None,
    )
    assert classify_google_sync_failure(httpx.ConnectError("offline")) == (
        "transient",
        True,
        None,
    )
    assert classify_google_sync_failure(RuntimeError("unknown")) == (
        "unknown",
        False,
        None,
    )


def test_google_oauth_default_is_authentication_nonretryable() -> None:
    assert classify_google_sync_failure(GoogleOAuthError("invalid grant")) == (
        "authentication",
        False,
        None,
    )


@pytest.mark.parametrize("status", [429, 503])
def test_google_oauth_refresh_transient_failure_is_retryable(tmp_path, status: int) -> None:
    client_file = tmp_path / "client.json"
    client_file.write_text(
        '{"web":{"client_id":"client","client_secret":"secret"}}',
        encoding="utf-8",
    )

    class Client:
        def post(self, *args, **kwargs):
            return _google_response(status, "server_error", headers={"Retry-After": "90"})

    service = GoogleOAuthService(str(client_file), "http://localhost/callback", http_client=Client())
    with pytest.raises(GoogleOAuthError) as exc_info:
        service.refresh_access_token("refresh-token")
    error = exc_info.value
    assert error.status_code == status
    assert error.retryable is True
    assert error.retry_after_seconds == 90
    assert classify_google_sync_failure(error) == ("transient", True, 90)


def test_google_oauth_refresh_invalid_grant_is_authentication(tmp_path) -> None:
    client_file = tmp_path / "client.json"
    client_file.write_text(
        '{"web":{"client_id":"client","client_secret":"client-secret-value"}}',
        encoding="utf-8",
    )

    class Client:
        def post(self, *args, **kwargs):
            assert kwargs["data"]["refresh_token"] == "refresh-token-value"
            assert kwargs["data"]["client_secret"] == "client-secret-value"
            return httpx.Response(
                400,
                json={
                    "error": "invalid_grant",
                    "error_description": "refresh-token-value client-secret-value leaked",
                },
            )

    service = GoogleOAuthService(str(client_file), "http://localhost/callback", http_client=Client())
    with pytest.raises(GoogleOAuthError) as exc_info:
        service.refresh_access_token("refresh-token-value")
    error = exc_info.value
    assert error.oauth_error == "invalid_grant"
    assert classify_google_sync_failure(error) == ("authentication", False, None)
    visible = sanitize_job_error(error)
    assert visible == "Google authentication failed (invalid_grant). Reconnect the Google account."
    assert "refresh-token-value" not in visible
    assert "client-secret-value" not in visible
    assert "leaked" not in visible


def test_google_oauth_transient_failure_uses_recurring_short_retry(db_session) -> None:
    job = _recurring_job(db_session, JOB_TYPE_SYNC_GOOGLE_GMAIL)
    error = GoogleOAuthError(
        "failed to refresh access token",
        status_code=503,
        retryable=True,
        retry_after_seconds=90,
    )
    failure_kind, retryable, retry_after_seconds = classify_google_sync_failure(error)
    finalize_recurring_job_failure(
        db_session,
        job.id,
        BOOTSTRAP_USER_ID,
        JOB_TYPE_SYNC_GOOGLE_GMAIL,
        "failed to refresh access token",
        failure_kind=failure_kind,
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
    )
    assert job.status == JOB_STATUS_PENDING
    assert 89 <= (job.run_after - utcnow()).total_seconds() <= 91


def test_google_permission_denied_without_reason_is_permission() -> None:
    error = GoogleApiError(
        "denied",
        status_code=403,
        api_status="PERMISSION_DENIED",
        retryable=False,
    )
    assert classify_google_sync_failure(error) == ("permission", False, None)


def test_gmail_read_http_errors_are_structured_and_retryable() -> None:
    class Client:
        def get(self, url, params=None, headers=None, **kwargs):
            return _google_response(429, "rateLimitExceeded", headers={"Retry-After": "90"})

    transport = GmailTransport(http_client=Client())
    calls = (
        lambda: transport.list_message_ids_page("token", "me", "", 10),
        lambda: transport.get_message("token", "me", "message"),
        lambda: transport.get_attachment("token", "me", "message", "attachment"),
    )
    for call in calls:
        with pytest.raises(GoogleApiError) as exc_info:
            call()
        error = exc_info.value
        assert error.status_code == 429
        assert error.reason == "rateLimitExceeded"
        assert error.retryable is True
        assert error.retry_after_seconds == 90


def test_google_success_clears_transient_metadata(db_session) -> None:
    job = _recurring_job(db_session, JOB_TYPE_SYNC_GOOGLE_GMAIL)
    job.payload.update({"last_error_kind": "transient", "last_error_retryable": True})
    queue = JobQueueService(db_session)
    queue.mark_recurring_success(job.id, 120)
    assert job.status == JOB_STATUS_PENDING
    assert job.attempts == 0
    assert job.last_error is None
    assert "last_error_kind" not in job.payload
    assert SourceStatusService._failure_metadata(job) == (None, False)


def test_source_status_reports_google_transient_retry(db_session, monkeypatch) -> None:
    account_id = uuid.uuid4()
    job = Job(
        user_id=BOOTSTRAP_USER_ID,
        type=JOB_TYPE_SYNC_GOOGLE_GMAIL,
        payload={
            "account_id": str(account_id),
            "last_error_kind": "transient",
            "last_error_retryable": True,
        },
        status=JOB_STATUS_PENDING,
        attempts=2,
        last_error="provider failure",
        run_after=utcnow() + timedelta(seconds=30),
    )
    db_session.add(job)
    db_session.flush()
    monkeypatch.setattr(
        SourceStatusService,
        "_connected_accounts",
        lambda _self: [
            _ConnectedSourceAccount(
                source_key="gmail",
                job_type=JOB_TYPE_SYNC_GOOGLE_GMAIL,
                account_id=account_id,
                account_label="user@example.com",
            )
        ],
    )

    row = SourceStatusService(db_session, BOOTSTRAP_USER_ID).list_status()[0]
    assert row.error_kind == "transient"
    assert row.retryable is True
    assert row.next_sync_at == job.run_after
    assert row.status == "error"


def test_google_auth_failure_remains_conservative(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.source_sync_failed_rearm_seconds", 3600)
    job = _recurring_job(db_session, JOB_TYPE_SYNC_GOOGLE_CALENDAR)
    finalize_recurring_job_failure(
        db_session,
        job.id,
        BOOTSTRAP_USER_ID,
        JOB_TYPE_SYNC_GOOGLE_CALENDAR,
        "expired",
        failure_kind="authentication",
        retryable=False,
    )
    assert job.status != JOB_STATUS_PENDING
    assert job.payload["last_error_kind"] == "authentication"
    assert job.payload["last_error_retryable"] is False
    assert (job.run_after - utcnow()).total_seconds() >= 3500
