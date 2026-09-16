"""PHASE 28C-B2-B1 — Gmail bounded history runtime."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.deps import get_db
from app.connectors.google.constants import (
    GMAIL_READONLY_SCOPE,
    build_gmail_list_query,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.gmail_history_state import (
    format_stored_date,
    get_history_backfill,
    plan_history_active_window,
    utc_today,
)
from app.connectors.google.gmail_sync import build_gmail_sync_service
from app.connectors.google.gmail_transport import GmailMessagePage, GmailTransport
from app.core.config import settings
from app.db.engine import engine
from app.db.models import GoogleAccount, Job, Object, User, UserSourcePreference
from app.jobs.constants import JOB_TYPE_SYNC_GOOGLE_GMAIL
from app.jobs.handlers import HANDLERS
from app.jobs.worker import process_one_job
from app.main import app
from app.services.source_sync_preference_service import SourceSyncPreferenceService
from app.source_sync.constants import SOURCE_GMAIL
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_phase_27a import _persist_gmail_schedule


def utcnow() -> datetime:
    return datetime.now(UTC)


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


def _sample_gmail_message(message_id: str, subject: str = "Hello") -> dict:
    fixed_ms = 1724846400000
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
            "body": {"data": "SGVsbG8gd29ybGQ="},
        },
    }


@pytest.fixture(autouse=True)
def cleanup_tables() -> None:
    conn = engine.connect()
    trans = conn.begin()
    session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    session.execute(delete(Job))
    session.execute(delete(Object))
    session.execute(delete(UserSourcePreference))
    session.execute(delete(GoogleAccount))
    trans.commit()
    conn.close()
    yield


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


def _upsert_google_account(
    db_session,
    credential_key: str,
    *,
    gmail_sync_state: dict | None = None,
) -> GoogleAccount:
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    if gmail_sync_state is not None:
        account.gmail_sync_state = gmail_sync_state
        account.calendar_sync_state = {"calendar_marker": True}
    db_session.flush()
    return account


def test_google_account_model_has_independent_sync_state_columns(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_google_account(db_session, credential_key)
    assert account.gmail_sync_state == {}
    assert account.calendar_sync_state == {}

    account.gmail_sync_state = {"history_backfill": {"version": 1}}
    account.calendar_sync_state = {"reserved": True}
    db_session.flush()
    db_session.expire(account)
    stored = db_session.get(GoogleAccount, account.id)
    assert stored.gmail_sync_state["history_backfill"]["version"] == 1
    assert stored.calendar_sync_state == {"reserved": True}


def test_oauth_upsert_preserves_gmail_sync_state(
    db_session,
    credential_key: str,
) -> None:
    state = {
        "history_backfill": {
            "version": 1,
            "scanned_start": "2026-01-01",
            "scanned_end": "2026-06-01",
        }
    }
    account = _upsert_google_account(db_session, credential_key, gmail_sync_state=state)
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email=account.email,
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="new-access",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=2),
    )
    db_session.flush()
    refreshed = db_session.get(GoogleAccount, account.id)
    assert refreshed.gmail_sync_state == state


def test_gmail_transport_pagination_parses_token_and_passes_page_token() -> None:
    calls: list[dict] = []

    def list_handler(params, headers):
        calls.append(dict(params))
        if params.get("pageToken") == "token-a":
            return httpx.Response(
                200,
                json={"messages": [{"id": "msg-2"}], "nextPageToken": "token-b"},
            )
        return httpx.Response(
            200,
            json={"messages": [{"id": "msg-1"}], "nextPageToken": "token-a"},
        )

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
    page1 = transport.list_message_ids_page("token", "me", "after:2026/01/01", 10)
    assert page1.message_ids == ["msg-1"]
    assert page1.next_page_token == "token-a"
    assert "pageToken" not in calls[0]

    page2 = transport.list_message_ids_page(
        "token", "me", "after:2026/01/01", 10, page_token="token-a"
    )
    assert page2.message_ids == ["msg-2"]
    assert page2.next_page_token == "token-b"
    assert calls[1]["pageToken"] == "token-a"


def test_bounded_gmail_query_includes_after_before_and_exclusions() -> None:
    query = build_gmail_list_query("2026/01/01", "2026/06/01")
    assert "after:2026/01/01" in query
    assert "before:2026/06/01" in query
    assert "-in:spam" in query
    assert "-category:promotions" in query


def test_effective_history_days_per_user_for_live_query(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    monkeypatch.setattr(settings, "gmail_sync_days", 30)
    account = _upsert_google_account(db_session, credential_key)
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_GMAIL,
        history_days=7,
        history_days_specified=True,
    )

    captured_queries: list[str] = []

    def list_handler(params, headers):
        captured_queries.append(str(params.get("q")))
        return httpx.Response(200, json={"messages": []})

    fake_http = FakeHttpClient(
        {
            (
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            ): list_handler,
        }
    )
    service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=7,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    service.sync_account(account.id, BOOTSTRAP_USER_ID)
    assert captured_queries
    after_part = captured_queries[0].split()[0]
    expected_after = (utcnow() - timedelta(days=7)).strftime("%Y/%m/%d")
    assert after_part == f"after:{expected_after}"

    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="B"))
    db_session.flush()
    account_b = GoogleAccountStore(db_session, CredentialEncryption(credential_key)).upsert_tokens(
        user_id=user_b_id,
        email="b@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    captured_queries.clear()
    service_b = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=settings.gmail_sync_days,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    service_b.sync_account(account_b.id, user_b_id)
    expected_default_after = (utcnow() - timedelta(days=30)).strftime("%Y/%m/%d")
    assert captured_queries[0].startswith(f"after:{expected_default_after}")


def test_live_pass_runs_before_history_when_backfill_active(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    today = utc_today()
    active_state = {
        "history_backfill": {
            "version": 1,
            "active_start": format_stored_date(today - timedelta(days=30)),
            "active_end": format_stored_date(today),
            "next_page_token": "page-a",
        }
    }
    account = _upsert_google_account(
        db_session, credential_key, gmail_sync_state=active_state
    )
    call_queries: list[str] = []

    def list_handler(params, headers):
        call_queries.append(str(params.get("q")))
        if "before:" in str(params.get("q")):
            return httpx.Response(
                200,
                json={"messages": [{"id": "hist-1"}], "nextPageToken": "page-b"},
            )
        return httpx.Response(200, json={"messages": [{"id": "live-1"}]})

    def get_handler(params, headers):
        url_suffix = params if isinstance(params, str) else ""
        message_id = url_suffix or "live-1"
        if "hist-1" in str(message_id) or "hist-1" in str(headers):
            mid = "hist-1"
        else:
            mid = "live-1"
        return httpx.Response(200, json=_sample_gmail_message(mid))

    fake_http = FakeHttpClient(
        {
            (
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            ): list_handler,
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/live-1"): (
                lambda params, headers: httpx.Response(
                    200, json=_sample_gmail_message("live-1")
                )
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/hist-1"): (
                lambda params, headers: httpx.Response(
                    200, json=_sample_gmail_message("hist-1")
                )
            ),
        }
    )
    service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert len(call_queries) == 2
    assert "before:" not in call_queries[0]
    assert "before:" in call_queries[1]


def test_initial_history_backfill_one_page_and_persist_token(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    account = _upsert_google_account(db_session, credential_key)
    list_calls = 0

    def list_handler(params, headers):
        nonlocal list_calls
        list_calls += 1
        if "before:" in str(params.get("q")):
            return httpx.Response(
                200,
                json={"messages": [{"id": "hist-1"}], "nextPageToken": "token-next"},
            )
        return httpx.Response(200, json={"messages": []})

    fake_http = FakeHttpClient(
        {
            (
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            ): list_handler,
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/hist-1"): (
                lambda params, headers: httpx.Response(
                    200, json=_sample_gmail_message("hist-1")
                )
            ),
        }
    )
    service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert list_calls == 2
    stored = db_session.get(GoogleAccount, account.id)
    backfill = get_history_backfill(stored.gmail_sync_state)
    assert backfill.get("next_page_token") == "token-next"
    assert backfill.get("active_start") is not None


def test_history_pagination_completes_and_merges_scanned_interval(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    today = utc_today()
    account = _upsert_google_account(
        db_session,
        credential_key,
        gmail_sync_state={
            "history_backfill": {
                "version": 1,
                "active_start": format_stored_date(today - timedelta(days=10)),
                "active_end": format_stored_date(today + timedelta(days=1)),
                "next_page_token": "token-a",
            }
        },
    )

    def list_handler(params, headers):
        if params.get("pageToken") == "token-a":
            return httpx.Response(200, json={"messages": [{"id": "hist-2"}]})
        return httpx.Response(200, json={"messages": []})

    fake_http = FakeHttpClient(
        {
            (
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            ): list_handler,
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/hist-2"): (
                lambda params, headers: httpx.Response(
                    200, json=_sample_gmail_message("hist-2")
                )
            ),
        }
    )
    service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(GoogleAccount, account.id)
    backfill = get_history_backfill(stored.gmail_sync_state)
    assert backfill.get("next_page_token") is None
    assert backfill.get("active_start") is None
    assert backfill.get("scanned_start") is not None
    assert backfill.get("scanned_end") is not None


def test_one_recurring_run_bounded_to_live_plus_one_history_page(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    account = _upsert_google_account(db_session, credential_key)
    history_list_calls = 0

    def list_handler(params, headers):
        nonlocal history_list_calls
        if "before:" in str(params.get("q")):
            history_list_calls += 1
            return httpx.Response(
                200,
                json={
                    "messages": [{"id": f"hist-{history_list_calls}"}],
                    "nextPageToken": "more",
                },
            )
        return httpx.Response(200, json={"messages": []})

    fake_http = FakeHttpClient(
        {
            (
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            ): list_handler,
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/hist-1"): (
                lambda params, headers: httpx.Response(
                    200, json=_sample_gmail_message("hist-1")
                )
            ),
        }
    )
    service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert history_list_calls == 1


def test_known_backfill_messages_skip_get_message(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    account = _upsert_google_account(db_session, credential_key)
    db_session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="email",
            provider="gmail",
            external_id="known-hist",
            origin="source",
            state="observed",
            title="old",
        )
    )
    db_session.flush()
    get_calls = 0

    def list_handler(params, headers):
        if "before:" in str(params.get("q")):
            return httpx.Response(200, json={"messages": [{"id": "known-hist"}]})
        return httpx.Response(200, json={"messages": []})

    def get_handler(params, headers):
        nonlocal get_calls
        get_calls += 1
        return httpx.Response(200, json=_sample_gmail_message("known-hist"))

    fake_http = FakeHttpClient(
        {
            (
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            ): list_handler,
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/known-hist"): get_handler,
        }
    )
    service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert get_calls == 0


def test_new_historical_message_enqueue_once(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    account = _upsert_google_account(db_session, credential_key)

    def list_handler(params, headers):
        if "before:" in str(params.get("q")):
            return httpx.Response(200, json={"messages": [{"id": "new-hist"}]})
        return httpx.Response(200, json={"messages": []})

    fake_http = FakeHttpClient(
        {
            (
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            ): list_handler,
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/new-hist"): (
                lambda params, headers: httpx.Response(
                    200, json=_sample_gmail_message("new-hist")
                )
            ),
        }
    )
    service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    obj = db_session.scalar(
        select(Object).where(Object.external_id == "new-hist", Object.provider == "gmail")
    )
    assert obj is not None
    embed_jobs = list(
        db_session.scalars(select(Job).where(Job.type == "embed_object", Job.user_id == BOOTSTRAP_USER_ID))
    )
    matching = [j for j in embed_jobs if j.payload.get("object_id") == str(obj.id)]
    assert len(matching) == 1


def test_crash_mid_page_does_not_advance_token(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    today = utc_today()
    account = _upsert_google_account(
        db_session,
        credential_key,
        gmail_sync_state={
            "history_backfill": {
                "version": 1,
                "active_start": format_stored_date(today - timedelta(days=5)),
                "active_end": format_stored_date(today + timedelta(days=1)),
                "next_page_token": "token-a",
            }
        },
    )

    def list_handler(params, headers):
        if "before:" in str(params.get("q")):
            return httpx.Response(
                200,
                json={
                    "messages": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}],
                    "nextPageToken": "token-b",
                },
            )
        return httpx.Response(200, json={"messages": []})

    def get_m2(params, headers):
        raise RuntimeError("simulated crash")

    fake_http = FakeHttpClient(
        {
            (
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            ): list_handler,
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/m1"): (
                lambda params, headers: httpx.Response(200, json=_sample_gmail_message("m1"))
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/m2"): get_m2,
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/m3"): (
                lambda params, headers: httpx.Response(200, json=_sample_gmail_message("m3"))
            ),
        }
    )
    service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(GoogleAccount, account.id)
    backfill = get_history_backfill(stored.gmail_sync_state)
    assert backfill.get("next_page_token") == "token-a"
    assert db_session.scalar(select(Object).where(Object.external_id == "m1")) is not None


def test_history_increase_schedules_backward_extension_only(
    db_session,
    credential_key: str,
) -> None:
    today = utc_today()
    scanned_start = today - timedelta(days=30)
    scanned_end = today + timedelta(days=1)
    backfill = {
        "version": 1,
        "scanned_start": format_stored_date(scanned_start),
        "scanned_end": format_stored_date(scanned_end),
    }
    window = plan_history_active_window(backfill, history_days=90).window
    assert window is not None
    assert window.active_end == scanned_start
    assert window.active_start == today - timedelta(days=90)


def test_history_decrease_does_not_delete_objects(
    db_session,
    credential_key: str,
) -> None:
    old_obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        provider="gmail",
        external_id="old-mail",
        origin="source",
        state="observed",
        title="old mail",
    )
    db_session.add(old_obj)
    db_session.flush()
    today = utc_today()
    backfill = {
        "version": 1,
        "scanned_start": format_stored_date(today - timedelta(days=90)),
        "scanned_end": format_stored_date(today + timedelta(days=1)),
    }
    window = plan_history_active_window(backfill, history_days=14).window
    assert window is None or window.active_start >= today - timedelta(days=14)
    assert db_session.get(Object, old_obj.id) is not None


def test_forward_catch_up_when_scan_boundary_advances() -> None:
    today = utc_today()
    scanned_end = today - timedelta(days=2)
    backfill = {
        "version": 1,
        "scanned_start": format_stored_date(today - timedelta(days=30)),
        "scanned_end": format_stored_date(scanned_end),
    }
    window = plan_history_active_window(backfill, history_days=30).window
    assert window is not None
    assert window.active_start == scanned_end


def test_direct_http_gmail_sync_live_only_uses_effective_history(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    monkeypatch.setattr(settings, "google_oauth_client_file", oauth_client_file)
    monkeypatch.setattr(
        settings,
        "google_redirect_uri",
        "http://localhost:18080/auth/google/callback",
    )
    account = _upsert_google_account(db_session, credential_key)
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_GMAIL,
        history_days=7,
        history_days_specified=True,
    )
    list_calls = 0

    def fake_list_page(
        self,
        access_token,
        user_id,
        query,
        max_results,
        page_token=None,
    ):
        nonlocal list_calls
        list_calls += 1
        return GmailMessagePage(message_ids=[], next_page_token=None)

    monkeypatch.setattr(GmailTransport, "list_message_ids_page", fake_list_page)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        response = client.post(
            f"/connectors/google/gmail/sync?account_id={account.id}",
            headers=auth_headers,
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert list_calls == 1


def test_disabled_gmail_worker_skips_provider_calls(
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
    persist_session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
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
    ready_session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
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
