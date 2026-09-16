import uuid
from datetime import timedelta

import httpx
import pytest
from cryptography.fernet import Fernet

from app.connectors.google.api_errors import (
    format_google_api_error,
    is_google_error_retryable,
    raise_for_google_response,
)
from app.connectors.google.calendar_transport import CalendarTransport
from app.connectors.google.errors import GoogleApiError
from app.db.models import Job
from app.jobs.constants import JOB_STATUS_PENDING, JOB_TYPE_SYNC_GOOGLE_CALENDAR
from app.services.job_queue_service import JobQueueService, utcnow
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


def _google_error_response(
    status_code: int,
    reason: str,
    message: str,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={
            "error": {
                "code": status_code,
                "message": message,
                "status": "PERMISSION_DENIED",
                "errors": [{"reason": reason, "message": message}],
            }
        },
    )


def test_raise_for_google_response_preserves_403_reason() -> None:
    response = _google_error_response(
        403,
        "insufficientPermissions",
        "Insufficient Permission",
    )
    with pytest.raises(GoogleApiError) as exc_info:
        raise_for_google_response(response, "list_calendars")
    error = exc_info.value
    assert error.operation == "list_calendars"
    assert error.status_code == 403
    assert error.reason == "insufficientPermissions"
    assert error.api_status == "PERMISSION_DENIED"
    assert error.retryable is False
    assert "Insufficient Permission" in error.message


def test_insufficient_permissions_classified_non_retryable() -> None:
    assert is_google_error_retryable(403, "insufficientPermissions") is False


def test_access_not_configured_classified_non_retryable() -> None:
    assert is_google_error_retryable(403, "accessNotConfigured") is False


def test_rate_limit_classified_retryable() -> None:
    assert is_google_error_retryable(429, "rateLimitExceeded") is True
    assert is_google_error_retryable(403, "userRateLimitExceeded") is True


def test_5xx_classified_retryable() -> None:
    assert is_google_error_retryable(503, None) is True


def test_calendar_transport_403_raises_structured_error() -> None:
    class ForbiddenClient:
        def get(self, url, params=None, headers=None, **kwargs):
            return _google_error_response(
                403,
                "insufficientPermissions",
                "Insufficient Permission",
            )

    transport = CalendarTransport(http_client=ForbiddenClient())
    with pytest.raises(GoogleApiError) as exc_info:
        transport.list_calendars("access-token", 10)
    assert exc_info.value.operation == "list_calendars"
    assert exc_info.value.reason == "insufficientPermissions"


def test_format_google_api_error_never_leaks_token() -> None:
    error = GoogleApiError(
        "Bearer ya29.secret-token-value",
        operation="list_calendars",
        status_code=403,
        reason="insufficientPermissions",
        retryable=False,
    )
    formatted = format_google_api_error(error)
    assert "ya29" not in formatted
    assert "Bearer" not in formatted


def test_malformed_json_error_response_safe() -> None:
    response = httpx.Response(403, text="not-json")
    with pytest.raises(GoogleApiError) as exc_info:
        raise_for_google_response(response, "list_calendars")
    assert exc_info.value.status_code == 403
    assert exc_info.value.retryable is False


def test_permanent_google_calendar_403_no_rapid_retry(
    db_session, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.source_sync_failed_rearm_seconds",
        3600,
    )
    queue = JobQueueService(db_session)
    job = queue.ensure_recurring_source_job(
        JOB_TYPE_SYNC_GOOGLE_CALENDAR,
        uuid.uuid4(),
        BOOTSTRAP_USER_ID,
    )
    job.run_after = utcnow() - timedelta(seconds=1)
    db_session.commit()

    claimed = queue.claim_next()
    assert claimed is not None
    db_session.commit()

    queue.mark_retry(
        claimed.id,
        "list_calendars: 403: insufficientPermissions: Insufficient Permission",
        retryable=False,
    )
    db_session.commit()

    stored = db_session.get(Job, claimed.id)
    assert stored is not None
    assert stored.status == JOB_STATUS_PENDING
    assert stored.attempts == 0
    assert "insufficientPermissions" in stored.last_error
    assert (stored.run_after - utcnow()).total_seconds() >= 3500


def test_retryable_google_calendar_error_uses_short_backoff(db_session) -> None:
    queue = JobQueueService(db_session)
    job = queue.ensure_recurring_source_job(
        JOB_TYPE_SYNC_GOOGLE_CALENDAR,
        uuid.uuid4(),
        BOOTSTRAP_USER_ID,
    )
    job.run_after = utcnow() - timedelta(seconds=1)
    db_session.commit()

    claimed = queue.claim_next()
    assert claimed is not None
    db_session.commit()

    queue.mark_retry(
        claimed.id,
        "list_calendars: 429: rateLimitExceeded: Rate Limit Exceeded",
        retryable=True,
    )
    db_session.commit()

    stored = db_session.get(Job, claimed.id)
    assert stored is not None
    assert stored.status == JOB_STATUS_PENDING
    assert stored.attempts == 1
    assert (stored.run_after - utcnow()).total_seconds() <= 15
