"""Tests for Google Drive files.get error classification (PHASE 27C-R4C)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from cryptography.fernet import Fernet

from app.connectors.google.api_errors import raise_for_google_response
from app.connectors.google.constants import DRIVE_READONLY_SCOPE
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.drive_metadata_errors import raise_for_drive_metadata_error
from app.connectors.google.drive_transport import DriveTransport
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleApiError, GoogleConfigurationError
from app.db.models import GoogleAccount
from app.services.explicit_link_intake_errors import ExplicitLinkIntakeError
from app.services.explicit_link_intake_service import build_google_explicit_link_intake_service
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _google_error_response(
    status_code: int,
    reason: str,
    message: str = "Google API error",
    api_status: str | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={
            "error": {
                "code": status_code,
                "message": message,
                "status": api_status or reason.upper().replace("notfound", "NOT_FOUND"),
                "errors": [{"reason": reason, "message": message}],
            }
        },
    )


def _api_error(
    status_code: int,
    reason: str,
    api_status: str | None = None,
) -> GoogleApiError:
    with pytest.raises(GoogleApiError) as exc_info:
        raise_for_google_response(
            _google_error_response(status_code, reason, api_status=api_status),
            "get_file_metadata",
        )
    return exc_info.value


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


class ErrorDriveTransport:
    def __init__(self, error: GoogleApiError) -> None:
        self._error = error
        self.calls: list[str] = []

    def get_file_metadata(self, access_token: str, file_id: str) -> dict[str, Any]:
        self.calls.append(file_id)
        raise self._error

    def close(self) -> None:
        pass


class SuccessDriveTransport:
    def __init__(self, file_id: str, name: str = "Shared doc") -> None:
        self._file_id = file_id
        self._name = name
        self.last_params: dict[str, str] | None = None
        self.calls: list[str] = []

    def get_file_metadata(self, access_token: str, file_id: str) -> dict[str, Any]:
        self.calls.append(file_id)
        return {
            "id": file_id,
            "name": self._name,
            "mimeType": "application/vnd.google-apps.document",
            "trashed": False,
        }

    def close(self) -> None:
        pass


def _google_account(db_session, credential_key: str) -> GoogleAccount:
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="drive@example.com",
        scopes=[DRIVE_READONLY_SCOPE],
        access_token="unittest-google-access",
        refresh_token="unittest-google-refresh",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.flush()
    return account


def test_service_disabled_raises_deployment_configuration_error() -> None:
    exc = _api_error(403, "serviceDisabled", api_status="PERMISSION_DENIED")
    with pytest.raises(GoogleConfigurationError, match="not enabled for this deployment"):
        raise_for_drive_metadata_error(exc)


def test_access_not_configured_raises_deployment_configuration_error() -> None:
    exc = _api_error(403, "accessNotConfigured", api_status="PERMISSION_DENIED")
    with pytest.raises(GoogleConfigurationError, match="not enabled for this deployment"):
        raise_for_drive_metadata_error(exc)


def test_not_configured_raises_deployment_configuration_error() -> None:
    exc = _api_error(403, "notConfigured", api_status="PERMISSION_DENIED")
    with pytest.raises(GoogleConfigurationError, match="not enabled for this deployment"):
        raise_for_drive_metadata_error(exc)


def test_forbidden_raises_resource_permission_denied() -> None:
    exc = _api_error(403, "forbidden", api_status="PERMISSION_DENIED")
    with pytest.raises(
        ExplicitLinkIntakeError,
        match="google drive resource permission denied",
    ):
        raise_for_drive_metadata_error(exc)


def test_rate_limit_exceeded_re_raises_original_google_api_error() -> None:
    exc = _api_error(403, "rateLimitExceeded", api_status="RESOURCE_EXHAUSTED")
    assert exc.retryable is True
    with pytest.raises(GoogleApiError) as raised:
        raise_for_drive_metadata_error(exc)
    err = raised.value
    assert err is exc
    assert err.status_code == 403
    assert err.reason == "rateLimitExceeded"
    assert err.api_status == "RESOURCE_EXHAUSTED"
    assert err.retryable is True


def test_user_rate_limit_exceeded_re_raises_original_google_api_error() -> None:
    exc = _api_error(403, "userRateLimitExceeded", api_status="RESOURCE_EXHAUSTED")
    assert exc.retryable is True
    with pytest.raises(GoogleApiError) as raised:
        raise_for_drive_metadata_error(exc)
    err = raised.value
    assert err is exc
    assert err.status_code == 403
    assert err.reason == "userRateLimitExceeded"
    assert err.api_status == "RESOURCE_EXHAUSTED"
    assert err.retryable is True


def test_domain_policy_raises_organization_policy_message() -> None:
    exc = _api_error(403, "domainPolicy", api_status="PERMISSION_DENIED")
    with pytest.raises(
        ExplicitLinkIntakeError,
        match="google drive access blocked by organization policy",
    ):
        raise_for_drive_metadata_error(exc)


def test_auth_error_raises_reconnect_message() -> None:
    exc = _api_error(401, "authError", api_status="UNAUTHENTICATED")
    with pytest.raises(
        ExplicitLinkIntakeError,
        match="google drive authorization requires reconnect",
    ):
        raise_for_drive_metadata_error(exc)


def test_not_found_raises_resource_unavailable() -> None:
    exc = _api_error(404, "notFound", api_status="NOT_FOUND")
    with pytest.raises(
        ExplicitLinkIntakeError,
        match="google drive resource unavailable",
    ):
        raise_for_drive_metadata_error(exc)


def test_drive_transport_files_get_includes_supports_all_drives() -> None:
    file_id = "shared-file"
    captured_params: dict[str, str] | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_params
        captured_params = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "id": file_id,
                "name": "Shared",
                "mimeType": "application/vnd.google-apps.document",
                "trashed": False,
            },
        )

    transport = DriveTransport(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    payload = transport.get_file_metadata("token", file_id)
    transport.close()

    assert payload["id"] == file_id
    assert captured_params is not None
    assert captured_params.get("supportsAllDrives") == "true"
    assert "fields" in captured_params


def test_intake_link_service_disabled_returns_503(
    db_session, credential_key, oauth_client_file, auth_client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.google_oauth_client_file",
        oauth_client_file,
    )
    monkeypatch.setattr(
        "app.core.config.settings.google_redirect_uri",
        "http://localhost:18080/auth/google/callback",
    )
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)

    account = _google_account(db_session, credential_key)
    file_id = "svc-disabled"
    transport = ErrorDriveTransport(_api_error(403, "serviceDisabled"))

    with patch(
        "app.api.intake.build_google_explicit_link_intake_service",
        return_value=build_google_explicit_link_intake_service(
            session=db_session,
            user_id=BOOTSTRAP_USER_ID,
            credential_key=credential_key,
            client_file=oauth_client_file,
            redirect_uri="http://localhost:18080/auth/google/callback",
            google_transport=transport,
        ),
    ):
        response = auth_client.post(
            "/intake/link",
            json={
                "url": f"https://drive.google.com/file/d/{file_id}/view",
                "account_id": str(account.id),
            },
        )
    assert response.status_code == 503
    assert "not enabled" in response.json()["detail"]


def test_intake_link_auth_error_returns_400_not_secretary_401(
    db_session, credential_key, oauth_client_file, auth_client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.google_oauth_client_file",
        oauth_client_file,
    )
    monkeypatch.setattr(
        "app.core.config.settings.google_redirect_uri",
        "http://localhost:18080/auth/google/callback",
    )
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)

    account = _google_account(db_session, credential_key)
    file_id = "auth-fail"
    transport = ErrorDriveTransport(_api_error(401, "authError", api_status="UNAUTHENTICATED"))

    with patch(
        "app.api.intake.build_google_explicit_link_intake_service",
        return_value=build_google_explicit_link_intake_service(
            session=db_session,
            user_id=BOOTSTRAP_USER_ID,
            credential_key=credential_key,
            client_file=oauth_client_file,
            redirect_uri="http://localhost:18080/auth/google/callback",
            google_transport=transport,
        ),
    ):
        response = auth_client.post(
            "/intake/link",
            json={
                "url": f"https://drive.google.com/file/d/{file_id}/view",
                "account_id": str(account.id),
            },
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "google drive authorization requires reconnect"
