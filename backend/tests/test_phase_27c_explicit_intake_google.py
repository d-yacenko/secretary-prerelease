import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.connectors.google.constants import (
    DRIVE_READONLY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GOOGLE_DRIVE_FOLDER_MIME,
    GOOGLE_DRIVE_PROVIDER,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.drive_normalize import build_canonical_uri
from app.connectors.google.drive_transport import DriveTransport
from app.connectors.google.drive_url_parser import parse_google_drive_file_id
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleApiError
from app.db.models import GoogleAccount, Job, Object, User
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT, JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT
from app.services.connection_status_service import ConnectionStatusService
from app.services.explicit_link_intake_service import (
    build_explicit_link_intake_service,
    build_google_explicit_link_intake_service,
)
from app.services.open_target_service import OpenTargetService
from app.users.bootstrap import BOOTSTRAP_USER_ID


class FakeYandexDiskTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_public_resource_metadata(self, public_key: str) -> dict[str, Any]:
        self.calls.append(("get_public_resource_metadata", public_key))
        return {}

    def close(self) -> None:
        pass


class FakeDriveTransport:
    def __init__(self, files: dict[str, dict[str, Any]] | None = None) -> None:
        self._files = dict(files or {})
        self.calls: list[tuple[str, str]] = []

    def get_file_metadata(self, access_token: str, file_id: str) -> dict[str, Any]:
        self.calls.append(("get_file_metadata", file_id))
        payload = self._files.get(file_id)
        if payload is None:
            raise GoogleApiError(
                "not found",
                operation="get_file_metadata",
                status_code=404,
            )
        return dict(payload)

    def close(self) -> None:
        pass


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


@pytest.fixture
def google_settings(monkeypatch: pytest.MonkeyPatch, oauth_client_file: str, credential_key: str) -> None:
    monkeypatch.setattr("app.core.config.settings.google_oauth_client_file", oauth_client_file)
    monkeypatch.setattr(
        "app.core.config.settings.google_redirect_uri",
        "http://localhost:18080/auth/google/callback",
    )
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _google_account(
    db_session,
    credential_key: str,
    scopes: list[str],
    email: str = "user@example.com",
    user_id: uuid.UUID = BOOTSTRAP_USER_ID,
) -> GoogleAccount:
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_tokens(
        user_id=user_id,
        email=email,
        scopes=scopes,
        access_token="unittest-google-access",
        refresh_token="unittest-google-refresh",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.flush()
    return account


def _drive_file(
    file_id: str,
    name: str,
    mime_type: str = "application/pdf",
    **kwargs: Any,
) -> dict[str, Any]:
    payload = {
        "id": file_id,
        "name": name,
        "mimeType": mime_type,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "modifiedTime": "2024-02-01T00:00:00.000Z",
        "size": "1234",
        "md5Checksum": "abc123",
        "parents": ["parent-folder"],
        "driveId": "shared-drive",
        "trashed": False,
        "webViewLink": f"https://evil.example/malicious/{file_id}",
    }
    payload.update(kwargs)
    return payload


def _intake_service(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    transport: FakeDriveTransport,
    user_id: uuid.UUID = BOOTSTRAP_USER_ID,
):
    return build_google_explicit_link_intake_service(
        session=db_session,
        user_id=user_id,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        google_transport=transport,
    )


def _embed_jobs_for_object(db_session, object_id: uuid.UUID) -> list[Job]:
    return [
        job
        for job in db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)).all()
        if (job.payload or {}).get("object_id") == str(object_id)
    ]


def _extract_jobs_for_object(db_session, object_id: uuid.UUID) -> list[Job]:
    return [
        job
        for job in db_session.scalars(
            select(Job).where(Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT)
        ).all()
        if (job.payload or {}).get("object_id") == str(object_id)
    ]


def test_valid_drive_file_url_creates_one_object(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    file_id = "drive-file-1"
    transport = FakeDriveTransport({file_id: _drive_file(file_id, "Quarterly report")})
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)

    result = service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )
    service.close()

    assert result.provider == GOOGLE_DRIVE_PROVIDER
    assert result.kind == "file"
    assert result.status == "created"

    obj = db_session.get(Object, result.object_id)
    assert obj is not None
    assert obj.external_id == file_id
    assert obj.title == "Quarterly report"
    assert obj.canonical_uri == build_canonical_uri(file_id)
    assert obj.metadata_["account_id"] == str(account.id)
    assert obj.metadata_["file_id"] == file_id
    assert obj.metadata_["intake_mode"] == "explicit_link"
    assert "unittest-google-access" not in json.dumps(obj.metadata_)
    assert "unittest-google-refresh" not in json.dumps(obj.metadata_)

    count = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == GOOGLE_DRIVE_PROVIDER,
            Object.external_id == file_id,
        )
    )
    assert count == 1
    assert result.content_status == "pending"
    assert result.content_jobs_enqueued == 1
    assert len(_extract_jobs_for_object(db_session, obj.id)) == 1


def test_valid_drive_folder_url_creates_folder_object(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    folder_id = "folder-abc"
    transport = FakeDriveTransport(
        {
            folder_id: _drive_file(
                folder_id,
                "Project docs",
                mime_type=GOOGLE_DRIVE_FOLDER_MIME,
            )
        }
    )
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)

    result = service.intake_link(
        url=f"https://drive.google.com/drive/folders/{folder_id}",
        account_id=account.id,
    )
    service.close()

    assert result.kind == "folder"
    obj = db_session.get(Object, result.object_id)
    assert obj is not None
    assert obj.kind == "folder"


def test_docs_document_url_extracts_file_id(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    file_id = "doc-id-123"
    transport = FakeDriveTransport({file_id: _drive_file(file_id, "Meeting notes", mime_type="application/vnd.google-apps.document")})
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)

    result = service.intake_link(
        url=f"https://docs.google.com/document/d/{file_id}/edit",
        account_id=account.id,
    )
    service.close()

    assert transport.calls == [("get_file_metadata", file_id)]
    assert result.status == "created"
    obj = db_session.get(Object, result.object_id)
    assert obj is not None
    assert obj.external_id == file_id


def test_spreadsheet_url_extracts_file_id(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    file_id = "sheet-id-456"
    transport = FakeDriveTransport(
        {file_id: _drive_file(file_id, "Budget", mime_type="application/vnd.google-apps.spreadsheet")}
    )
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)

    result = service.intake_link(
        url=f"https://docs.google.com/spreadsheets/d/{file_id}/edit#gid=0",
        account_id=account.id,
    )
    service.close()

    assert transport.calls == [("get_file_metadata", file_id)]
    obj = db_session.get(Object, result.object_id)
    assert obj is not None
    assert obj.external_id == file_id


def test_unsupported_host_rejected_before_network(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    transport = FakeDriveTransport()
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)

    with pytest.raises(Exception, match="unsupported link url"):
        service.intake_link(url="https://evil.example/file/d/abc", account_id=None)
    service.close()
    assert transport.calls == []


def test_malformed_url_rejected_before_network(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    transport = FakeDriveTransport()
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)

    with pytest.raises(Exception, match="unsupported link url|invalid link url"):
        service.intake_link(url="https://drive.google.com/file/d/", account_id=None)
    service.close()
    assert transport.calls == []


def test_account_without_drive_scope_skips_drive_api(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    account = _google_account(db_session, credential_key, [GMAIL_READONLY_SCOPE])
    transport = FakeDriveTransport({"abc": _drive_file("abc", "ignored")})
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)

    with pytest.raises(Exception, match="google drive scope not granted"):
        service.intake_link(
            url="https://drive.google.com/file/d/abc/view",
            account_id=account.id,
        )
    service.close()
    assert transport.calls == []


def test_cross_user_account_id_rejected(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    other_user = uuid.uuid4()
    db_session.add(User(id=other_user, display_name="other"))
    db_session.flush()
    other_account = _google_account(
        db_session,
        credential_key,
        [DRIVE_READONLY_SCOPE],
        email="other@example.com",
        user_id=other_user,
    )
    transport = FakeDriveTransport({"abc": _drive_file("abc", "secret")})
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)

    with pytest.raises(Exception, match="google account not found"):
        service.intake_link(
            url="https://drive.google.com/file/d/abc/view",
            account_id=other_account.id,
        )
    service.close()
    assert transport.calls == []


def test_multiple_eligible_accounts_require_selection(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    _google_account(
        db_session,
        credential_key,
        [DRIVE_READONLY_SCOPE],
        email="first@example.com",
    )
    _google_account(
        db_session,
        credential_key,
        [DRIVE_READONLY_SCOPE],
        email="second@example.com",
    )
    transport = FakeDriveTransport({"abc": _drive_file("abc", "doc")})
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)

    with pytest.raises(Exception, match="google account selection required"):
        service.intake_link(url="https://drive.google.com/file/d/abc/view")
    service.close()
    assert transport.calls == []


def test_repeated_same_link_returns_same_object(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    file_id = "repeat-file"
    transport = FakeDriveTransport({file_id: _drive_file(file_id, "Stable title")})
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)

    first = service.intake_link(
        url=f"https://drive.google.com/open?id={file_id}",
        account_id=account.id,
    )
    second = service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )
    service.close()

    assert second.object_id == first.object_id
    assert second.status == "unchanged"
    count = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == GOOGLE_DRIVE_PROVIDER,
            Object.external_id == file_id,
        )
    )
    assert count == 1
    assert len(_extract_jobs_for_object(db_session, first.object_id)) == 1


def test_metadata_update_same_object_no_extra_embed(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    file_id = "meta-file"
    transport = FakeDriveTransport({file_id: _drive_file(file_id, "Title unchanged")})
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)
    first = service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )

    transport._files[file_id] = _drive_file(
        file_id,
        "Title unchanged",
        size="9999",
        modifiedTime="2024-03-01T00:00:00.000Z",
    )
    second = service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )
    service.close()

    assert second.object_id == first.object_id
    assert second.status == "updated"
    obj = db_session.get(Object, first.object_id)
    assert obj is not None
    assert obj.metadata_["size"] == 9999
    assert len(_extract_jobs_for_object(db_session, first.object_id)) == 1


def test_title_update_same_object_reuses_embed_behavior(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    file_id = "title-file"
    transport = FakeDriveTransport({file_id: _drive_file(file_id, "Old title")})
    service = _intake_service(db_session, credential_key, oauth_client_file, transport)
    first = service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )
    first_jobs = _extract_jobs_for_object(db_session, first.object_id)
    assert len(first_jobs) == 1
    first_jobs[0].status = "done"
    db_session.flush()

    transport._files[file_id] = _drive_file(file_id, "New title")
    second = service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )
    service.close()

    assert second.object_id == first.object_id
    assert second.status == "updated"
    obj = db_session.get(Object, first.object_id)
    assert obj is not None
    assert obj.title == "New title"
    assert len(_extract_jobs_for_object(db_session, first.object_id)) == 1


def test_malicious_web_view_link_never_controls_open_target(db_session, credential_key) -> None:
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    file_id = "open-target-file"
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        provider=GOOGLE_DRIVE_PROVIDER,
        external_id=file_id,
        origin="source",
        state="observed",
        title="Doc",
        canonical_uri="https://evil.example/malicious",
        metadata_={
            "account_id": str(account.id),
            "file_id": file_id,
            "web_view_link": "https://evil.example/phish",
        },
    )
    db_session.add(obj)
    db_session.flush()

    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available is True
    assert target.url == build_canonical_uri(file_id)
    assert "evil.example" not in (target.url or "")


def test_malicious_canonical_uri_never_controls_open_target(db_session, credential_key) -> None:
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    file_id = "canonical-file"
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        provider=GOOGLE_DRIVE_PROVIDER,
        external_id=file_id,
        origin="source",
        state="observed",
        title="Doc",
        canonical_uri="javascript:alert(1)",
        metadata_={
            "account_id": str(account.id),
            "file_id": file_id,
        },
    )
    db_session.add(obj)
    db_session.flush()

    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available is True
    assert target.url == build_canonical_uri(file_id)


def test_external_id_mismatch_makes_open_target_unavailable(db_session, credential_key) -> None:
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        provider=GOOGLE_DRIVE_PROVIDER,
        external_id="real-id",
        origin="source",
        state="observed",
        title="Doc",
        canonical_uri=build_canonical_uri("real-id"),
        metadata_={
            "account_id": str(account.id),
            "file_id": "tampered-id",
        },
    )
    db_session.add(obj)
    db_session.flush()

    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available is False
    assert target.reason == "google_drive_metadata_tampered"


def test_drive_transport_exact_lookup_only() -> None:
    transport = DriveTransport()
    assert hasattr(transport, "get_file_metadata")
    assert not hasattr(transport, "list_files")
    assert not hasattr(transport, "list_changes")
    assert not hasattr(transport, "get_start_page_token")
    transport.close()


def test_exact_provider_request_only_httpx(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    file_id = "http-file"
    requested_urls: list[str] = []

    requested_params: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(request.url.path)
        requested_params.append(dict(request.url.params))
        return httpx.Response(
            200,
            json=_drive_file(file_id, "HTTP doc"),
        )

    transport = DriveTransport(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    service = build_explicit_link_intake_service(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        google_transport=transport,
        yandex_transport=FakeYandexDiskTransport(),
        http_client=transport._http,
    )
    service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )
    service.close()

    assert requested_urls == [f"/drive/v3/files/{file_id}"]
    assert all("changes" not in url for url in requested_urls)
    assert all("startPageToken" not in url for url in requested_urls)
    assert len(requested_params) == 1
    assert requested_params[0].get("supportsAllDrives") == "true"
    assert "fields" in requested_params[0]


def test_tokens_absent_from_object_and_errors(
    db_session, credential_key, oauth_client_file, google_settings, auth_client
) -> None:
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    file_id = "token-check"
    transport = FakeDriveTransport({file_id: _drive_file(file_id, "Safe")})

    with patch(
        "app.api.intake.build_google_explicit_link_intake_service",
        return_value=_intake_service(db_session, credential_key, oauth_client_file, transport),
    ):
        response = auth_client.post(
            "/intake/link",
            json={
                "url": f"https://drive.google.com/file/d/{file_id}/view",
                "account_id": str(account.id),
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert "unittest-google-access" not in json.dumps(body).lower()
    assert "unittest-google-refresh" not in json.dumps(body).lower()

    obj = db_session.get(Object, uuid.UUID(body["object_id"]))
    assert obj is not None
    dumped = json.dumps(obj.metadata_)
    assert "unittest-google-access" not in dumped
    assert "unittest-google-refresh" not in dumped


def test_drive_available_in_connection_snapshot(
    db_session, credential_key, google_settings
) -> None:
    _google_account(db_session, credential_key, [GMAIL_READONLY_SCOPE, DRIVE_READONLY_SCOPE])
    snapshot = ConnectionStatusService(db_session, BOOTSTRAP_USER_ID).snapshot()
    assert snapshot.google.drive_available is True


def test_parse_google_drive_file_id_presentation_url() -> None:
    file_id = "pres-id"
    assert parse_google_drive_file_id(
        f"https://docs.google.com/presentation/d/{file_id}/edit"
    ) == file_id


def test_intake_link_api_endpoint(auth_client, db_session, credential_key, oauth_client_file, google_settings) -> None:
    account = _google_account(db_session, credential_key, [DRIVE_READONLY_SCOPE])
    file_id = "api-file"
    transport = FakeDriveTransport({file_id: _drive_file(file_id, "API doc")})

    with patch(
        "app.api.intake.build_google_explicit_link_intake_service",
        return_value=_intake_service(db_session, credential_key, oauth_client_file, transport),
    ):
        response = auth_client.post(
            "/intake/link",
            json={
                "url": f"https://drive.google.com/file/d/{file_id}/view",
                "account_id": str(account.id),
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == GOOGLE_DRIVE_PROVIDER
    assert payload["kind"] == "file"
    assert payload["status"] == "created"
    assert payload["object_id"]
