"""Focused tests for Yandex CalDAV typed errors and credential validation."""

from datetime import UTC, datetime

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.api.schemas import SourceSyncStatusOut
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.yandex.caldav_api_errors import (
    format_yandex_caldav_error,
    raise_for_caldav_http_response,
    raise_for_caldav_request_error,
)
from app.connectors.yandex.caldav_host import (
    trusted_caldav_base_url,
    validate_trusted_caldav_host,
)
from app.connectors.yandex.caldav_transport import CalDavHttpTransport
from app.connectors.yandex.calendar_credentials import YandexCalendarAccountStore
from app.connectors.yandex.constants import DEFAULT_CALDAV_HOST
from app.connectors.yandex.errors import (
    YandexCalDavError,
    YandexCalDavStaleSyncTokenError,
    YandexConfigurationError,
    YandexConnectorError,
    YandexImapError,
)
from app.db.models import YandexCalendarAccount
from app.services.job_queue_service import is_job_error_retryable, sanitize_job_error
from tests.conftest import BOOTSTRAP_USER_ID

LEAK_MARKER = "sk-testPhase28bD2CalDavLeak"
AUTH_HEADER_LEAK = "Authorization: Basic leaked-secret"


@pytest.fixture
def credential_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", key)
    return key


def test_401_principal_is_auth_non_retryable() -> None:
    class Client:
        def request(self, method: str, url: str, **kwargs) -> httpx.Response:
            return httpx.Response(401, text=AUTH_HEADER_LEAK)

    transport = CalDavHttpTransport(
        email="user@yandex.ru",
        password="pass",
        http_client=Client(),
    )
    with pytest.raises(YandexCalDavError) as exc_info:
        transport.probe_principal()
    error = exc_info.value
    assert error.status_code == 401
    assert error.category == "auth"
    assert error.failure_kind == "authentication"
    assert error.retryable is False
    formatted = format_yandex_caldav_error(error)
    assert "authorization rejected" in formatted
    assert "401" in formatted
    assert LEAK_MARKER not in formatted
    assert "leaked-secret" not in formatted
    assert is_job_error_retryable(error) is False


def test_403_permission_is_non_retryable() -> None:
    class Client:
        def request(self, method: str, url: str, **kwargs) -> httpx.Response:
            return httpx.Response(403, text="permission denied")

    transport = CalDavHttpTransport(
        email="user@yandex.ru",
        password="pass",
        http_client=Client(),
    )
    with pytest.raises(YandexCalDavError) as exc_info:
        transport.probe_principal()
    error = exc_info.value
    assert error.category == "permission"
    assert error.failure_kind == "permission"
    assert error.retryable is False
    assert "permission denied" in format_yandex_caldav_error(error)


def test_403_stale_sync_token_still_raises_stale_error() -> None:
    stale_xml = "<d:error xmlns:d='DAV:'><d:valid-sync-token/></d:error>"

    class Client:
        def request(self, method: str, url: str, **kwargs) -> httpx.Response:
            return httpx.Response(403, text=stale_xml)

    transport = CalDavHttpTransport(
        email="user@yandex.ru",
        password="pass",
        http_client=Client(),
    )
    with pytest.raises(YandexCalDavStaleSyncTokenError):
        transport.sync_collection(
            "/calendars/user/default/",
            "old-token",
            100,
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 12, 31, tzinfo=UTC),
        )


def test_404_discovery_is_not_found_non_retryable() -> None:
    class Client:
        def request(self, method: str, url: str, **kwargs) -> httpx.Response:
            return httpx.Response(404, text="not found")

    transport = CalDavHttpTransport(
        email="user@yandex.ru",
        password="pass",
        http_client=Client(),
    )
    with pytest.raises(YandexCalDavError) as exc_info:
        transport.probe_principal()
    error = exc_info.value
    assert error.category == "not_found"
    assert error.retryable is False
    assert "endpoint not found" in format_yandex_caldav_error(error)


def test_429_is_retryable() -> None:
    response = httpx.Response(429, text="rate limited")
    with pytest.raises(YandexCalDavError) as exc_info:
        raise_for_caldav_http_response(response, operation="PROPFIND", path="/principal/")
    error = exc_info.value
    assert error.retryable is True
    assert is_job_error_retryable(error) is True
    assert error.failure_kind == "transient"


@pytest.mark.parametrize("status_code", [408, 425, 429, 500, 504])
def test_retryable_caldav_statuses_are_transient(status_code: int) -> None:
    with pytest.raises(YandexCalDavError) as exc_info:
        raise_for_caldav_http_response(
            httpx.Response(status_code),
            operation="PROPFIND",
            path="/principal/",
        )
    error = exc_info.value
    assert error.failure_kind == "transient"
    assert error.retryable is True


def test_503_is_retryable() -> None:
    response = httpx.Response(503, text="server error")
    with pytest.raises(YandexCalDavError) as exc_info:
        raise_for_caldav_http_response(response, operation="PROPFIND", path="/principal/")
    error = exc_info.value
    assert error.category == "server"
    assert error.failure_kind == "transient"
    assert error.retryable is True


def test_httpx_timeout_is_retryable_network_error() -> None:
    error = raise_for_caldav_request_error(
        httpx.TimeoutException("timeout"),
        operation="PROPFIND",
        path="/principal/",
    )
    assert error.category == "network"
    assert error.failure_kind == "transient"
    assert error.retryable is True
    assert "network timeout" in format_yandex_caldav_error(error)
    assert is_job_error_retryable(error) is True


def test_sanitize_job_error_hides_secret_markers() -> None:
    error = YandexCalDavError(
        LEAK_MARKER,
        operation="PROPFIND",
        path="/principal/",
        status_code=401,
        category="auth",
        retryable=False,
    )
    sanitized = sanitize_job_error(error)
    assert LEAK_MARKER not in sanitized
    assert "authorization rejected" in sanitized


def test_calendar_connect_invalid_credential_preserves_existing(
    auth_client, db_session, credential_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="calendar@yandex.ru",
        app_password="good-calendar-password",
        caldav_host=DEFAULT_CALDAV_HOST,
    )
    db_session.commit()
    original_encrypted = account.app_password_encrypted

    class BadClient:
        def request(self, method: str, url: str, **kwargs) -> httpx.Response:
            return httpx.Response(401, text="unauthorized")

    monkeypatch.setattr(
        "app.api.yandex.CalDavHttpTransport",
        lambda email, password, base_url, http_client=None: CalDavHttpTransport(
            email=email,
            password=password,
            base_url=base_url,
            http_client=BadClient(),
        ),
    )

    response = auth_client.post(
        "/connectors/yandex/calendar/connect",
        json={
            "email": "calendar@yandex.ru",
            "app_password": "bad-calendar-password",
        },
    )
    assert response.status_code == 400
    stored = db_session.scalar(
        select(YandexCalendarAccount).where(YandexCalendarAccount.id == account.id)
    )
    assert stored is not None
    assert stored.app_password_encrypted == original_encrypted
    assert store.get_app_password(stored) == "good-calendar-password"


def test_calendar_connect_valid_credential_persists(
    auth_client, db_session, credential_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)

    class OkClient:
        def request(self, method: str, url: str, **kwargs) -> httpx.Response:
            return httpx.Response(
                207,
                text=(
                    "<?xml version='1.0'?>"
                    "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>"
                    "<d:response><d:propstat><d:status>HTTP/1.1 200 OK</d:status>"
                    "<d:prop><c:calendar-home-set><d:href>/calendars/user/</d:href>"
                    "</c:calendar-home-set></d:prop></d:propstat></d:response>"
                    "</d:multistatus>"
                ),
            )

    monkeypatch.setattr(
        "app.api.yandex.CalDavHttpTransport",
        lambda email, password, base_url, http_client=None: CalDavHttpTransport(
            email=email,
            password=password,
            base_url=base_url,
            http_client=OkClient(),
        ),
    )

    response = auth_client.post(
        "/connectors/yandex/calendar/connect",
        json={
            "email": "newcalendar@yandex.ru",
            "app_password": "new-calendar-password",
        },
    )
    assert response.status_code == 200
    account = db_session.scalar(
        select(YandexCalendarAccount).where(
            YandexCalendarAccount.email == "newcalendar@yandex.ru"
        )
    )
    assert account is not None
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    assert store.get_app_password(account) == "new-calendar-password"


def test_calendar_connect_validation_does_not_sync_events(
    auth_client, credential_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    discover_calls = [0]

    class ProbeOnlyTransport(CalDavHttpTransport):
        def discover_calendars(self, max_results: int):
            discover_calls[0] += 1
            return []

        def probe_principal(self) -> None:
            return None

    monkeypatch.setattr(
        "app.api.yandex.CalDavHttpTransport",
        lambda email, password, base_url, http_client=None: ProbeOnlyTransport(
            email=email,
            password=password,
            base_url=base_url,
        ),
    )

    response = auth_client.post(
        "/connectors/yandex/calendar/connect",
        json={
            "email": "probe@yandex.ru",
            "app_password": "probe-password",
        },
    )
    assert response.status_code == 200
    assert discover_calls[0] == 0


def test_yandex_imap_error_is_retryable() -> None:
    assert is_job_error_retryable(YandexImapError("temporary failure")) is True


def test_generic_yandex_connector_error_is_retryable() -> None:
    assert is_job_error_retryable(YandexConnectorError("temporary connector failure")) is True


def test_yandex_configuration_error_is_not_retryable() -> None:
    assert is_job_error_retryable(YandexConfigurationError("credential key invalid")) is False


def test_unclassified_caldav_request_is_unknown() -> None:
    with pytest.raises(YandexCalDavError) as exc_info:
        raise_for_caldav_http_response(
            httpx.Response(400),
            operation="PROPFIND",
            path="/principal/",
        )
    error = exc_info.value
    assert error.failure_kind == "unknown"
    assert error.retryable is False


def test_source_status_schema_adds_typed_failure_fields_safely() -> None:
    base = {
        "source": "yandex_calendar",
        "provider": "yandex_calendar",
        "account_id": BOOTSTRAP_USER_ID,
        "account_label": "calendar@yandex.ru",
        "enabled": True,
        "status": "error",
        "last_success_at": None,
        "last_attempt_at": None,
        "next_sync_at": None,
        "last_error": "temporary failure",
    }
    legacy = SourceSyncStatusOut.model_validate(base)
    assert legacy.error_kind is None
    assert legacy.retryable is False

    typed = SourceSyncStatusOut.model_validate(
        {**base, "error_kind": "transient", "retryable": True}
    )
    assert typed.error_kind == "transient"
    assert typed.retryable is True


def test_trusted_caldav_host_caldav_yandex_ru_accepted() -> None:
    assert validate_trusted_caldav_host("caldav.yandex.ru") == DEFAULT_CALDAV_HOST
    assert trusted_caldav_base_url("caldav.yandex.ru") == "https://caldav.yandex.ru"


def test_trusted_caldav_host_https_url_accepted() -> None:
    assert validate_trusted_caldav_host("https://caldav.yandex.ru") == DEFAULT_CALDAV_HOST
    assert trusted_caldav_base_url("https://caldav.yandex.ru") == "https://caldav.yandex.ru"


def test_trusted_caldav_host_http_rejected() -> None:
    with pytest.raises(YandexConfigurationError, match="must use https"):
        validate_trusted_caldav_host("http://caldav.yandex.ru")


def test_trusted_caldav_host_evil_example_rejected() -> None:
    with pytest.raises(YandexConfigurationError, match="not allowed"):
        validate_trusted_caldav_host("evil.example")


def test_trusted_caldav_host_localhost_rejected() -> None:
    with pytest.raises(YandexConfigurationError, match="not allowed"):
        validate_trusted_caldav_host("localhost")


def test_trusted_caldav_host_127_rejected() -> None:
    with pytest.raises(YandexConfigurationError, match="not allowed"):
        validate_trusted_caldav_host("127.0.0.1")


def test_trusted_caldav_host_private_ip_rejected() -> None:
    with pytest.raises(YandexConfigurationError, match="not allowed"):
        validate_trusted_caldav_host("10.0.0.1")


def test_calendar_connect_rejected_host_makes_zero_http_calls(
    auth_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport_calls = 0

    def fake_transport(*args, **kwargs):
        nonlocal transport_calls
        transport_calls += 1
        raise AssertionError("transport should not be constructed")

    monkeypatch.setattr("app.api.yandex.CalDavHttpTransport", fake_transport)

    response = auth_client.post(
        "/connectors/yandex/calendar/connect",
        json={
            "email": "user@yandex.ru",
            "app_password": "probe-password",
            "caldav_host": "evil.example",
        },
    )
    assert response.status_code == 400
    assert transport_calls == 0
    assert "not allowed" in response.json()["detail"]
