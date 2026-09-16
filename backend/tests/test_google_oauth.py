import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db
from app.connectors.google.constants import (
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_READONLY_SCOPE,
    DRIVE_READONLY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
    GOOGLE_OAUTH_SCOPES,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleConfigurationError
from app.connectors.google.gmail_normalize import normalize_gmail_message
from app.connectors.google.gmail_sync import build_gmail_sync_service
from app.connectors.google.gmail_transport import GmailTransport
from app.connectors.google.oauth_config import load_oauth_client_config
from app.connectors.google.oauth_service import GoogleOAuthService
from app.connectors.google.oauth_state import OAuthStateService, hash_oauth_state
from app.core.config import settings
from app.db.models import GoogleAccount, Job, OAuthState, Object
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.embedding_text import build_embedding_text
from app.main import app
from app.mcp.server import MCP_TOOL_NAMES
from app.services.context_service import ContextService
from app.users.bootstrap import BOOTSTRAP_USER_ID

REPO_ROOT = Path(__file__).resolve().parents[2]


def utcnow() -> datetime:
    return datetime.now(UTC)


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
    monkeypatch.setattr(settings, "google_oauth_client_file", oauth_client_file)
    monkeypatch.setattr(
        settings,
        "google_redirect_uri",
        "http://localhost:18080/auth/google/callback",
    )
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)


@pytest.fixture
def client(db_session, auth_headers):
    from tests.conftest import AuthTestClient

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


class FakeHttpClient:
    def __init__(self, handlers: dict) -> None:
        self._handlers = handlers
        self.calls: list[tuple] = []

    def post(self, url: str, data: dict | None = None, **kwargs) -> httpx.Response:
        self.calls.append(("POST", url, data))
        handler = self._handlers.get(("POST", url))
        if handler is None:
            raise AssertionError(f"unexpected POST {url}")
        return handler(data)

    def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        **kwargs,
    ) -> httpx.Response:
        self.calls.append(("GET", url, params, headers))
        handler = self._handlers.get(("GET", url))
        if handler is None:
            raise AssertionError(f"unexpected GET {url}")
        return handler(params, headers)


def test_google_oauth_secret_json_ignored_by_git() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-v", "secrets/google-oauth-client.json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "secrets/" in result.stdout


def test_load_valid_web_oauth_json(oauth_client_file: str) -> None:
    config = load_oauth_client_config(oauth_client_file)
    assert config["client_id"] == "test-client-id"
    assert config["client_secret"] == "test-client-secret"


def test_missing_oauth_json_raises_configuration_error(tmp_path: Path) -> None:
    missing = str(tmp_path / "missing.json")
    with pytest.raises(GoogleConfigurationError, match="missing"):
        load_oauth_client_config(missing)


def test_malformed_oauth_json_raises_configuration_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    with pytest.raises(GoogleConfigurationError, match="malformed"):
        load_oauth_client_config(str(bad))


def test_oauth_start_redirects_with_state_scope_and_redirect(
    client,
    google_settings,
) -> None:
    response = client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert "accounts.google.com" in location
    params = parse_qs(urlparse(location).query)
    assert params["scope"] == [" ".join(GOOGLE_OAUTH_SCOPES)]
    assert params["redirect_uri"] == ["http://localhost:18080/auth/google/callback"]
    assert params["access_type"] == ["offline"]
    assert params["state"]


def test_oauth_callback_rejects_invalid_state(client, google_settings) -> None:
    response = client.get(
        "/auth/google/callback",
        params={"code": "dummy-code", "state": "invalid-state"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid oauth state"


def test_oauth_callback_rejects_reused_state(client, db_session, google_settings) -> None:
    state_service = OAuthStateService(db_session)
    state = state_service.create_state(BOOTSTRAP_USER_ID)
    db_session.flush()
    state_service.consume_state(state)
    db_session.flush()

    response = client.get(
        "/auth/google/callback",
        params={"code": "dummy-code", "state": state},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "oauth state already used"


def test_oauth_callback_missing_scope_uses_canonical_oauth_scopes(
    client,
    db_session,
    google_settings,
    oauth_client_file: str,
):
    state_service = OAuthStateService(db_session)
    state = state_service.create_state(BOOTSTRAP_USER_ID)
    db_session.flush()
    fake_http = FakeHttpClient(
        {
            ("POST", "https://oauth2.googleapis.com/token"): lambda data: httpx.Response(
                200,
                json={
                    "access_token": "callback-access",
                    "refresh_token": "callback-refresh",
                    "expires_in": 3600,
                },
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile"): lambda params, headers: httpx.Response(
                200,
                json={"emailAddress": "scope-fallback@example.com"},
            ),
        }
    )
    oauth_service = GoogleOAuthService(
        oauth_client_file,
        "http://localhost:18080/auth/google/callback",
        http_client=fake_http,
    )
    from unittest.mock import patch

    with patch("app.api.google._google_oauth_service", return_value=oauth_service), patch(
        "app.api.google.GmailTransport",
        return_value=GmailTransport(http_client=fake_http),
    ):
        response = client.get(
            "/auth/google/callback",
            params={"code": "auth-code", "state": state},
        )
    assert response.status_code == 200
    body = response.json()
    assert CALENDAR_EVENTS_SCOPE in body["scopes"]
    assert GMAIL_READONLY_SCOPE in body["scopes"]
    assert CALENDAR_READONLY_SCOPE in body["scopes"]
    assert DRIVE_READONLY_SCOPE in body["scopes"]
    assert set(body["scopes"]) == set(GOOGLE_OAUTH_SCOPES)


def test_encrypted_token_storage_roundtrip(db_session, credential_key: str) -> None:
    encryption = CredentialEncryption(credential_key)
    store = GoogleAccountStore(db_session, encryption)
    account = store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-1",
        refresh_token="refresh-1",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    loaded = db_session.get(GoogleAccount, account.id)
    assert loaded is not None
    assert loaded.access_token_encrypted != "access-1"
    assert loaded.refresh_token_encrypted != "refresh-1"
    assert store.get_access_token(loaded) == "access-1"
    assert store.get_refresh_token(loaded) == "refresh-1"


def test_refresh_token_preserved_when_not_returned(db_session, credential_key: str) -> None:
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-old",
        refresh_token="refresh-keep",
        token_expiry=utcnow() - timedelta(minutes=5),
    )
    db_session.commit()

    store.update_tokens_from_refresh(
        account,
        access_token="access-new",
        refresh_token=None,
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    assert store.get_access_token(account) == "access-new"
    assert store.get_refresh_token(account) == "refresh-keep"


def _sample_gmail_message(message_id: str, subject: str = "Hello") -> dict:
    fixed_ms = 1724846400000  # fixed instant for stable normalization
    return {
        "id": message_id,
        "threadId": "thread-1",
        "labelIds": ["INBOX"],
        "internalDate": str(fixed_ms),
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "user@example.com"},
                {"name": "Message-ID", "value": f"<{message_id}@gmail.com>"},
            ],
            "body": {
                "data": "SGVsbG8gd29ybGQ=",
            },
        },
    }


def test_bounded_gmail_sync_creates_observed_email_objects(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    message_ids = [f"msg-{i}" for i in range(3)]
    fake_http = FakeHttpClient(
        {
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): lambda params, headers: httpx.Response(
                200,
                json={"messages": [{"id": mid} for mid in message_ids]},
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-0"): lambda params, headers: httpx.Response(
                200, json=_sample_gmail_message("msg-0", "First")
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-1"): lambda params, headers: httpx.Response(
                200, json=_sample_gmail_message("msg-1", "Second")
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-2"): lambda params, headers: httpx.Response(
                200, json=_sample_gmail_message("msg-2", "Third")
            ),
        }
    )

    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=3)

    assert result["synchronized"] == 3
    assert result["created"] == 3
    assert result["updated"] == 0
    assert result["jobs_enqueued"] == 3

    objects = list(
        db_session.scalars(
            select(Object).where(
                Object.provider == "gmail",
                Object.kind == "email",
                Object.external_id.in_(message_ids),
            )
        )
    )
    assert len(objects) == 3
    for obj in objects:
        assert obj.origin == "source"
        assert obj.state == "observed"
        assert obj.external_id is not None
        assert obj.body == "Hello world"
        assert "body_text" not in obj.metadata_


def test_gmail_body_stored_in_object_body(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    fake_http = FakeHttpClient(
        {
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): lambda params, headers: httpx.Response(
                200,
                json={"messages": [{"id": "msg-body"}]},
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-body"): lambda params, headers: httpx.Response(
                200, json=_sample_gmail_message("msg-body", "Body test")
            ),
        }
    )
    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)

    obj = db_session.scalar(
        select(Object).where(Object.external_id == "msg-body", Object.provider == "gmail")
    )
    assert obj is not None
    assert obj.body == "Hello world"


def test_embedding_text_includes_gmail_body(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    fake_http = FakeHttpClient(
        {
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): lambda params, headers: httpx.Response(
                200,
                json={"messages": [{"id": "msg-embed"}]},
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-embed"): lambda params, headers: httpx.Response(
                200, json=_sample_gmail_message("msg-embed", "Embed subject")
            ),
        }
    )
    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)

    obj = db_session.scalar(
        select(Object).where(Object.external_id == "msg-embed", Object.provider == "gmail")
    )
    assert obj is not None
    embedding_text = build_embedding_text(obj)
    assert "Hello world" in embedding_text


def test_context_service_includes_gmail_body(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    fake_http = FakeHttpClient(
        {
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): lambda params, headers: httpx.Response(
                200,
                json={"messages": [{"id": "msg-ctx"}]},
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-ctx"): lambda params, headers: httpx.Response(
                200, json=_sample_gmail_message("msg-ctx", "Context subject")
            ),
        }
    )
    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)

    obj = db_session.scalar(
        select(Object).where(Object.external_id == "msg-ctx", Object.provider == "gmail")
    )
    assert obj is not None

    context = ContextService(db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService()).build_context(object_id=obj.id)
    target_items = [item for item in context.items if item.object_id == obj.id]
    assert len(target_items) == 1
    assert "Hello world" in target_items[0].content


def test_second_sync_skips_get_for_known_message_without_duplicate_object_or_job(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    get_calls: list[str] = []

    def get_message(params, headers):
        get_calls.append("get")
        return httpx.Response(200, json=_sample_gmail_message("msg-change", "Same subject"))

    fake_http = FakeHttpClient(
        {
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): lambda params, headers: httpx.Response(
                200,
                json={"messages": [{"id": "msg-change"}]},
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-change"): get_message,
        }
    )
    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    first = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    assert first["created"] == 1
    assert first["jobs_enqueued"] == 1
    assert get_calls == ["get"]

    second = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    assert second["created"] == 0
    assert second["updated"] == 0
    assert second["unchanged"] == 1
    assert second["jobs_enqueued"] == 0
    assert get_calls == ["get"]

    obj = db_session.scalar(
        select(Object).where(Object.external_id == "msg-change", Object.provider == "gmail")
    )
    assert obj is not None
    assert obj.body == "Hello world"


def test_gmail_resync_is_idempotent_without_duplicate_jobs(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    fake_http = FakeHttpClient(
        {
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): lambda params, headers: httpx.Response(
                200,
                json={"messages": [{"id": "msg-1"}]},
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-1"): lambda params, headers: httpx.Response(
                200, json=_sample_gmail_message("msg-1")
            ),
        }
    )

    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    first = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    second = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["updated"] == 0
    assert second["unchanged"] == 1
    assert second["jobs_enqueued"] == 0

    count = db_session.scalar(
        select(Object).where(
            Object.provider == "gmail",
            Object.kind == "email",
            Object.external_id == "msg-1",
        )
    )
    assert count is not None


def test_gmail_normalization_keeps_headers_and_skips_raw_mime() -> None:
    message = _sample_gmail_message("msg-headers")
    message["payload"]["parts"] = [
        {
            "mimeType": "text/html",
            "body": {"data": "PGI+SGVsbG88L2I+"},
        }
    ]
    message["payload"]["body"] = {}
    normalized = normalize_gmail_message(message)
    metadata = normalized["metadata"]
    assert metadata["sender"] == "sender@example.com"
    assert metadata["recipients"] == ["user@example.com"]
    assert "message-id" in metadata["headers"]
    assert normalized["body"] == "Hello"
    assert "body_text" not in metadata
    assert "SGVsbG8" not in json.dumps(metadata)
    assert "PGI+" not in json.dumps(metadata)


def test_nested_multipart_extracts_plain_text() -> None:
    message = {
        "id": "nested-1",
        "threadId": "thread-nested",
        "labelIds": ["INBOX"],
        "internalDate": "1724846400000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "Nested"}],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": "SGVsbG8gZnJvbSBuZXN0ZWQ="},
                        }
                    ],
                }
            ],
        },
    }
    normalized = normalize_gmail_message(message)
    assert normalized["body"] == "Hello from nested"


def test_embedding_jobs_use_object_reference_only(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    fake_http = FakeHttpClient(
        {
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): lambda params, headers: httpx.Response(
                200,
                json={"messages": [{"id": "msg-job"}]},
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-job"): lambda params, headers: httpx.Response(
                200, json=_sample_gmail_message("msg-job", "Job test")
            ),
        }
    )

    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    sync_result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    assert sync_result["jobs_enqueued"] == 1

    email_object = db_session.scalar(
        select(Object).where(Object.external_id == "msg-job", Object.provider == "gmail")
    )
    assert email_object is not None

    jobs = [
        job
        for job in db_session.scalars(
            select(Job).where(Job.type == "embed_object", Job.user_id == BOOTSTRAP_USER_ID)
        )
        if job.payload.get("object_id") == str(email_object.id)
    ]
    assert len(jobs) == 1
    payload = jobs[0].payload
    assert set(payload.keys()) == {"object_id"}
    assert "body" not in payload
    assert "subject" not in payload


def test_google_api_errors_are_controlled(db_session, credential_key: str) -> None:
    transport = GmailTransport(
        http_client=FakeHttpClient(
            {
                ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): lambda params, headers: httpx.Response(
                    403,
                    json={"error": {"message": "denied", "status": "PERMISSION_DENIED"}},
                ),
            }
        )
    )
    from app.connectors.google.errors import GoogleApiError

    with pytest.raises(GoogleApiError, match="failed to list gmail messages"):
        transport.list_message_ids("token", "me", "after:2026/01/01", 10)


def test_no_db_transaction_held_during_fake_network_wait(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    tx_during_network: list[bool] = []

    def list_handler(params, headers):
        tx_during_network.append(db_session.in_transaction())
        return httpx.Response(200, json={"messages": [{"id": "msg-tx"}]})

    def get_handler(params, headers):
        tx_during_network.append(db_session.in_transaction())
        return httpx.Response(200, json=_sample_gmail_message("msg-tx"))

    fake_http = FakeHttpClient(
        {
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): list_handler,
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-tx"): get_handler,
        }
    )

    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    assert tx_during_network == [False, False]


def test_no_gmail_send_or_unapproved_calendar_mcp_tools() -> None:
    forbidden = {
        "sync_gmail",
        "gmail_sync",
        "search_calendar",
        "propose_calendar_event",
    }
    assert not MCP_TOOL_NAMES.intersection(forbidden)
    assert "create_calendar_event" in MCP_TOOL_NAMES
    assert "send_email" in MCP_TOOL_NAMES


def test_oauth_token_refresh_on_expired_access_token(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-old",
        refresh_token="refresh-keep",
        token_expiry=utcnow() - timedelta(minutes=10),
    )
    db_session.commit()

    tx_during_refresh: list[bool] = []

    def refresh_handler(data):
        tx_during_refresh.append(db_session.in_transaction())
        return httpx.Response(
            200,
            json={"access_token": "access-refreshed", "expires_in": 3600},
        )

    fake_http = FakeHttpClient(
        {
            ("POST", "https://oauth2.googleapis.com/token"): refresh_handler,
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): lambda params, headers: httpx.Response(
                200,
                json={"messages": []},
            ),
        }
    )

    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)

    assert tx_during_refresh == [False]
    assert account_store.get_access_token(account) == "access-refreshed"
    assert account_store.get_refresh_token(account) == "refresh-keep"


def test_oauth_exchange_and_callback_success(
    client,
    db_session,
    google_settings,
    oauth_client_file: str,
) -> None:
    state_service = OAuthStateService(db_session)
    state = state_service.create_state(BOOTSTRAP_USER_ID)
    db_session.flush()

    fake_http = FakeHttpClient(
        {
            ("POST", "https://oauth2.googleapis.com/token"): lambda data: httpx.Response(
                200,
                json={
                    "access_token": "callback-access",
                    "refresh_token": "callback-refresh",
                    "expires_in": 3600,
                },
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile"): lambda params, headers: httpx.Response(
                200,
                json={"emailAddress": "connected@example.com"},
            ),
        }
    )

    oauth_service = GoogleOAuthService(
        oauth_client_file,
        "http://localhost:18080/auth/google/callback",
        http_client=fake_http,
    )
    from unittest.mock import patch

    with patch("app.api.google._google_oauth_service", return_value=oauth_service), patch(
        "app.api.google.GmailTransport",
        return_value=GmailTransport(http_client=fake_http),
    ):
        response = client.get(
            "/auth/google/callback",
            params={"code": "auth-code", "state": state},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "connected"
    assert body["email"] == "connected@example.com"
    assert "access_token" not in body
    assert "refresh_token" not in body

    account = db_session.scalar(
        select(GoogleAccount).where(GoogleAccount.email == "connected@example.com")
    )
    assert account is not None
    assert account.access_token_encrypted is not None


def test_bounded_sync_respects_max_limit(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    requested_max = []

    def list_handler(params, headers):
        requested_max.append(params["maxResults"])
        return httpx.Response(200, json={"messages": []})

    fake_http = FakeHttpClient(
        {
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): list_handler,
        }
    )

    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=150)
    assert requested_max == [100]


def test_authorization_url_requires_authentication(db_session) -> None:

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        response = test_client.post("/auth/google/authorization-url")
    app.dependency_overrides.clear()
    assert response.status_code == 401


def test_authorization_url_returns_google_url_with_required_scopes(
    client,
    db_session,
    google_settings,
) -> None:
    response = client.post("/auth/google/authorization-url")
    assert response.status_code == 200
    body = response.json()
    assert "authorization_url" in body
    assert "access_token" not in body
    assert "refresh_token" not in body

    location = body["authorization_url"]
    assert "accounts.google.com" in location
    params = parse_qs(urlparse(location).query)
    scope = params["scope"][0]
    assert GMAIL_READONLY_SCOPE in scope
    assert GMAIL_SEND_SCOPE in scope
    assert CALENDAR_READONLY_SCOPE in scope
    assert CALENDAR_EVENTS_SCOPE in scope
    assert DRIVE_READONLY_SCOPE in scope
    assert params["redirect_uri"] == ["http://localhost:18080/auth/google/callback"]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["state"]

    state_row = db_session.scalar(
        select(OAuthState).where(OAuthState.state_hash == hash_oauth_state(params["state"][0]))
    )
    assert state_row is not None
    assert state_row.user_id == BOOTSTRAP_USER_ID


def test_oauth_callback_upgrades_existing_account_with_drive_scope(
    client,
    db_session,
    google_settings,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    existing = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE, CALENDAR_READONLY_SCOPE],
        access_token="access-old",
        refresh_token="refresh-keep",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()
    existing_id = existing.id

    state_service = OAuthStateService(db_session)
    state = state_service.create_state(BOOTSTRAP_USER_ID)
    db_session.flush()

    granted_scope = " ".join(GOOGLE_OAUTH_SCOPES)
    fake_http = FakeHttpClient(
        {
            ("POST", "https://oauth2.googleapis.com/token"): lambda data: httpx.Response(
                200,
                json={
                    "access_token": "callback-access",
                    "expires_in": 3600,
                    "scope": granted_scope,
                },
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile"): lambda params, headers: httpx.Response(
                200,
                json={"emailAddress": "user@example.com"},
            ),
        }
    )

    oauth_service = GoogleOAuthService(
        oauth_client_file,
        "http://localhost:18080/auth/google/callback",
        http_client=fake_http,
    )
    from unittest.mock import patch

    with patch("app.api.google._google_oauth_service", return_value=oauth_service), patch(
        "app.api.google.GmailTransport",
        return_value=GmailTransport(http_client=fake_http),
    ):
        response = client.get(
            "/auth/google/callback",
            params={"code": "auth-code", "state": state},
        )

    assert response.status_code == 200
    accounts = list(
        db_session.scalars(
            select(GoogleAccount).where(
                GoogleAccount.user_id == BOOTSTRAP_USER_ID,
                GoogleAccount.email == "user@example.com",
            )
        )
    )
    assert len(accounts) == 1
    upgraded = accounts[0]
    assert upgraded.id == existing_id
    assert DRIVE_READONLY_SCOPE in upgraded.scopes
    assert account_store.get_access_token(upgraded) == "callback-access"
    assert account_store.get_refresh_token(upgraded) == "refresh-keep"
