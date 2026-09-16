"""PHASE 28C-B2-B1-R1 — reconcile active Gmail backfill with current history policy."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet

from app.connectors.google.constants import GMAIL_READONLY_SCOPE
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.gmail_history_state import (
    desired_history_window,
    format_stored_date,
    get_history_backfill,
    plan_history_active_window,
    reconcile_active_window,
    utc_today,
)
from app.connectors.google.gmail_sync import build_gmail_sync_service
from app.core.config import settings
from app.db.engine import engine
from app.db.models import GoogleAccount, Job, Object, UserSourcePreference
from app.users.bootstrap import BOOTSTRAP_USER_ID


def utcnow() -> datetime:
    return datetime.now(UTC)


class FakeHttpClient:
    def __init__(self, handlers: dict) -> None:
        self._handlers = handlers
        self.calls: list[tuple] = []

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


@pytest.fixture(autouse=True)
def cleanup_tables() -> None:
    from sqlalchemy import delete
    from sqlalchemy.orm import Session

    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
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
    db_session.flush()
    return account


def test_narrow_history_discards_out_of_policy_active_window_and_token() -> None:
    today = utc_today()
    desired_start, desired_end = desired_history_window(14)
    backfill = {
        "version": 1,
        "active_start": format_stored_date(today - timedelta(days=90)),
        "active_end": format_stored_date(today + timedelta(days=1)),
        "next_page_token": "token-a",
    }
    reconciled = reconcile_active_window(backfill, history_days=14)
    assert reconciled.get("next_page_token") is None
    assert reconciled.get("active_start") is None
    assert reconciled.get("scanned_start") is None

    plan = plan_history_active_window(backfill, history_days=14)
    assert plan.backfill.get("next_page_token") is None
    assert plan.window is not None
    assert plan.window.next_page_token is None
    assert plan.window.active_start >= desired_start
    assert plan.window.active_end <= desired_end


def test_sync_service_does_not_send_discarded_page_token(
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
                "active_start": format_stored_date(today - timedelta(days=90)),
                "active_end": format_stored_date(today + timedelta(days=1)),
                "next_page_token": "token-a",
            }
        },
    )
    history_params: list[dict] = []

    def list_handler(params, headers):
        if "before:" in str(params.get("q")):
            history_params.append(dict(params))
            return httpx.Response(200, json={"messages": []})
        return httpx.Response(200, json={"messages": []})

    service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=14,
        default_limit=50,
        max_limit=100,
        http_client=FakeHttpClient(
            {
                (
                    "GET",
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                ): list_handler,
            }
        ),
    )
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert history_params
    assert history_params[0].get("pageToken") is None


def test_scanned_interval_preserved_when_active_extension_abandoned(
    db_session,
    credential_key: str,
    oauth_client_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    today = utc_today()
    scanned_start = today - timedelta(days=30)
    scanned_end = today + timedelta(days=1)
    account = _upsert_google_account(
        db_session,
        credential_key,
        gmail_sync_state={
            "history_backfill": {
                "version": 1,
                "scanned_start": format_stored_date(scanned_start),
                "scanned_end": format_stored_date(scanned_end),
                "active_start": format_stored_date(today - timedelta(days=90)),
                "active_end": format_stored_date(scanned_start),
                "next_page_token": "token-b",
            }
        },
    )
    list_calls = 0

    def list_handler(params, headers):
        nonlocal list_calls
        list_calls += 1
        return httpx.Response(200, json={"messages": []})

    service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=14,
        default_limit=50,
        max_limit=100,
        http_client=FakeHttpClient(
            {
                (
                    "GET",
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                ): list_handler,
            }
        ),
    )
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert list_calls == 1
    stored = db_session.get(GoogleAccount, account.id)
    backfill = get_history_backfill(stored.gmail_sync_state)
    assert backfill.get("scanned_start") == format_stored_date(scanned_start)
    assert backfill.get("scanned_end") == format_stored_date(scanned_end)
    assert backfill.get("next_page_token") is None
    assert backfill.get("active_start") is None


def test_deployment_max_narrowing_discards_old_token(
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
                "active_start": format_stored_date(today - timedelta(days=90)),
                "active_end": format_stored_date(today + timedelta(days=1)),
                "next_page_token": "token-old",
            }
        },
    )
    history_params: list[dict] = []

    def list_handler(params, headers):
        if "before:" in str(params.get("q")):
            history_params.append(dict(params))
        return httpx.Response(200, json={"messages": []})

    service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=FakeHttpClient(
            {
                (
                    "GET",
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                ): list_handler,
            }
        ),
    )
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert history_params
    assert history_params[0].get("pageToken") is None


def test_history_increase_keeps_valid_active_token() -> None:
    today = utc_today()
    desired_start_90, desired_end = desired_history_window(90)
    active_start = today - timedelta(days=30)
    active_end = today - timedelta(days=15)
    backfill = {
        "version": 1,
        "active_start": format_stored_date(active_start),
        "active_end": format_stored_date(active_end),
        "next_page_token": "keep-token",
    }
    plan = plan_history_active_window(backfill, history_days=90)
    assert plan.window is not None
    assert plan.window.next_page_token == "keep-token"
    assert plan.window.active_start == active_start
    assert plan.window.active_end == active_end
    assert active_start >= desired_start_90
    assert active_end <= desired_end


def test_crash_after_reconcile_clears_token_before_provider(
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
                "active_start": format_stored_date(today - timedelta(days=90)),
                "active_end": format_stored_date(today + timedelta(days=1)),
                "next_page_token": "token-a",
            }
        },
    )

    def list_handler(params, headers):
        if "before:" in str(params.get("q")):
            raise RuntimeError("simulated crash after reconcile")
        return httpx.Response(200, json={"messages": []})

    service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=14,
        default_limit=50,
        max_limit=100,
        http_client=FakeHttpClient(
            {
                (
                    "GET",
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                ): list_handler,
            }
        ),
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)

    db_session.expire_all()
    stored = db_session.get(GoogleAccount, account.id)
    backfill = get_history_backfill(stored.gmail_sync_state)
    assert backfill.get("next_page_token") is None
    assert backfill.get("active_start") is not None
    assert backfill.get("active_end") is not None

    history_params: list[dict] = []

    def list_handler_retry(params, headers):
        if "before:" in str(params.get("q")):
            history_params.append(dict(params))
        return httpx.Response(200, json={"messages": []})

    service_retry = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=14,
        default_limit=50,
        max_limit=100,
        http_client=FakeHttpClient(
            {
                (
                    "GET",
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                ): list_handler_retry,
            }
        ),
    )
    service_retry.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert history_params
    assert history_params[0].get("pageToken") is None
