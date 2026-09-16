"""Temporal Correctness B — recurring Calendar occurrence materialization for Today."""

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.connectors.google.calendar_normalize import normalize_calendar_event
from app.connectors.google.calendar_sync import build_calendar_sync_service
from app.connectors.google.constants import (
    CALENDAR_API_BASE,
    CALENDAR_READONLY_SCOPE,
    LIVE_CALENDAR_MAX_PAGES_PER_CALENDAR,
    LIVE_CALENDAR_PAGE_SIZE,
    LIVE_COVERAGE_STATE_KEY,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.yandex.caldav_transport import (
    CalDavCalendar,
    CalDavEvent,
    CalDavFetchResult,
    FakeCalDavTransport,
)
from app.connectors.yandex.calendar_credentials import YandexCalendarAccountStore
from app.connectors.yandex.calendar_normalize import (
    build_external_id,
    normalize_caldav_events,
)
from app.connectors.yandex.calendar_sync import build_yandex_calendar_sync_service
from app.connectors.yandex.constants import CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION
from app.db.models import Object
from app.services.today_service import TodayService
from app.users.bootstrap import BOOTSTRAP_USER_ID

FIXED_NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
CALENDAR_HREF = "/calendars/user@yandex.ru/events-1/"
CALENDAR_B_HREF = "/calendars/user@yandex.ru/events-2/"
WEEKLY_UID = "weekly-series"
TODAY_OCCURRENCE_START = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
NEXT_WEEK_START = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def oauth_client_file(tmp_path) -> str:
    path = tmp_path / "google-oauth-client.json"
    path.write_text(
        '{"web":{"client_id":"test-client-id","client_secret":"test-client-secret"}}',
        encoding="utf-8",
    )
    return str(path)


def _freeze_google_token_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    # GoogleTokenManager.get_valid_access_token compares expiry to this clock.
    monkeypatch.setattr("app.connectors.google.gmail_transport.utcnow", lambda: FIXED_NOW)


@pytest.fixture
def freeze_google_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.connectors.google.calendar_sync.utcnow", lambda: FIXED_NOW)
    _freeze_google_token_clock(monkeypatch)


def _parse_rfc3339(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


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


def _google_occurrence(
    *,
    event_id: str,
    start: datetime,
    summary: str = "Weekly meeting",
    recurring_event_id: str = "weekly-master",
    status: str = "confirmed",
    all_day: bool = False,
    time_zone: str | None = None,
) -> dict:
    end = start + timedelta(hours=1)
    payload = {
        "id": event_id,
        "status": status,
        "summary": summary,
        "recurringEventId": recurring_event_id,
        "updated": "2026-09-01T08:00:00Z",
    }
    if all_day:
        payload["start"] = {"date": start.date().isoformat()}
        payload["end"] = {"date": (start.date() + timedelta(days=1)).isoformat()}
    else:
        start_field = {"dateTime": start.isoformat()}
        end_field = {"dateTime": end.isoformat()}
        if time_zone:
            start_field["timeZone"] = time_zone
            end_field["timeZone"] = time_zone
        payload["start"] = start_field
        payload["end"] = end_field
    return payload


def _google_handlers(
    events_by_calendar: dict[str, list[dict]],
    captured: dict | None = None,
    *,
    chunk_size: int | None = None,
    empty_first_page: bool = False,
) -> dict:
    calendars = [
        {"id": calendar_id, "summary": calendar_id, "primary": calendar_id == "primary"}
        for calendar_id in events_by_calendar
    ]

    def calendar_list(params, headers):
        return httpx.Response(200, json={"items": calendars})

    handlers = {("GET", f"{CALENDAR_API_BASE}/users/me/calendarList"): calendar_list}
    for calendar_id, events in events_by_calendar.items():
        encoded = quote(calendar_id, safe="")

        def make_handler(calendar_events):
            def events_handler(params, headers):
                if captured is not None:
                    captured.setdefault("event_calls", []).append(dict(params or {}))
                time_min = _parse_rfc3339((params or {}).get("timeMin"))
                time_max = _parse_rfc3339((params or {}).get("timeMax"))
                in_window = []
                for item in calendar_events:
                    start_field = item.get("start") or {}
                    if start_field.get("dateTime"):
                        start_at = _parse_rfc3339(start_field["dateTime"])
                    else:
                        start_at = datetime.fromisoformat(
                            f"{start_field.get('date')}T00:00:00+00:00"
                        )
                    if time_min <= start_at <= time_max:
                        in_window.append(item)
                page_token = (params or {}).get("pageToken")
                max_results = int((params or {}).get("maxResults") or 100)
                if empty_first_page and not page_token:
                    payload = {"items": [], "nextPageToken": "p0"}
                    return httpx.Response(200, json=payload)
                start = 0
                if page_token:
                    start = int(str(page_token).removeprefix("p"))
                take = chunk_size if chunk_size is not None else max_results
                page = in_window[start : start + take]
                payload = {"items": page}
                nxt = start + take
                if nxt < len(in_window):
                    payload["nextPageToken"] = f"p{nxt}"
                return httpx.Response(200, json=payload)

            return events_handler

        handlers[("GET", f"{CALENDAR_API_BASE}/calendars/{encoded}/events")] = make_handler(
            events
        )
    return handlers


def _build_google_sync(db_session, credential_key, oauth_client_file, fake_http):
    return build_calendar_sync_service(
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


def _google_account(db_session, credential_key):
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[CALENDAR_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=FIXED_NOW + timedelta(hours=1),
    )
    db_session.commit()
    return account


def _today_event_ids(db_session, reference_at=FIXED_NOW):
    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(
        reference_at=reference_at,
        timezone="Europe/Moscow",
    )
    return {obj.external_id for obj in snapshot["calendar_events"]}


def _yandex_weekly_expanded(*, include_today=True, include_next=False, cancelled_today=False, title="Weekly"):
    lines = ["BEGIN:VCALENDAR"]
    for start, include in (
        (TODAY_OCCURRENCE_START, include_today),
        (NEXT_WEEK_START, include_next),
    ):
        if not include:
            continue
        end = start + timedelta(hours=1)
        recurrence_id = start.strftime("%Y%m%dT%H%M%SZ")
        status = "CANCELLED" if cancelled_today and start == TODAY_OCCURRENCE_START else "CONFIRMED"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{WEEKLY_UID}",
                f"RECURRENCE-ID:{recurrence_id}",
                f"SUMMARY:{title}",
                f"STATUS:{status}",
                f"DTSTART:{recurrence_id}",
                f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\n".join(lines) + "\n"


def _yandex_master_ical() -> str:
    return (
        "BEGIN:VCALENDAR\n"
        "BEGIN:VEVENT\n"
        f"UID:{WEEKLY_UID}\n"
        "SUMMARY:Weekly\n"
        "DTSTART:20260812T100000Z\n"
        "DTEND:20260812T110000Z\n"
        "RRULE:FREQ=WEEKLY;INTERVAL=1\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )


def _yandex_account(db_session, credential_key, email="cal@yandex.ru"):
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email=email,
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    db_session.commit()
    return store, account


def test_google_normalize_keeps_occurrence_identity_not_master() -> None:
    event = _google_occurrence(
        event_id="weekly-master_20260909T100000Z",
        start=TODAY_OCCURRENCE_START,
    )
    normalized = normalize_calendar_event(event, calendar_id="primary")
    assert normalized["external_id"] == "primary:weekly-master_20260909T100000Z"
    assert normalized["metadata"]["event_id"] == "weekly-master_20260909T100000Z"
    assert normalized["metadata"]["recurring_event_id"] == "weekly-master"


def test_google_weekly_occurrence_materialized_and_in_today(
    db_session,
    oauth_client_file,
    credential_key,
    freeze_google_now,
) -> None:
    account = _google_account(db_session, credential_key)
    occurrence_id = "weekly-master_20260909T100000Z"
    captured: dict = {}
    events = [
        _google_occurrence(event_id="old-1", start=FIXED_NOW - timedelta(days=40)),
        *[_google_occurrence(event_id=f"hist-{i}", start=FIXED_NOW - timedelta(days=30, minutes=i)) for i in range(120)],
        _google_occurrence(event_id=occurrence_id, start=TODAY_OCCURRENCE_START),
    ]
    # Historical events are outside the live operational window; they must not
    # starve today's occurrence (root cause: first page of now-60d window).
    fake_http = FakeHttpClient(_google_handlers({"primary": events}, captured))
    sync = _build_google_sync(db_session, credential_key, oauth_client_file, fake_http)
    result = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    obj = db_session.scalar(select(Object).where(Object.external_id == f"primary:{occurrence_id}"))
    assert obj is not None, (
        "stage=materialization; Google live window used to start 60d back with "
        "first-page-only list_events, so old occurrences consumed the budget"
    )
    assert result["created"] >= 1
    assert f"primary:{occurrence_id}" in _today_event_ids(db_session)
    assert any(call.get("showDeleted") == "true" for call in captured.get("event_calls", []))
    assert all(call.get("singleEvents") == "true" for call in captured.get("event_calls", []))
    assert all(call.get("orderBy") == "startTime" for call in captured.get("event_calls", []))
    time_min = _parse_rfc3339(captured["event_calls"][0]["timeMin"])
    assert time_min >= FIXED_NOW - timedelta(days=2)


def test_google_provider_pagination_reaches_occurrence_past_page_one(
    db_session,
    oauth_client_file,
    credential_key,
    freeze_google_now,
) -> None:
    account = _google_account(db_session, credential_key)
    occurrence_id = "weekly-master_20260909T150000Z"
    dense = [
        _google_occurrence(
            event_id=f"dense-{index}",
            start=FIXED_NOW + timedelta(minutes=index),
            recurring_event_id="other",
        )
        for index in range(LIVE_CALENDAR_PAGE_SIZE)
    ]
    target = _google_occurrence(
        event_id=occurrence_id,
        start=FIXED_NOW + timedelta(hours=3),
    )
    captured: dict = {}
    fake_http = FakeHttpClient(_google_handlers({"primary": [*dense, target]}, captured))
    sync = _build_google_sync(db_session, credential_key, oauth_client_file, fake_http)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    obj = db_session.scalar(select(Object).where(Object.external_id == f"primary:{occurrence_id}"))
    assert obj is not None, "stage=provider-page; next_page_token was discarded after page 1"
    tokens = [call.get("pageToken") for call in captured.get("event_calls", [])]
    assert any(token for token in tokens)
    assert len(captured["event_calls"]) <= LIVE_CALENDAR_MAX_PAGES_PER_CALENDAR


def test_google_dense_calendar_a_does_not_starve_calendar_b(
    db_session,
    oauth_client_file,
    credential_key,
    freeze_google_now,
) -> None:
    account = _google_account(db_session, credential_key)
    occurrence_id = "calb_20260909T100000Z"
    calendar_a = [
        _google_occurrence(event_id=f"a-{i}", start=FIXED_NOW + timedelta(minutes=i), recurring_event_id="a")
        for i in range(80)
    ]
    calendar_b = [
        _google_occurrence(event_id=occurrence_id, start=TODAY_OCCURRENCE_START, recurring_event_id="b")
    ]
    fake_http = FakeHttpClient(_google_handlers({"cal-a": calendar_a, "cal-b": calendar_b}))
    sync = _build_google_sync(db_session, credential_key, oauth_client_file, fake_http)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=40)
    obj = db_session.scalar(select(Object).where(Object.external_id == f"cal-b:{occurrence_id}"))
    assert obj is not None, "stage=multi-calendar; calendar A consumed the global live budget"


def test_google_resync_idempotent_and_modified_occurrence_updates_same_object(
    db_session,
    oauth_client_file,
    credential_key,
    freeze_google_now,
) -> None:
    account = _google_account(db_session, credential_key)
    occurrence_id = "weekly-master_20260909T100000Z"
    events = [_google_occurrence(event_id=occurrence_id, start=TODAY_OCCURRENCE_START)]
    fake_http = FakeHttpClient(_google_handlers({"primary": events}))
    sync = _build_google_sync(db_session, credential_key, oauth_client_file, fake_http)
    first = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    second = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert first["created"] == 1
    assert second["created"] == 0
    assert second["unchanged"] >= 1
    events[0]["summary"] = "Moved weekly"
    events[0]["start"] = {"dateTime": (TODAY_OCCURRENCE_START + timedelta(hours=1)).isoformat()}
    events[0]["end"] = {"dateTime": (TODAY_OCCURRENCE_START + timedelta(hours=2)).isoformat()}
    third = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert third["updated"] == 1
    count = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.external_id == f"primary:{occurrence_id}")
    )
    assert count == 1
    obj = db_session.scalar(select(Object).where(Object.external_id == f"primary:{occurrence_id}"))
    assert obj is not None
    assert obj.title == "Moved weekly"
    assert obj.metadata_["recurring_event_id"] == "weekly-master"


def test_google_cancelled_occurrence_leaves_today(
    db_session,
    oauth_client_file,
    credential_key,
    freeze_google_now,
) -> None:
    account = _google_account(db_session, credential_key)
    occurrence_id = "weekly-master_20260909T100000Z"
    sibling_id = "weekly-master_20260916T100000Z"
    events = [
        _google_occurrence(event_id=occurrence_id, start=TODAY_OCCURRENCE_START),
        _google_occurrence(event_id=sibling_id, start=NEXT_WEEK_START),
    ]
    fake_http = FakeHttpClient(_google_handlers({"primary": events}))
    sync = _build_google_sync(db_session, credential_key, oauth_client_file, fake_http)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert f"primary:{occurrence_id}" in _today_event_ids(db_session)
    events[0]["status"] = "cancelled"
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    today_ids = _today_event_ids(db_session)
    assert f"primary:{occurrence_id}" not in today_ids
    sibling = db_session.scalar(select(Object).where(Object.external_id == f"primary:{sibling_id}"))
    assert sibling is not None
    assert sibling.status != "deleted"


def test_google_all_day_and_timezone_occurrence_in_today(
    db_session,
    oauth_client_file,
    credential_key,
    freeze_google_now,
) -> None:
    account = _google_account(db_session, credential_key)
    moscow_start = datetime.fromisoformat("2026-09-09T10:00:00+03:00")
    events = [
        _google_occurrence(
            event_id="all-day_20260909",
            start=datetime(2026, 9, 9, tzinfo=UTC),
            all_day=True,
            recurring_event_id="all-day",
        ),
        _google_occurrence(
            event_id="tz_20260909T070000Z",
            start=moscow_start,
            time_zone="Europe/Moscow",
            recurring_event_id="tz-weekly",
        ),
    ]
    fake_http = FakeHttpClient(_google_handlers({"primary": events}))
    sync = _build_google_sync(db_session, credential_key, oauth_client_file, fake_http)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    today_ids = _today_event_ids(db_session)
    assert "primary:all-day_20260909" in today_ids
    assert "primary:tz_20260909T070000Z" in today_ids


def test_yandex_unexpanded_master_is_not_an_occurrence_object() -> None:
    events = normalize_caldav_events(_yandex_master_ical(), CALENDAR_HREF)
    assert events == []


def test_yandex_expanded_weekly_has_stable_occurrence_identity() -> None:
    ical = _yandex_weekly_expanded(include_today=True, include_next=True)
    events = normalize_caldav_events(ical, CALENDAR_HREF)
    ids = [item["external_id"] for item in events]
    assert ids == [
        build_external_id(CALENDAR_HREF, WEEKLY_UID, "20260909T100000Z"),
        build_external_id(CALENDAR_HREF, WEEKLY_UID, "20260916T100000Z"),
    ]
    assert events[0]["metadata"]["recurrence_id"] == "20260909T100000Z"
    assert events[1]["metadata"]["recurrence_id"] == "20260916T100000Z"


def test_yandex_weekly_occurrence_materialized_and_in_today(db_session, credential_key) -> None:
    _, account = _yandex_account(db_session, credential_key)
    href = f"{CALENDAR_HREF}{WEEKLY_UID}.ics"
    master = CalDavEvent(event_href=href, etag='"v1"', calendar_data=_yandex_master_ical())
    expanded = CalDavEvent(
        event_href=href,
        etag='"v1"',
        calendar_data=_yandex_weekly_expanded(include_today=True, include_next=True),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={CALENDAR_HREF: [master]},
        multiget_events_by_calendar={CALENDAR_HREF: {href: expanded}},
        sync_tokens_by_calendar={CALENDAR_HREF: "token-1"},
    )
    sync = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: FIXED_NOW,
    )
    result = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    external_id = build_external_id(CALENDAR_HREF, WEEKLY_UID, "20260909T100000Z")
    obj = db_session.scalar(select(Object).where(Object.external_id == external_id))
    assert obj is not None, (
        "stage=materialization; Yandex live used sync-token/backfill without "
        "re-expanding the operational window for unchanged recurring resources"
    )
    assert result["created"] >= 1
    assert external_id in _today_event_ids(db_session)


def test_yandex_moving_window_materializes_next_week_with_unchanged_etag(
    db_session, credential_key
) -> None:
    _, account = _yandex_account(db_session, credential_key, email="move@yandex.ru")
    href = f"{CALENDAR_HREF}{WEEKLY_UID}.ics"
    master = CalDavEvent(event_href=href, etag='"same"', calendar_data=_yandex_master_ical())
    expanded = CalDavEvent(
        event_href=href,
        etag='"same"',
        calendar_data=_yandex_weekly_expanded(include_today=True, include_next=True),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={CALENDAR_HREF: [master]},
        multiget_events_by_calendar={CALENDAR_HREF: {href: expanded}},
        sync_tokens_by_calendar={CALENDAR_HREF: "token-1"},
    )
    current = {"now": FIXED_NOW}

    def now_factory():
        return current["now"]

    sync = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=3,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=now_factory,
    )
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    today_id = build_external_id(CALENDAR_HREF, WEEKLY_UID, "20260909T100000Z")
    next_id = build_external_id(CALENDAR_HREF, WEEKLY_UID, "20260916T100000Z")
    assert db_session.scalar(select(Object).where(Object.external_id == today_id)) is not None
    assert db_session.scalar(select(Object).where(Object.external_id == next_id)) is None
    current["now"] = FIXED_NOW + timedelta(days=7)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    nxt = db_session.scalar(select(Object).where(Object.external_id == next_id))
    assert nxt is not None, (
        "stage=moving-window; unchanged ETag/sync-token skipped re-expansion "
        "so week N+1 never materialized"
    )
    assert nxt.metadata_["etag"] == '"same"'


def test_yandex_resync_idempotent_and_override_updates_occurrence(
    db_session, credential_key
) -> None:
    _, account = _yandex_account(db_session, credential_key, email="idemp@yandex.ru")
    href = f"{CALENDAR_HREF}{WEEKLY_UID}.ics"
    master = CalDavEvent(event_href=href, etag='"v1"', calendar_data=_yandex_master_ical())
    expanded = CalDavEvent(
        event_href=href,
        etag='"v1"',
        calendar_data=_yandex_weekly_expanded(include_today=True),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={CALENDAR_HREF: [master]},
        multiget_events_by_calendar={CALENDAR_HREF: {href: expanded}},
        sync_tokens_by_calendar={CALENDAR_HREF: "token-1"},
    )
    sync = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: FIXED_NOW,
    )
    first = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    second = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert first["created"] == 1
    assert second["created"] == 0
    transport._multiget_events[CALENDAR_HREF][href] = CalDavEvent(
        event_href=href,
        etag='"v2"',
        calendar_data=_yandex_weekly_expanded(include_today=True, title="Override"),
    )
    third = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert third["updated"] == 1
    external_id = build_external_id(CALENDAR_HREF, WEEKLY_UID, "20260909T100000Z")
    count = db_session.scalar(select(func.count()).select_from(Object).where(Object.external_id == external_id))
    assert count == 1
    obj = db_session.scalar(select(Object).where(Object.external_id == external_id))
    assert obj is not None
    assert obj.title == "Override"


def test_yandex_cancelled_occurrence_leaves_today_not_series(db_session, credential_key) -> None:
    _, account = _yandex_account(db_session, credential_key, email="cancel@yandex.ru")
    href = f"{CALENDAR_HREF}{WEEKLY_UID}.ics"
    master = CalDavEvent(event_href=href, etag='"v1"', calendar_data=_yandex_master_ical())
    expanded = CalDavEvent(
        event_href=href,
        etag='"v1"',
        calendar_data=_yandex_weekly_expanded(include_today=True, include_next=True),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={CALENDAR_HREF: [master]},
        multiget_events_by_calendar={CALENDAR_HREF: {href: expanded}},
        sync_tokens_by_calendar={CALENDAR_HREF: "token-1"},
    )
    sync = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: FIXED_NOW,
    )
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    today_id = build_external_id(CALENDAR_HREF, WEEKLY_UID, "20260909T100000Z")
    next_id = build_external_id(CALENDAR_HREF, WEEKLY_UID, "20260916T100000Z")
    transport._multiget_events[CALENDAR_HREF][href] = CalDavEvent(
        event_href=href,
        etag='"v1"',
        calendar_data=_yandex_weekly_expanded(
            include_today=True, include_next=True, cancelled_today=True
        ),
    )
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert today_id not in _today_event_ids(db_session)
    nxt = db_session.scalar(select(Object).where(Object.external_id == next_id))
    assert nxt is not None
    assert nxt.status != "deleted"


def test_yandex_dense_first_calendar_does_not_starve_later_calendar(
    db_session, credential_key
) -> None:
    _, account = _yandex_account(db_session, credential_key, email="fair@yandex.ru")
    dense_events = []
    for index in range(80):
        start = TODAY_OCCURRENCE_START + timedelta(minutes=index)
        uid = f"dense-{index}"
        ical = (
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
            f"UID:{uid}\nSUMMARY:Dense {index}\n"
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}\n"
            f"DTEND:{(start + timedelta(minutes=15)).strftime('%Y%m%dT%H%M%SZ')}\n"
            "END:VEVENT\nEND:VCALENDAR\n"
        )
        dense_events.append(
            CalDavEvent(event_href=f"{CALENDAR_HREF}{uid}.ics", etag=f'"{uid}"', calendar_data=ical)
        )
    href_b = f"{CALENDAR_B_HREF}{WEEKLY_UID}.ics"
    master_b = CalDavEvent(event_href=href_b, etag='"b"', calendar_data=_yandex_master_ical())
    expanded_b = CalDavEvent(
        event_href=href_b,
        etag='"b"',
        calendar_data=_yandex_weekly_expanded(include_today=True),
    )
    transport = FakeCalDavTransport(
        calendars=[
            CalDavCalendar(href=CALENDAR_HREF, display_name="Dense", sync_token=None),
            CalDavCalendar(href=CALENDAR_B_HREF, display_name="Work", sync_token=None),
        ],
        calendar_order=[CALENDAR_HREF, CALENDAR_B_HREF],
        query_events_by_calendar={
            CALENDAR_HREF: dense_events,
            CALENDAR_B_HREF: [master_b],
        },
        multiget_events_by_calendar={CALENDAR_B_HREF: {href_b: expanded_b}},
        sync_tokens_by_calendar={CALENDAR_HREF: "a", CALENDAR_B_HREF: "b"},
    )
    sync = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=40,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: FIXED_NOW,
    )
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=40)
    external_id = build_external_id(CALENDAR_B_HREF, WEEKLY_UID, "20260909T100000Z")
    obj = db_session.scalar(select(Object).where(Object.external_id == external_id))
    assert obj is not None, "stage=multi-calendar; global occurrence budget starved calendar B"


def test_yandex_all_day_and_timezone_occurrence_in_today(db_session, credential_key) -> None:
    _, account = _yandex_account(db_session, credential_key, email="tz@yandex.ru")
    all_day = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:all-day-week\n"
        "RECURRENCE-ID;VALUE=DATE:20260909\nSUMMARY:Holiday\n"
        "DTSTART;VALUE=DATE:20260909\nDTEND;VALUE=DATE:20260910\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )
    tz_ical = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:tz-week\n"
        "RECURRENCE-ID;TZID=Europe/Moscow:20260909T100000\nSUMMARY:Moscow weekly\n"
        "DTSTART;TZID=Europe/Moscow:20260909T100000\n"
        "DTEND;TZID=Europe/Moscow:20260909T110000\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )
    href_a = f"{CALENDAR_HREF}all-day.ics"
    href_b = f"{CALENDAR_HREF}tz.ics"
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={
            CALENDAR_HREF: [
                CalDavEvent(event_href=href_a, etag='"a"', calendar_data=all_day),
                CalDavEvent(event_href=href_b, etag='"b"', calendar_data=tz_ical),
            ]
        },
    )
    sync = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: FIXED_NOW,
    )
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    today_ids = _today_event_ids(db_session)
    assert any("all-day-week" in item for item in today_ids)
    assert any("tz-week" in item for item in today_ids)


def test_google_live_continuation_survives_now_drift(
    db_session,
    oauth_client_file,
    credential_key,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_now = {"value": FIXED_NOW}
    monkeypatch.setattr(
        "app.connectors.google.calendar_sync.utcnow",
        lambda: current_now["value"],
    )
    _freeze_google_token_clock(monkeypatch)
    account = _google_account(db_session, credential_key)
    occurrence_id = "weekly-master_20260909T121000Z"
    events = [
        _google_occurrence(
            event_id=f"dense-{index:03d}",
            start=FIXED_NOW + timedelta(minutes=index),
            recurring_event_id="dense",
        )
        for index in range(12)
    ]
    events[6] = _google_occurrence(
        event_id=occurrence_id,
        start=FIXED_NOW + timedelta(minutes=6),
    )
    captured: dict = {}
    fake_http = FakeHttpClient(_google_handlers({"primary": events}, captured))
    sync = _build_google_sync(db_session, credential_key, oauth_client_file, fake_http)
    first = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)
    assert first["created"] == 5
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    live = store.get_calendar_sync_state(account.id, BOOTSTRAP_USER_ID)[LIVE_COVERAGE_STATE_KEY]
    frozen = live["calendars"]["primary"]
    assert frozen["next_page_token"]
    assert frozen["active_time_min"]
    assert frozen["active_time_max"]
    run1_min = captured["event_calls"][0]["timeMin"]
    run1_max = captured["event_calls"][0]["timeMax"]

    current_now["value"] = FIXED_NOW + timedelta(minutes=15)
    captured["event_calls"].clear()
    second = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)
    assert captured["event_calls"][0]["timeMin"] == run1_min
    assert captured["event_calls"][0]["timeMax"] == run1_max
    assert captured["event_calls"][0].get("pageToken")
    assert second["created"] == 5
    obj = db_session.scalar(select(Object).where(Object.external_id == f"primary:{occurrence_id}"))
    assert obj is not None

    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    live = store.get_calendar_sync_state(account.id, BOOTSTRAP_USER_ID)[LIVE_COVERAGE_STATE_KEY]
    assert live.get("calendars", {}).get("primary") is None

    current_now["value"] = FIXED_NOW + timedelta(minutes=30)
    captured["event_calls"].clear()
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert captured["event_calls"][0].get("pageToken") in (None, "")
    assert captured["event_calls"][0]["timeMin"] != run1_min


def test_google_malformed_live_continuation_resets_to_fresh_window(
    db_session,
    oauth_client_file,
    credential_key,
    freeze_google_now,
) -> None:
    account = _google_account(db_session, credential_key)
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    store.update_calendar_sync_state(
        account.id,
        BOOTSTRAP_USER_ID,
        {
            LIVE_COVERAGE_STATE_KEY: {
                "calendars": {
                    "primary": {"next_page_token": "stale-token"},
                }
            }
        },
    )
    db_session.commit()
    captured: dict = {}
    fake_http = FakeHttpClient(
        _google_handlers(
            {"primary": [_google_occurrence(event_id="only", start=TODAY_OCCURRENCE_START)]},
            captured,
        )
    )
    sync = _build_google_sync(db_session, credential_key, oauth_client_file, fake_http)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=10)
    assert captured["event_calls"][0].get("pageToken") in (None, "")


def test_google_short_page_with_next_token_materializes_later_occurrence(
    db_session,
    oauth_client_file,
    credential_key,
    freeze_google_now,
) -> None:
    account = _google_account(db_session, credential_key)
    occurrence_id = "weekly-master_20260909T100000Z"
    events = [
        _google_occurrence(
            event_id=f"short-{index}",
            start=TODAY_OCCURRENCE_START + timedelta(minutes=index),
            recurring_event_id="short",
        )
        for index in range(3)
    ]
    events.append(
        _google_occurrence(
            event_id=occurrence_id,
            start=TODAY_OCCURRENCE_START + timedelta(minutes=3),
        )
    )
    captured: dict = {}
    fake_http = FakeHttpClient(
        _google_handlers({"primary": events}, captured, chunk_size=1)
    )
    sync = _build_google_sync(db_session, credential_key, oauth_client_file, fake_http)
    result = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert result["created"] >= 4
    first = captured["event_calls"][0]
    assert int(first["maxResults"]) == LIVE_CALENDAR_PAGE_SIZE
    assert first.get("pageToken") in (None, "")
    assert any(call.get("pageToken") for call in captured["event_calls"][1:])
    obj = db_session.scalar(select(Object).where(Object.external_id == f"primary:{occurrence_id}"))
    assert obj is not None
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    live = store.get_calendar_sync_state(account.id, BOOTSTRAP_USER_ID)[LIVE_COVERAGE_STATE_KEY]
    assert live.get("calendars", {}).get("primary") is None


def test_google_empty_page_with_next_token_continues_bounded(
    db_session,
    oauth_client_file,
    credential_key,
    freeze_google_now,
) -> None:
    account = _google_account(db_session, credential_key)
    occurrence_id = "weekly-master_20260909T100000Z"
    events = [
        _google_occurrence(
            event_id=occurrence_id,
            start=TODAY_OCCURRENCE_START,
        )
    ]
    captured: dict = {}
    fake_http = FakeHttpClient(
        _google_handlers({"primary": events}, captured, empty_first_page=True)
    )
    sync = _build_google_sync(db_session, credential_key, oauth_client_file, fake_http)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert len(captured["event_calls"]) >= 2
    assert len(captured["event_calls"]) <= LIVE_CALENDAR_MAX_PAGES_PER_CALENDAR
    assert captured["event_calls"][1].get("pageToken") == "p0"
    obj = db_session.scalar(select(Object).where(Object.external_id == f"primary:{occurrence_id}"))
    assert obj is not None
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    live = store.get_calendar_sync_state(account.id, BOOTSTRAP_USER_ID)[LIVE_COVERAGE_STATE_KEY]
    assert live.get("calendars", {}).get("primary") is None


def test_yandex_query_local_slice_sets_truncated() -> None:
    events = [
        CalDavEvent(
            event_href=f"{CALENDAR_HREF}evt-{index:03d}.ics",
            etag=f'"{index}"',
            calendar_data=(
                "BEGIN:VEVENT\n"
                f"UID:evt-{index:03d}\n"
                "DTSTART:20260909T100000Z\n"
                "DTEND:20260909T110000Z\n"
                "END:VEVENT\n"
            ),
        )
        for index in range(3)
    ]
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={CALENDAR_HREF: events},
    )
    result = transport.query_events(
        CALENDAR_HREF,
        FIXED_NOW - timedelta(days=1),
        FIXED_NOW + timedelta(days=1),
        max_results=2,
    )
    assert result.truncated is True
    assert result.local_truncated is True
    assert result.provider_truncated is False
    assert result.last_selected_href == f"{CALENDAR_HREF}evt-001.ics"
    assert result.selected_ref_hrefs == (
        f"{CALENDAR_HREF}evt-000.ics",
        f"{CALENDAR_HREF}evt-001.ics",
    )
    assert len(result.events) == 2


def test_yandex_same_calendar_truncation_reaches_later_recurring_resource(
    db_session, credential_key
) -> None:
    _, account = _yandex_account(db_session, credential_key, email="trunc@yandex.ru")
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    store.update_sync_state(
        account,
        {
            "normalization_version": CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION,
            "calendars": {CALENDAR_HREF: {"sync_token": "token-1"}},
        },
    )
    db_session.commit()
    dense_events = []
    for index in range(100):
        start = TODAY_OCCURRENCE_START + timedelta(minutes=index)
        uid = f"aaa-{index:03d}"
        ical = (
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
            f"UID:{uid}\nSUMMARY:Dense {index}\n"
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}\n"
            f"DTEND:{(start + timedelta(minutes=15)).strftime('%Y%m%dT%H%M%SZ')}\n"
            "END:VEVENT\nEND:VCALENDAR\n"
        )
        dense_events.append(
            CalDavEvent(
                event_href=f"{CALENDAR_HREF}{uid}.ics",
                etag=f'"{uid}"',
                calendar_data=ical,
            )
        )
    href_weekly = f"{CALENDAR_HREF}zzz-weekly.ics"
    master = CalDavEvent(event_href=href_weekly, etag='"w"', calendar_data=_yandex_master_ical())
    expanded = CalDavEvent(
        event_href=href_weekly,
        etag='"w"',
        calendar_data=_yandex_weekly_expanded(include_today=True),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={CALENDAR_HREF: [*dense_events, master]},
        multiget_events_by_calendar={CALENDAR_HREF: {href_weekly: expanded}},
        sync_tokens_by_calendar={CALENDAR_HREF: "token-1"},
    )
    sync = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: FIXED_NOW,
    )
    first = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    mutations = first["created"] + first["updated"] + first["tombstoned"]
    assert mutations <= 100
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    cursor = account.sync_state["calendars"][CALENDAR_HREF].get("operational_href_cursor")
    assert cursor == f"{CALENDAR_HREF}aaa-099.ics"
    external_id = build_external_id(CALENDAR_HREF, WEEKLY_UID, "20260909T100000Z")
    assert db_session.scalar(select(Object).where(Object.external_id == external_id)) is None

    second = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    obj = db_session.scalar(select(Object).where(Object.external_id == external_id))
    assert obj is not None
    assert external_id in _today_event_ids(db_session)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert "operational_href_cursor" not in account.sync_state["calendars"][CALENDAR_HREF]
    assert second["created"] >= 1


def test_yandex_provider_truncation_subdivides_range_to_reach_recurring_resource(
    db_session, credential_key
) -> None:
    _, account = _yandex_account(db_session, credential_key, email="provider-trunc@yandex.ru")
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    store.update_sync_state(
        account,
        {
            "normalization_version": CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION,
            "calendars": {CALENDAR_HREF: {"sync_token": "token-1"}},
        },
    )
    db_session.commit()
    dense_events = []
    dense_start = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
    for index in range(20):
        start = dense_start + timedelta(days=index)
        uid = f"aaa-{index:03d}"
        ical = (
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
            f"UID:{uid}\nSUMMARY:Dense {index}\n"
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}\n"
            f"DTEND:{(start + timedelta(hours=1)).strftime('%Y%m%dT%H%M%SZ')}\n"
            "END:VEVENT\nEND:VCALENDAR\n"
        )
        dense_events.append(
            CalDavEvent(
                event_href=f"{CALENDAR_HREF}{uid}.ics",
                etag=f'"{uid}"',
                calendar_data=ical,
            )
        )
    href_weekly = f"{CALENDAR_HREF}zzz-weekly.ics"
    master = CalDavEvent(event_href=href_weekly, etag='"w"', calendar_data=_yandex_master_ical())
    expanded = CalDavEvent(
        event_href=href_weekly,
        etag='"w"',
        calendar_data=_yandex_weekly_expanded(include_today=True),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={CALENDAR_HREF: [*dense_events, master]},
        multiget_events_by_calendar={CALENDAR_HREF: {href_weekly: expanded}},
        sync_tokens_by_calendar={CALENDAR_HREF: "token-1"},
        provider_ref_cap=5,
    )
    sync = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: FIXED_NOW,
    )
    created = 0
    found = None
    external_id = build_external_id(CALENDAR_HREF, WEEKLY_UID, "20260909T100000Z")
    for _ in range(20):
        result = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
        created += result["created"]
        found = db_session.scalar(select(Object).where(Object.external_id == external_id))
        if found is not None:
            break
    assert found is not None
    assert "20260909T100000Z" in (found.external_id or "")
    assert external_id in _today_event_ids(db_session)
    assert len(transport.query_windows) >= 2
    assert len(transport.query_windows) < 500
    first_start, first_end, _ = transport.query_windows[0]
    later_progress = False
    for start, end, after in transport.query_windows[1:]:
        if (end - start) < (first_end - first_start) or start > first_start:
            later_progress = True
        if after:
            assert (start, end) != (first_start, first_end)
    assert later_progress
    hrefs_seen = [href for _, refs in transport.multiget_calls for href in refs]
    assert href_weekly in hrefs_seen


def test_yandex_incremental_does_not_advance_token_past_unprocessed_budget(
    db_session, credential_key
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="budget@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    store.update_sync_state(
        account,
        {
            "normalization_version": CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION,
            "calendars": {
                CALENDAR_HREF: {
                    "sync_token": "token-start",
                    "covered_window_end": (FIXED_NOW + timedelta(days=90)).isoformat(),
                }
            },
        },
    )
    db_session.commit()
    changed = []
    for index in range(5):
        start = TODAY_OCCURRENCE_START + timedelta(hours=index)
        uid = f"chg-{index}"
        changed.append(
            CalDavEvent(
                event_href=f"{CALENDAR_HREF}{uid}.ics",
                etag=f'"v1-{index}"',
                calendar_data=(
                    "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
                    f"UID:{uid}\nSUMMARY:Changed {index}\n"
                    f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}\n"
                    f"DTEND:{(start + timedelta(hours=1)).strftime('%Y%m%dT%H%M%SZ')}\n"
                    "END:VEVENT\nEND:VCALENDAR\n"
                ),
            )
        )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token-start")],
        query_events_by_calendar={CALENDAR_HREF: []},
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "token-start": CalDavFetchResult(
                    events=changed,
                    sync_token="token-done",
                )
            }
        },
    )
    sync = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: FIXED_NOW,
    )
    first = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=2)
    mutations = first["created"] + first["updated"] + first["tombstoned"]
    assert mutations <= 2
    assert first["created"] == 2
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert account.sync_state["calendars"][CALENDAR_HREF]["sync_token"] == "token-start"

    second = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    mutations_two = second["created"] + second["updated"] + second["tombstoned"]
    assert mutations_two <= 100
    assert second["created"] == 3
    count = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(Object.provider == "yandex_calendar", Object.user_id == BOOTSTRAP_USER_ID)
    )
    assert count == 5
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert account.sync_state["calendars"][CALENDAR_HREF]["sync_token"] == "token-done"


def test_yandex_tombstone_db_reads_are_bounded(db_session, credential_key) -> None:
    store, account = _yandex_account(db_session, credential_key, email="tombstone@yandex.ru")
    deleted_href = f"{CALENDAR_HREF}series.ics"
    missing_href = f"{CALENDAR_HREF}missing.ics"
    for index in range(12):
        start = TODAY_OCCURRENCE_START + timedelta(minutes=index)
        recid = start.strftime("%Y%m%dT%H%M%SZ")
        db_session.add(
            Object(
                user_id=BOOTSTRAP_USER_ID,
                kind="event",
                provider="yandex_calendar",
                external_id=build_external_id(CALENDAR_HREF, "series-uid", recid),
                origin="source",
                state="observed",
                title=f"Series {index}",
                start_at=start,
                due_at=start + timedelta(hours=1),
                occurred_at=start,
                metadata_={"event_href": deleted_href},
            )
        )
    kept_id = build_external_id(CALENDAR_HREF, "miss-uid", "20260909T100000Z")
    for index in range(8):
        start = TODAY_OCCURRENCE_START + timedelta(hours=index)
        recid = start.strftime("%Y%m%dT%H%M%SZ")
        db_session.add(
            Object(
                user_id=BOOTSTRAP_USER_ID,
                kind="event",
                provider="yandex_calendar",
                external_id=build_external_id(CALENDAR_HREF, "miss-uid", recid),
                origin="source",
                state="observed",
                title=f"Miss {index}",
                start_at=start,
                due_at=start + timedelta(hours=1),
                occurred_at=start,
                metadata_={"event_href": missing_href},
            )
        )
    store.update_sync_state(
        account,
        {
            "normalization_version": CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION,
            "calendars": {
                CALENDAR_HREF: {
                    "sync_token": "token-start",
                    "covered_window_end": (FIXED_NOW + timedelta(days=90)).isoformat(),
                }
            },
        },
    )
    db_session.commit()
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token-start")],
        query_events_by_calendar={CALENDAR_HREF: []},
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "token-start": CalDavFetchResult(
                    events=[],
                    sync_token="token-done",
                    deleted_hrefs=[deleted_href],
                )
            }
        },
    )
    sync = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: FIXED_NOW,
    )
    first = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=3)
    assert first["tombstoned"] == 3
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert account.sync_state["calendars"][CALENDAR_HREF]["sync_token"] == "token-start"
    series_deleted = db_session.scalars(
        select(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.metadata_["event_href"].as_string() == deleted_href,
            Object.status == "deleted",
        )
    ).all()
    assert len(series_deleted) == 3

    second = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert second["tombstoned"] == 9
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert account.sync_state["calendars"][CALENDAR_HREF]["sync_token"] == "token-done"
    series_all = db_session.scalars(
        select(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.metadata_["event_href"].as_string() == deleted_href,
        )
    ).all()
    assert len(series_all) == 12
    assert all(obj.status == "deleted" for obj in series_all)

    removed, complete = sync._tombstone_missing_occurrences(
        user_id=BOOTSTRAP_USER_ID,
        event_href=missing_href,
        returned_external_ids={kept_id},
        time_min=TODAY_OCCURRENCE_START - timedelta(days=1),
        time_max=TODAY_OCCURRENCE_START + timedelta(days=2),
        max_count=3,
    )
    assert removed == 3
    assert complete is False
    removed_two, complete_two = sync._tombstone_missing_occurrences(
        user_id=BOOTSTRAP_USER_ID,
        event_href=missing_href,
        returned_external_ids={kept_id},
        time_min=TODAY_OCCURRENCE_START - timedelta(days=1),
        time_max=TODAY_OCCURRENCE_START + timedelta(days=2),
        max_count=10,
    )
    assert complete_two is True
    assert removed + removed_two == 7
    missing_rows = db_session.scalars(
        select(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.metadata_["event_href"].as_string() == missing_href,
        )
    ).all()
    assert len(missing_rows) == 8
    kept = db_session.scalar(select(Object).where(Object.external_id == kept_id))
    assert kept is not None
    assert kept.status != "deleted"


def test_today_service_still_only_queries_event_objects(db_session) -> None:
    from app.db.models import Object as Obj

    db_session.add(
        Obj(
            user_id=BOOTSTRAP_USER_ID,
            kind="event",
            provider="google_calendar",
            origin="source",
            state="observed",
            title="Already materialized",
            start_at=TODAY_OCCURRENCE_START,
            due_at=TODAY_OCCURRENCE_START + timedelta(hours=1),
            occurred_at=TODAY_OCCURRENCE_START,
            metadata_={},
        )
    )
    db_session.commit()
    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(
        reference_at=FIXED_NOW,
        timezone="UTC",
    )
    assert len(snapshot["calendar_events"]) == 1
    assert snapshot["calendar_events"][0].title == "Already materialized"
