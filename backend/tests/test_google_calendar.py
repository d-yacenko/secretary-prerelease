import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.connectors.google.calendar_normalize import normalize_calendar_event
from app.connectors.google.calendar_sync import build_calendar_sync_service
from app.connectors.google.constants import (
    CALENDAR_API_BASE,
    CALENDAR_READONLY_SCOPE,
    GMAIL_READONLY_SCOPE,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleConnectorError
from app.db.models import Object, User
from app.users.bootstrap import BOOTSTRAP_USER_ID


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
def user_b_id(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="User B"))
    db_session.flush()
    return user_id


class FakeHttpClient:
    def __init__(self, handlers: dict) -> None:
        self._handlers = handlers

    def post(self, url: str, data: dict | None = None, **kwargs) -> httpx.Response:
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
        handler = self._handlers.get(("GET", url))
        if handler is None:
            raise AssertionError(f"unexpected GET {url}")
        return handler(params, headers)


def _sample_calendar_event(
    event_id: str = "evt-1",
    summary: str = "Team sync",
    description: str = "Discuss roadmap",
) -> dict:
    start = utcnow() + timedelta(hours=1)
    end = start + timedelta(hours=1)
    return {
        "id": event_id,
        "status": "confirmed",
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "location": "Room A",
        "htmlLink": "https://calendar.google.com/event?eid=evt-1",
        "organizer": {"email": "owner@example.com"},
        "attendees": [
            {"email": "guest@example.com", "responseStatus": "accepted"},
        ],
        "updated": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _calendar_handlers(
    calendar_id: str = "primary",
    events: list[dict] | None = None,
) -> dict:
    events = events or [_sample_calendar_event()]
    return {
        ("GET", f"{CALENDAR_API_BASE}/users/me/calendarList"): lambda params, headers: httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": calendar_id,
                        "summary": "Primary",
                        "primary": True,
                    }
                ]
            },
        ),
        ("GET", f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events"): lambda params, headers: httpx.Response(
            200,
            json={"items": events},
        ),
    }


def test_calendar_normalization_preserves_calendar_and_event_ids() -> None:
    normalized = normalize_calendar_event(
        _sample_calendar_event("evt-abc", "Standup"),
        calendar_id="primary",
        calendar_summary="Primary",
    )
    assert normalized["kind"] == "event"
    assert normalized["provider"] == "google_calendar"
    assert normalized["origin"] == "source"
    assert normalized["state"] == "observed"
    assert normalized["external_id"] == "primary:evt-abc"
    assert normalized["metadata"]["calendar_id"] == "primary"
    assert normalized["metadata"]["event_id"] == "evt-abc"
    assert normalized["start_at"] is not None
    assert normalized["due_at"] is not None


def test_calendar_normalization_preserves_self_attendee_and_organizer_flags() -> None:
    event = _sample_calendar_event("evt-self")
    event["organizer"] = {"email": "me@example.com", "self": True}
    event["attendees"] = [
        {"email": "me@example.com", "self": True, "responseStatus": "accepted"},
    ]
    normalized = normalize_calendar_event(event, calendar_id="primary")
    assert normalized["metadata"]["organizer"] == "me@example.com"
    assert normalized["metadata"]["organizer_self"] is True
    assert normalized["metadata"]["attendees"] == [
        {"email": "me@example.com", "response_status": "accepted", "self": "true"},
    ]
    assert "attendees_truncated" not in normalized["metadata"]


def test_calendar_normalization_marks_attendees_truncated() -> None:
    event = _sample_calendar_event("evt-many")
    event["attendees"] = [
        {"email": f"a{index}@example.com", "responseStatus": "accepted"}
        for index in range(21)
    ]
    normalized = normalize_calendar_event(event, calendar_id="primary")
    assert len(normalized["metadata"]["attendees"]) == 20
    assert normalized["metadata"]["attendees_truncated"] is True


def test_bounded_calendar_sync_creates_observed_event_objects(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE, CALENDAR_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    fake_http = FakeHttpClient(_calendar_handlers(events=[_sample_calendar_event("evt-1")]))
    sync_service = build_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        http_client=fake_http,
    )
    result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)

    assert result["created"] == 1
    assert result["jobs_enqueued"] == 1

    obj = db_session.scalar(
        select(Object).where(
            Object.provider == "google_calendar",
            Object.kind == "event",
            Object.external_id == "primary:evt-1",
        )
    )
    assert obj is not None
    assert obj.user_id == BOOTSTRAP_USER_ID
    assert obj.origin == "source"
    assert obj.state == "observed"
    assert obj.title == "Team sync"
    assert obj.body == "Discuss roadmap"
    assert obj.metadata_["calendar_id"] == "primary"


def test_calendar_resync_unchanged_without_duplicate_jobs(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[CALENDAR_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    fake_http = FakeHttpClient(_calendar_handlers(events=[_sample_calendar_event("evt-2")]))
    sync_service = build_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
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
        select(func.count())
        .select_from(Object)
        .where(
            Object.provider == "google_calendar",
            Object.external_id == "primary:evt-2",
        )
    )
    assert count == 1


def test_calendar_resync_updates_object_and_enqueues_on_title_change(
    db_session,
    oauth_client_file: str,
    credential_key: str,
) -> None:
    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[CALENDAR_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    fetch_count = 0

    def events_handler(params, headers):
        nonlocal fetch_count
        fetch_count += 1
        summary = "Team sync" if fetch_count == 1 else "Updated title"
        return httpx.Response(
            200,
            json={"items": [_sample_calendar_event("evt-upd", summary=summary)]},
        )

    handlers = _calendar_handlers()
    handlers[("GET", f"{CALENDAR_API_BASE}/calendars/primary/events")] = events_handler
    fake_http = FakeHttpClient(handlers)

    sync_service = build_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        http_client=fake_http,
    )
    first = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    second = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)

    assert first["created"] == 1
    assert second["updated"] == 1
    assert second["jobs_enqueued"] == 1

    obj = db_session.scalar(
        select(Object).where(Object.external_id == "primary:evt-upd")
    )
    assert obj is not None
    assert obj.title == "Updated title"


def test_calendar_sync_requires_calendar_scope(
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

    sync_service = build_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost:18080/auth/google/callback",
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        http_client=FakeHttpClient(_calendar_handlers()),
    )
    with pytest.raises(GoogleConnectorError, match="missing calendar scope"):
        sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)


def test_two_users_can_store_same_calendar_external_id(
    db_session,
    oauth_client_file: str,
    credential_key: str,
    user_b_id,
) -> None:
    for user_id in (BOOTSTRAP_USER_ID, user_b_id):
        account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
        account = account_store.upsert_tokens(
            user_id=user_id,
            email=f"{user_id}@example.com",
            scopes=[CALENDAR_READONLY_SCOPE],
            access_token="access-token",
            refresh_token="refresh-token",
            token_expiry=utcnow() + timedelta(hours=1),
        )
        db_session.commit()
        sync_service = build_calendar_sync_service(
            session=db_session,
            credential_key=credential_key,
            client_file=oauth_client_file,
            redirect_uri="http://localhost:18080/auth/google/callback",
            days_back=60,
            days_forward=90,
            default_limit=100,
            max_limit=100,
            max_calendars=10,
            http_client=FakeHttpClient(_calendar_handlers(events=[_sample_calendar_event("shared-evt")])),
        )
        sync_service.sync_account(account.id, user_id, limit=1)

    objs = list(
        db_session.scalars(
            select(Object).where(
                Object.provider == "google_calendar",
                Object.external_id == "primary:shared-evt",
            )
        ).all()
    )
    assert len(objs) == 2
    assert {obj.user_id for obj in objs} == {BOOTSTRAP_USER_ID, user_b_id}
