import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, or_, select

from app.api.deps import get_db
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.yandex.caldav_transport import (
    CalDavCalendar,
    CalDavEvent,
    CalDavFetchResult,
    CalDavHttpTransport,
    FakeCalDavTransport,
)
from app.connectors.yandex.calendar_credentials import YandexCalendarAccountStore
from app.connectors.yandex.calendar_normalize import (
    build_external_id,
    normalize_caldav_event,
    normalize_caldav_events,
    unescape_ical_text,
)
from app.connectors.yandex.calendar_sync import build_yandex_calendar_sync_service
from app.connectors.yandex.constants import CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION
from app.connectors.yandex.errors import (
    YandexCalDavError,
    YandexCalDavStaleSyncTokenError,
    YandexConnectorError,
)
from app.db.models import Object, User, YandexCalendarAccount
from app.main import app
from app.users.bootstrap import BOOTSTRAP_USER_ID

CALENDAR_HREF = "/calendars/user@yandex.ru/events-1/"
PRINCIPAL_HREF = "/principals/users/user@yandex.ru/"
HOME_HREF = "/calendars/user@yandex.ru/"
SHARED_EVENT_UID = "shared-corporate-evt"


def _steady_sync_state(
    calendars: dict,
    normalization_version: int = CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION,
) -> dict:
    return {
        "normalization_version": normalization_version,
        "calendars": calendars,
    }


def _sample_ical(
    event_uid: str = "evt-yandex-1",
    summary: str = "Standup",
    description: str = "Daily sync",
    dtstart: str = "20260829T100000Z",
    dtend: str = "20260829T110000Z",
    recurrence_id: str | None = None,
) -> str:
    recurrence_line = f"RECURRENCE-ID:{recurrence_id}\n" if recurrence_id else ""
    return (
        "BEGIN:VCALENDAR\n"
        "BEGIN:VEVENT\n"
        f"UID:{event_uid}\n"
        f"{recurrence_line}"
        f"SUMMARY:{summary}\n"
        f"DESCRIPTION:{description}\n"
        f"DTSTART:{dtstart}\n"
        f"DTEND:{dtend}\n"
        "LOCATION:Room B\n"
        "STATUS:CONFIRMED\n"
        "LAST-MODIFIED:20260828T080000Z\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )


def _event(
    event_uid: str,
    summary: str = "Standup",
    description: str = "Daily sync",
    dtstart: str = "20260829T100000Z",
    dtend: str = "20260829T110000Z",
    recurrence_id: str | None = None,
) -> CalDavEvent:
    return CalDavEvent(
        event_href=f"{CALENDAR_HREF}{event_uid}.ics",
        etag=f'"{event_uid}"',
        calendar_data=_sample_ical(
            event_uid,
            summary,
            description,
            dtstart,
            dtend,
            recurrence_id,
        ),
    )


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def client(db_session, auth_headers):
    from tests.conftest import AuthTestClient

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def test_normalize_caldav_event_matches_event_object_shape() -> None:
    normalized = normalize_caldav_event(
        _sample_ical(),
        calendar_href=CALENDAR_HREF,
        calendar_summary="Work",
        etag='"etag-1"',
        event_href=f"{CALENDAR_HREF}evt-yandex-1.ics",
    )
    assert normalized is not None
    assert normalized["kind"] == "event"
    assert normalized["provider"] == "yandex_calendar"
    assert normalized["external_id"] == build_external_id(CALENDAR_HREF, "evt-yandex-1")


def test_normalize_caldav_preserves_organizer_and_attendee_emails() -> None:
    ical = (
        "BEGIN:VEVENT\n"
        "UID:org-att-1\n"
        "SUMMARY:Review\n"
        "ORGANIZER;CN=Owner:mailto:owner@yandex.ru\n"
        "ATTENDEE;CN=Guest:mailto:guest@yandex.ru\n"
        "ATTENDEE:mailto:owner@yandex.ru\n"
        "DTSTART:20260829T100000Z\n"
        "DTEND:20260829T110000Z\n"
        "END:VEVENT\n"
    )
    events = normalize_caldav_events(ical, CALENDAR_HREF)
    assert len(events) == 1
    assert events[0]["metadata"]["organizer"] == "owner@yandex.ru"
    assert events[0]["metadata"]["attendees"] == [
        {"email": "guest@yandex.ru"},
        {"email": "owner@yandex.ru"},
    ]
    assert "attendees_truncated" not in events[0]["metadata"]


def test_normalize_caldav_marks_attendees_truncated() -> None:
    attendee_lines = "".join(
        f"ATTENDEE:mailto:g{index:02d}@yandex.ru\n" for index in range(21)
    )
    ical = (
        "BEGIN:VEVENT\n"
        "UID:many-att\n"
        "SUMMARY:Review\n"
        f"{attendee_lines}"
        "DTSTART:20260829T100000Z\n"
        "DTEND:20260829T110000Z\n"
        "END:VEVENT\n"
    )
    events = normalize_caldav_events(ical, CALENDAR_HREF)
    assert len(events[0]["metadata"]["attendees"]) == 20
    assert events[0]["metadata"]["attendees_truncated"] is True


def test_unescape_ical_text_decodes_newlines_and_punctuation() -> None:
    assert unescape_ical_text("Строка 1\\nСтрока 2\\n\\nСтрока 4") == (
        "Строка 1\nСтрока 2\n\nСтрока 4"
    )
    assert unescape_ical_text("Обсуждение\\, часть 2") == "Обсуждение, часть 2"
    assert unescape_ical_text("Комната\\; этаж 3") == "Комната; этаж 3"
    assert unescape_ical_text("path\\\\share") == "path\\share"
    assert unescape_ical_text("lower\\nupper\\N") == "lower\nupper\n"


def test_normalize_caldav_event_unescapes_description() -> None:
    ical = (
        "BEGIN:VEVENT\n"
        "UID:escape-test\n"
        "SUMMARY:Обсуждение\\, часть 2\n"
        "DESCRIPTION:Строка 1\\nСтрока 2\n"
        "LOCATION:Комната\\; этаж 3\n"
        "DTSTART:20260829T100000Z\n"
        "DTEND:20260829T110000Z\n"
        "END:VEVENT\n"
    )
    normalized = normalize_caldav_event(ical, calendar_href=CALENDAR_HREF)
    assert normalized is not None
    assert normalized["title"] == "Обсуждение, часть 2"
    assert normalized["body"] == "Строка 1\nСтрока 2"
    assert normalized["metadata"]["location"] == "Комната; этаж 3"


def test_normalize_moscow_tzid_to_utc() -> None:
    ical = (
        "BEGIN:VEVENT\n"
        "UID:tz-test\n"
        "DTSTART;TZID=Europe/Moscow:20260829T100000\n"
        "DTEND;TZID=Europe/Moscow:20260829T110000\n"
        "END:VEVENT\n"
    )
    events = normalize_caldav_events(ical, CALENDAR_HREF)
    assert len(events) == 1
    assert events[0]["start_at"] == datetime(2026, 8, 29, 7, 0, tzinfo=UTC)


def test_normalize_recurring_occurrences_have_distinct_external_ids() -> None:
    ical = (
        "BEGIN:VCALENDAR\n"
        "BEGIN:VEVENT\n"
        "UID:weekly-1\n"
        "RECURRENCE-ID:20260829T100000Z\n"
        "SUMMARY:Week 1\n"
        "DTSTART:20260829T100000Z\n"
        "DTEND:20260829T110000Z\n"
        "END:VEVENT\n"
        "BEGIN:VEVENT\n"
        "UID:weekly-1\n"
        "RECURRENCE-ID:20260905T100000Z\n"
        "SUMMARY:Week 2\n"
        "DTSTART:20260905T100000Z\n"
        "DTEND:20260905T110000Z\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )
    events = normalize_caldav_events(ical, CALENDAR_HREF)
    assert len(events) == 2
    ids = {event["external_id"] for event in events}
    assert len(ids) == 2


def test_normalize_filters_occurrences_outside_window() -> None:
    ical = (
        "BEGIN:VCALENDAR\n"
        "BEGIN:VEVENT\n"
        "UID:out-window\n"
        "SUMMARY:Old\n"
        "DTSTART:20200101T100000Z\n"
        "DTEND:20200101T110000Z\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )
    time_min = datetime(2026, 1, 1, tzinfo=UTC)
    time_max = datetime(2026, 12, 31, tzinfo=UTC)
    events = normalize_caldav_events(
        ical,
        CALENDAR_HREF,
        time_min=time_min,
        time_max=time_max,
    )
    assert events == []


class DiscoveryHttpClient:
    def __init__(self, principal_xml: str, home_xml: str) -> None:
        self._principal_xml = principal_xml
        self._home_xml = home_xml
        self.requests: list[tuple[str, str, str]] = []
        self.bodies: list[str] = []

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        depth = kwargs.get("headers", {}).get("Depth", "0")
        path = url.split("caldav.yandex.ru", 1)[-1]
        body = kwargs.get("content") or b""
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        self.requests.append((method, path, depth))
        self.bodies.append(body)
        if PRINCIPAL_HREF in path:
            return httpx.Response(200, text=self._principal_xml)
        if HOME_HREF in path:
            return httpx.Response(200, text=self._home_xml)
        raise AssertionError(f"unexpected request {method} {url}")


def test_caldav_discovery_uses_principal_then_calendar_home() -> None:
    principal_xml = (
        "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>"
        "<d:response><d:href>" + PRINCIPAL_HREF + "</d:href>"
        "<d:propstat><d:prop><c:calendar-home-set><d:href>" + HOME_HREF + "</d:href>"
        "</c:calendar-home-set></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
        "</d:response></d:multistatus>"
    )
    home_xml = (
        "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>"
        "<d:response><d:href>" + HOME_HREF + "</d:href>"
        "<d:propstat><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        "<d:response><d:href>" + CALENDAR_HREF + "</d:href>"
        "<d:propstat><d:prop><d:displayname>Work</d:displayname>"
        "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
        "<d:sync-token>token-home</d:sync-token>"
        "<c:supported-calendar-component-set><c:comp name='VEVENT'/></c:supported-calendar-component-set>"
        "</d:prop>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        "</d:multistatus>"
    )
    http = DiscoveryHttpClient(principal_xml, home_xml)
    transport = CalDavHttpTransport(
        email="user@yandex.ru",
        password="pass",
        http_client=http,
    )
    calendars = transport.discover_calendars(10)
    assert len(calendars) == 1
    assert calendars[0].href == CALENDAR_HREF
    assert calendars[0].supported_components == frozenset({"VEVENT"})
    assert http.requests[0] == ("PROPFIND", PRINCIPAL_HREF, "0")
    assert http.requests[1] == ("PROPFIND", HOME_HREF, "1")
    assert "<c:supported-calendar-component-set/>" in http.bodies[1]


def test_query_events_does_not_use_expand_on_yandex_incompatible_calendar_query() -> None:
    captured: dict[str, str] = {}

    class QueryHttpClient:
        def request(self, method: str, url: str, **kwargs) -> httpx.Response:
            captured["body"] = kwargs.get("content", b"").decode("utf-8")
            xml = "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'></d:multistatus>"
            return httpx.Response(207, text=xml)

    transport = CalDavHttpTransport(
        email="user@yandex.ru",
        password="pass",
        http_client=QueryHttpClient(),
    )
    time_min = datetime(2026, 1, 1, tzinfo=UTC)
    time_max = datetime(2026, 12, 31, tzinfo=UTC)
    transport.query_events(CALENDAR_HREF, time_min, time_max, 10)
    assert "<c:expand" not in captured["body"]
    assert "<c:calendar-data" not in captured["body"]
    assert "<d:getetag/>" in captured["body"]
    assert "<c:time-range" in captured["body"]
    assert "</c:filter>" in captured["body"]


def test_caldav_discovery_parses_vevent_and_vtodo_component_sets() -> None:
    principal_xml = (
        "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>"
        "<d:response><d:href>" + PRINCIPAL_HREF + "</d:href>"
        "<d:propstat><d:prop><c:calendar-home-set><d:href>" + HOME_HREF + "</d:href>"
        "</c:calendar-home-set></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
        "</d:response></d:multistatus>"
    )
    events_href = "/calendars/user@yandex.ru/events-18154946/"
    todos_href = "/calendars/user@yandex.ru/todos-7121590/"
    home_xml = (
        "<D:multistatus xmlns:D='DAV:'>"
        "<D:response><href xmlns='DAV:'>" + events_href + "</href>"
        "<D:propstat><D:prop>"
        "<D:displayname>Мои события</D:displayname>"
        "<D:resourcetype><C:calendar xmlns:C='urn:ietf:params:xml:ns:caldav'/><D:collection/></D:resourcetype>"
        "<C:supported-calendar-component-set xmlns:C='urn:ietf:params:xml:ns:caldav'>"
        "<C:comp name='VEVENT'/></C:supported-calendar-component-set>"
        "</D:prop><status xmlns='DAV:'>HTTP/1.1 200 OK</status></D:propstat></D:response>"
        "<D:response><href xmlns='DAV:'>" + todos_href + "</href>"
        "<D:propstat><D:prop>"
        "<D:displayname>Не забыть</D:displayname>"
        "<D:resourcetype><C:calendar xmlns:C='urn:ietf:params:xml:ns:caldav'/><D:collection/></D:resourcetype>"
        "<C:supported-calendar-component-set xmlns:C='urn:ietf:params:xml:ns:caldav'>"
        "<C:comp name='VTODO'/></C:supported-calendar-component-set>"
        "</D:prop><status xmlns='DAV:'>HTTP/1.1 200 OK</status></D:propstat></D:response>"
        "</D:multistatus>"
    )
    http = DiscoveryHttpClient(principal_xml, home_xml)
    transport = CalDavHttpTransport(
        email="user@yandex.ru",
        password="pass",
        http_client=http,
    )
    calendars = transport.discover_calendars(10)
    by_href = {calendar.href: calendar for calendar in calendars}
    assert by_href[events_href].supported_components == frozenset({"VEVENT"})
    assert by_href[todos_href].supported_components == frozenset({"VTODO"})
    missing_xml = (
        "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>"
        "<d:response><d:href>" + CALENDAR_HREF + "</d:href>"
        "<d:propstat><d:prop><d:displayname>Work</d:displayname>"
        "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
        "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        "</d:multistatus>"
    )
    missing = CalDavHttpTransport(
        email="user@yandex.ru",
        password="pass",
        http_client=DiscoveryHttpClient(principal_xml, missing_xml),
    ).discover_calendars(10)
    assert missing[0].supported_components == frozenset()


def test_calendar_multiget_uses_expand_with_bounded_range() -> None:
    captured: dict[str, str] = {}
    query_xml = (
        "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>"
        "<d:response><d:href>" + CALENDAR_HREF + "evt-a.ics</d:href>"
        "<d:propstat><d:prop><d:getetag>etag-a</d:getetag></d:prop>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        "</d:multistatus>"
    )
    multiget_xml = (
        "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>"
        "<d:response><d:href>" + CALENDAR_HREF + "evt-a.ics</d:href>"
        "<d:propstat><d:prop><c:calendar-data>BEGIN:VEVENT\nUID:evt-a\nEND:VEVENT</c:calendar-data>"
        "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        "</d:multistatus>"
    )
    call = 0

    class TwoStepHttpClient:
        def request(self, method: str, url: str, **kwargs) -> httpx.Response:
            nonlocal call
            call += 1
            body = kwargs.get("content", b"").decode("utf-8")
            if "calendar-query" in body:
                captured["query_body"] = body
                return httpx.Response(207, text=query_xml)
            captured["multiget_body"] = body
            return httpx.Response(207, text=multiget_xml)

    transport = CalDavHttpTransport(
        email="user@yandex.ru",
        password="pass",
        http_client=TwoStepHttpClient(),
    )
    time_min = datetime(2026, 1, 1, tzinfo=UTC)
    time_max = datetime(2026, 12, 31, tzinfo=UTC)
    result = transport.query_events(CALENDAR_HREF, time_min, time_max, 10)
    assert call == 2
    assert len(result.events) == 1
    assert "<c:expand" in captured["multiget_body"]
    assert "20260101T000000Z" in captured["multiget_body"]
    assert "20261231T000000Z" in captured["multiget_body"]
    assert "calendar-multiget" in captured["multiget_body"]


def test_sync_collection_uses_depth_zero_and_dav_limit_wrapper() -> None:
    captured: dict[str, str] = {}

    class SyncHttpClient:
        def request(self, method: str, url: str, **kwargs) -> httpx.Response:
            captured["depth"] = kwargs["headers"]["Depth"]
            captured["body"] = kwargs.get("content", b"").decode("utf-8")
            xml = (
                "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>"
                "<d:sync-token>token-next</d:sync-token></d:multistatus>"
            )
            return httpx.Response(200, text=xml)

    transport = CalDavHttpTransport(
        email="user@yandex.ru",
        password="pass",
        http_client=SyncHttpClient(),
    )
    time_min = datetime(2026, 1, 1, tzinfo=UTC)
    time_max = datetime(2026, 12, 31, tzinfo=UTC)
    transport.sync_collection(CALENDAR_HREF, "token-start", 100, time_min, time_max)
    assert captured["depth"] == "0"
    assert "<d:limit><d:nresults>100</d:nresults></d:limit>" in captured["body"]
    assert "<c:expand" in captured["body"]


def test_parse_truncated_multistatus_returns_partial_token() -> None:
    xml = (
        "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>"
        "<d:response><d:href>" + CALENDAR_HREF + "evt-1.ics</d:href>"
        "<d:propstat><d:prop><c:calendar-data>BEGIN:VEVENT\nUID:trunc-1\nEND:VEVENT</c:calendar-data>"
        "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        "<d:response><d:href>" + CALENDAR_HREF + "</d:href>"
        "<d:status>HTTP/1.1 507 Insufficient Storage</d:status></d:response>"
        "<d:sync-token>partial-token</d:sync-token>"
        "</d:multistatus>"
    )
    transport = CalDavHttpTransport(email="user@yandex.ru", password="pass")
    events, token, deleted, truncated = transport._parse_event_multistatus(xml)
    assert len(events) == 1
    assert token == "partial-token"
    assert truncated is True
    assert deleted == []


def test_sync_collection_batches_with_partial_tokens(db_session, credential_key: str) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="batch@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    store.update_sync_state(
        account,
        _steady_sync_state({CALENDAR_HREF: {"sync_token": "token-start"}}),
    )
    db_session.commit()

    all_events = [_event(f"evt-{index}") for index in range(250)]
    batches: dict[str, CalDavFetchResult] = {
        "token-start": CalDavFetchResult(
            events=all_events[0:100],
            sync_token="token-100",
        ),
        "token-100": CalDavFetchResult(
            events=all_events[100:200],
            sync_token="token-200",
        ),
        "token-200": CalDavFetchResult(
            events=all_events[200:250],
            sync_token="token-final",
        ),
    }
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token-start")],
        sync_batches_by_calendar={CALENDAR_HREF: batches},
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
    )

    first = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert first["created"] == 100
    assert account.sync_state["calendars"][CALENDAR_HREF]["sync_token"] == "token-100"

    second = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert second["created"] == 100
    assert account.sync_state["calendars"][CALENDAR_HREF]["sync_token"] == "token-200"

    third = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert third["created"] == 50
    assert account.sync_state["calendars"][CALENDAR_HREF]["sync_token"] == "token-final"

    count = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.provider == "yandex_calendar")
    )
    assert count == 250


def test_sync_collection_tombstones_deleted_event(db_session, credential_key: str) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="delete@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    event = _event("evt-delete")
    db_session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="event",
            provider="yandex_calendar",
            external_id=build_external_id(CALENDAR_HREF, "evt-delete"),
            origin="source",
            state="observed",
            title="Standup",
            metadata_={"event_href": event.event_href},
        )
    )
    store.update_sync_state(
        account,
        _steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "t2",
                    "covered_window_end": "2026-12-31T00:00:00+00:00",
                }
            }
        ),
    )
    db_session.commit()

    delete_transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="t2")],
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "t2": CalDavFetchResult(
                    events=[],
                    sync_token="t3",
                    deleted_hrefs=[event.event_href],
                )
            }
        },
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: delete_transport,
    )
    result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    assert result["tombstoned"] == 1
    obj = db_session.scalar(
        select(Object).where(
            Object.external_id == build_external_id(CALENDAR_HREF, "evt-delete")
        )
    )
    assert obj is not None
    assert obj.status == "deleted"
    assert obj.metadata_["caldav_deleted"] is True


def test_no_db_transaction_during_caldav_network(db_session, credential_key: str) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="tx@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    db_session.commit()

    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="t1")],
        query_events_by_calendar={CALENDAR_HREF: [_event("evt-tx")]},
        tx_checker=lambda: db_session.in_transaction(),
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    assert transport.discover_calls == 1
    assert CALENDAR_HREF in transport.query_calls


def test_malformed_caldav_xml_raises_controlled_error() -> None:
    transport = CalDavHttpTransport(email="user@yandex.ru", password="pass")
    with pytest.raises(YandexCalDavError, match="xml malformed"):
        transport._parse_event_multistatus("<not-xml")


def test_parse_multistatus_uses_ok_propstat_when_multiple_present() -> None:
    xml = (
        "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>"
        "<d:response><d:href>" + CALENDAR_HREF + "evt.ics</d:href>"
        "<d:propstat><d:status>HTTP/1.1 404 Not Found</d:status></d:propstat>"
        "<d:propstat><d:prop><d:getetag>\"e1\"</d:getetag>"
        "<c:calendar-data>BEGIN:VEVENT\nUID:multi-prop\nEND:VEVENT</c:calendar-data>"
        "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
        "</d:response></d:multistatus>"
    )
    transport = CalDavHttpTransport(email="user@yandex.ru", password="pass")
    events, _token, _deleted, truncated = transport._parse_event_multistatus(xml)
    assert len(events) == 1
    assert "UID:multi-prop" in events[0].calendar_data
    assert truncated is False


def test_parse_multistatus_merges_split_ok_propstats() -> None:
    xml = (
        "<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>"
        "<d:response><d:href>" + CALENDAR_HREF + "evt-split.ics</d:href>"
        "<d:propstat><d:prop><d:getetag>\"etag-split\"</d:getetag></d:prop>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
        "<d:propstat><d:prop><c:calendar-data>BEGIN:VEVENT\nUID:split-prop\nEND:VEVENT</c:calendar-data>"
        "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
        "</d:response></d:multistatus>"
    )
    transport = CalDavHttpTransport(email="user@yandex.ru", password="pass")
    events, _, _, _ = transport._parse_event_multistatus(xml)
    assert len(events) == 1
    assert events[0].etag == '"etag-split"'
    assert "UID:split-prop" in events[0].calendar_data


def test_sync_collection_raises_when_fake_exceeds_limit() -> None:
    transport = FakeCalDavTransport(
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "token-start": CalDavFetchResult(
                    events=[_event(f"evt-{i}") for i in range(101)],
                    sync_token="token-next",
                )
            }
        },
    )
    with pytest.raises(YandexCalDavError, match="exceeded requested result limit"):
        transport.sync_collection(
            CALENDAR_HREF,
            "token-start",
            100,
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 12, 31, tzinfo=UTC),
        )


def test_bounded_yandex_calendar_sync_creates_observed_event_objects(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="user@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    db_session.commit()

    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token-1")],
        query_events_by_calendar={CALENDAR_HREF: [_event("evt-yandex-1")]},
        sync_tokens_by_calendar={CALENDAR_HREF: "token-1"},
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
    )
    result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)

    assert result["created"] == 1
    assert result["jobs_enqueued"] == 1

    obj = db_session.scalar(
        select(Object).where(
            Object.provider == "yandex_calendar",
            Object.external_id == build_external_id(CALENDAR_HREF, "evt-yandex-1"),
        )
    )
    assert obj is not None
    assert obj.user_id == BOOTSTRAP_USER_ID


def test_yandex_calendar_resync_unchanged_without_duplicate_jobs(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="owner@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    store.update_sync_state(
        account,
        _steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "token-1",
                    "covered_window_end": (now + timedelta(days=90)).isoformat(),
                }
            }
        ),
    )
    db_session.commit()

    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token-1")],
        query_events_by_calendar={CALENDAR_HREF: [_event("evt-yandex-2")]},
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "token-1": CalDavFetchResult(
                    events=[_event("evt-yandex-2")],
                    sync_token="token-3",
                ),
                "token-3": CalDavFetchResult(
                    events=[_event("evt-yandex-2")],
                    sync_token="token-3",
                ),
            }
        },
        sync_tokens_by_calendar={CALENDAR_HREF: "token-1"},
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: now,
    )
    first = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    second = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)

    assert first["created"] == 1
    assert second["unchanged"] >= 1
    assert second["jobs_enqueued"] == 0
    assert transport.sync_collection_calls == [
        (CALENDAR_HREF, "token-1", 100),
        (CALENDAR_HREF, "token-3", 100),
    ]


def test_two_users_share_same_external_id_under_different_user_id(
    db_session, credential_key: str
) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()
    shared_external_id = build_external_id(CALENDAR_HREF, SHARED_EVENT_UID)

    for user_id in (BOOTSTRAP_USER_ID, user_b_id):
        store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
        account = store.upsert_account(
            user_id=user_id,
            email=f"{user_id}@yandex.ru",
            app_password="calendar-app-password",
            caldav_host="caldav.yandex.ru",
        )
        db_session.flush()
        transport = FakeCalDavTransport(
            calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
            query_events_by_calendar={
                CALENDAR_HREF: [_event(SHARED_EVENT_UID, summary=str(user_id))]
            },
        )
        sync_service = build_yandex_calendar_sync_service(
            session=db_session,
            credential_key=credential_key,
            days_back=60,
            days_forward=90,
            default_limit=100,
            max_limit=100,
            max_calendars=10,
            transport_factory=lambda snapshot, _transport=transport: _transport,
        )
        sync_service.sync_account(account.id, user_id, limit=1)

    objs = list(
        db_session.scalars(
            select(Object).where(
                Object.provider == "yandex_calendar",
                Object.external_id == shared_external_id,
            )
        ).all()
    )
    assert len(objs) == 2
    assert {obj.user_id for obj in objs} == {BOOTSTRAP_USER_ID, user_b_id}


def test_user_b_cannot_sync_user_a_yandex_calendar_account(
    db_session, credential_key: str
) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()

    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="owner@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    db_session.commit()

    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: FakeCalDavTransport(
            calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
            query_events_by_calendar={CALENDAR_HREF: [_event("evt-yandex-3")]},
        ),
    )
    with pytest.raises(YandexConnectorError, match="yandex calendar account not found"):
        sync_service.sync_account(account.id, user_b_id, limit=1)


def _master_weekly_rrule_ical() -> str:
    return (
        "BEGIN:VCALENDAR\n"
        "BEGIN:VEVENT\n"
        "UID:weekly-expand\n"
        "SUMMARY:Weekly meeting\n"
        "DTSTART:20260829T100000Z\n"
        "DTEND:20260829T110000Z\n"
        "RRULE:FREQ=WEEKLY;INTERVAL=1;COUNT=5\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )


def test_bounded_backfill_multiget_expands_recurring_occurrences(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="multiget@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    db_session.commit()

    event_href = f"{CALENDAR_HREF}weekly-expand.ics"
    master = CalDavEvent(
        event_href=event_href,
        etag='"weekly-master"',
        calendar_data=_master_weekly_rrule_ical(),
    )
    expanded = CalDavEvent(
        event_href=event_href,
        etag='"weekly-master"',
        calendar_data=_expanded_recurring_ical(4),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="steady")],
        query_events_by_calendar={CALENDAR_HREF: [master]},
        multiget_events_by_calendar={CALENDAR_HREF: {event_href: expanded}},
        sync_tokens_by_calendar={CALENDAR_HREF: "steady"},
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )
    result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    objs = list(
        db_session.scalars(
            select(Object).where(
                Object.user_id == BOOTSTRAP_USER_ID,
                Object.provider == "yandex_calendar",
            )
        ).all()
    )

    assert result["created"] == 4
    assert len(transport.multiget_calls) >= 1
    assert len(objs) == 4
    external_ids = {obj.external_id for obj in objs}
    assert len(external_ids) == 4
    assert all("weekly-expand" in external_id for external_id in external_ids)


def test_bounded_reconciliation_rerun_no_duplicate_embed_jobs(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="rerun@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    db_session.commit()

    event_href = f"{CALENDAR_HREF}weekly-expand.ics"
    master = CalDavEvent(
        event_href=event_href,
        etag='"weekly-master"',
        calendar_data=_master_weekly_rrule_ical(),
    )
    expanded = CalDavEvent(
        event_href=event_href,
        etag='"weekly-master"',
        calendar_data=_expanded_recurring_ical(3),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="steady")],
        query_events_by_calendar={CALENDAR_HREF: [master]},
        multiget_events_by_calendar={CALENDAR_HREF: {event_href: expanded}},
        sync_tokens_by_calendar={CALENDAR_HREF: "steady"},
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )
    first = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert first["created"] == 3

    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    calendars_state = dict(account.sync_state.get("calendars", {}))
    state = dict(calendars_state.get(CALENDAR_HREF, {}))
    state.pop("sync_token", None)
    state["pending_sync_token"] = "steady"
    calendars_state[CALENDAR_HREF] = state
    store.update_sync_state(account, _steady_sync_state(calendars_state))
    db_session.commit()

    second = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert second["unchanged"] >= 3
    assert second["jobs_enqueued"] == 0


def _expanded_recurring_ical(occurrence_count: int) -> str:
    lines = ["BEGIN:VCALENDAR"]
    base = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)
    for index in range(occurrence_count):
        start = base + timedelta(days=index)
        end = start + timedelta(hours=1)
        recurrence_id = start.strftime("%Y%m%dT%H%M%SZ")
        lines.extend(
            [
                "BEGIN:VEVENT",
                "UID:weekly-expand",
                f"RECURRENCE-ID:{recurrence_id}",
                f"SUMMARY:Occurrence {index}",
                f"DTSTART:{recurrence_id}",
                f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\n".join(lines) + "\n"


def test_incremental_sync_persists_token_after_all_occurrences_in_resource(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="expand@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    store.update_sync_state(
        account,
        _steady_sync_state({CALENDAR_HREF: {"sync_token": "token-2"}}),
    )
    db_session.commit()

    expanded_event = CalDavEvent(
        event_href=f"{CALENDAR_HREF}weekly-expand.ics",
        etag='"weekly-expand"',
        calendar_data=_expanded_recurring_ical(20),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token-2")],
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "token-2": CalDavFetchResult(
                    events=[expanded_event],
                    sync_token="token-3",
                )
            }
        },
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
    )
    result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=10)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert result["created"] == 10
    assert account.sync_state["calendars"][CALENDAR_HREF]["sync_token"] == "token-2"

    second = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=10)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert second["created"] == 10
    assert account.sync_state["calendars"][CALENDAR_HREF]["sync_token"] == "token-3"


def test_deletion_tombstones_all_occurrences_for_event_href(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="multi-del@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    db_session.commit()

    event_href = f"{CALENDAR_HREF}weekly-expand.ics"
    occurrences = normalize_caldav_events(_expanded_recurring_ical(3), CALENDAR_HREF, event_href=event_href)
    for normalized in occurrences:
        db_session.add(
            Object(
                user_id=BOOTSTRAP_USER_ID,
                kind=normalized["kind"],
                provider=normalized["provider"],
                external_id=normalized["external_id"],
                origin=normalized["origin"],
                state=normalized["state"],
                title=normalized["title"],
                metadata_=normalized["metadata"],
            )
        )
    db_session.commit()

    store.update_sync_state(
        account,
        _steady_sync_state({CALENDAR_HREF: {"sync_token": "token-del"}}),
    )
    db_session.commit()

    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token-del")],
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "token-del": CalDavFetchResult(
                    events=[],
                    sync_token="token-del-2",
                    deleted_hrefs=[event_href],
                )
            }
        },
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
    )
    result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=10)
    objs = list(
        db_session.scalars(
            select(Object).where(
                Object.user_id == BOOTSTRAP_USER_ID,
                Object.provider == "yandex_calendar",
                Object.metadata_["event_href"].as_string() == event_href,
            )
        ).all()
    )
    assert result["tombstoned"] == 3
    assert len(objs) == 3
    assert all(obj.status == "deleted" for obj in objs)


def test_deletion_does_not_touch_other_user_same_event_href(
    db_session, credential_key: str
) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()

    event_href = f"{CALENDAR_HREF}shared-delete.ics"
    for user_id in (BOOTSTRAP_USER_ID, user_b_id):
        db_session.add(
            Object(
                user_id=user_id,
                kind="event",
                provider="yandex_calendar",
                external_id=build_external_id(CALENDAR_HREF, f"evt-{user_id}"),
                origin="source",
                state="observed",
                title="Shared",
                metadata_={"event_href": event_href},
            )
        )
    db_session.commit()

    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="iso-del@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    store.update_sync_state(
        account,
        _steady_sync_state({CALENDAR_HREF: {"sync_token": "token-iso"}}),
    )
    db_session.commit()

    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token-iso")],
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "token-iso": CalDavFetchResult(
                    events=[],
                    sync_token="token-iso-2",
                    deleted_hrefs=[event_href],
                )
            }
        },
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)

    owner = db_session.scalar(
        select(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.metadata_["event_href"].as_string() == event_href,
        )
    )
    other = db_session.scalar(
        select(Object).where(
            Object.user_id == user_b_id,
            Object.metadata_["event_href"].as_string() == event_href,
        )
    )
    assert owner is not None and owner.status == "deleted"
    assert other is not None and other.status != "deleted"


CALENDAR_B_HREF = "/calendars/user@yandex.ru/events-2/"


def test_no_db_transaction_leak_after_noop_deletion_before_next_calendar(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="tx2@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    store.update_sync_state(
        account,
        _steady_sync_state(
            {
                CALENDAR_HREF: {"sync_token": "token-a"},
                CALENDAR_B_HREF: {
                    "sync_token": "token-b",
                    "covered_window_end": "2026-12-31T00:00:00+00:00",
                },
            }
        ),
    )
    db_session.commit()

    tx_checks: list[bool] = []

    class TxTrackingTransport(FakeCalDavTransport):
        def query_events(self, calendar_href, time_min, time_max, max_results, **kwargs):
            tx_checks.append(db_session.in_transaction())
            return super().query_events(
                calendar_href, time_min, time_max, max_results, **kwargs
            )

        def sync_collection(self, calendar_href, sync_token, max_results, time_min, time_max):
            tx_checks.append(db_session.in_transaction())
            return super().sync_collection(
                calendar_href, sync_token, max_results, time_min, time_max
            )

    transport = TxTrackingTransport(
        calendars=[
            CalDavCalendar(href=CALENDAR_HREF, display_name="A", sync_token="token-a"),
            CalDavCalendar(href=CALENDAR_B_HREF, display_name="B", sync_token="token-b"),
        ],
        calendar_order=[CALENDAR_HREF, CALENDAR_B_HREF],
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "token-a": CalDavFetchResult(
                    events=[],
                    sync_token="token-a-2",
                    deleted_hrefs=[f"{CALENDAR_HREF}unknown.ics"],
                )
            },
            CALENDAR_B_HREF: {
                "token-b": CalDavFetchResult(
                    events=[_event("evt-b", summary="Calendar B")],
                    sync_token="token-b-2",
                )
            },
        },
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)

    assert transport.sync_collection_calls[:2] == [
        (CALENDAR_HREF, "token-a", 100),
        (CALENDAR_B_HREF, "token-b", 100),
    ]
    assert transport.query_calls == [CALENDAR_HREF, CALENDAR_B_HREF]
    assert tx_checks
    assert all(flag is False for flag in tx_checks)


def test_yandex_calendar_connect_api_does_not_return_app_password(
    client, db_session, credential_key: str, monkeypatch: pytest.MonkeyPatch
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
    response = client.post(
        "/connectors/yandex/calendar/connect",
        json={
            "email": "calendar@yandex.ru",
            "app_password": "secret-calendar-password",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "calendar@yandex.ru"
    assert "app_password" not in body
    assert "secret-calendar-password" not in response.text

    account = db_session.scalar(
        select(YandexCalendarAccount).where(YandexCalendarAccount.email == "calendar@yandex.ru")
    )
    assert account is not None
    assert account.user_id == BOOTSTRAP_USER_ID


def _events_in_window(count: int, window_start: datetime, window_days: int) -> list[CalDavEvent]:
    events: list[CalDavEvent] = []
    for index in range(count):
        day_offset = (index * window_days) // max(count, 1)
        day = window_start + timedelta(days=day_offset)
        start = day.strftime("%Y%m%dT%H%M%SZ")
        end = (day + timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
        events.append(_event(f"evt-{index:03d}", dtstart=start, dtend=end))
    return events


def test_backfill_imports_full_window_before_steady_state_token(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="backfill@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    db_session.commit()

    base_day = datetime(2026, 6, 29, 10, 0, tzinfo=UTC)
    all_events = _events_in_window(180, base_day, 150)
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="steady-token")],
        query_events_by_calendar={CALENDAR_HREF: all_events},
        sync_tokens_by_calendar={CALENDAR_HREF: "steady-token"},
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: now,
    )

    first = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    state = account.sync_state["calendars"][CALENDAR_HREF]
    assert first["created"] == 100
    assert "sync_token" not in state
    assert state.get("backfill_cursor") is not None

    second = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    state = account.sync_state["calendars"][CALENDAR_HREF]
    assert second["created"] >= 78
    assert state["sync_token"] == "steady-token"
    assert state.get("backfill_cursor") is None

    count = db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.provider == "yandex_calendar",
            Object.user_id == BOOTSTRAP_USER_ID,
        )
    )
    assert count >= 178


def test_future_horizon_reconciliation_imports_newly_visible_event(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="horizon@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    initial_now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    initial_window_max = initial_now + timedelta(days=90)
    store.update_sync_state(
        account,
        _steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "steady-1",
                    "covered_window_end": initial_window_max.isoformat(),
                }
            }
        ),
    )
    db_session.commit()

    future_day = initial_now + timedelta(days=100)
    future_start = future_day.strftime("%Y%m%dT%H%M%SZ")
    future_end = (future_day + timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
    future_event = _event(
        "evt-future-horizon",
        summary="Future horizon",
        dtstart=future_start,
        dtend=future_end,
    )
    current_now = initial_now + timedelta(days=15)
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="steady-1")],
        query_events_by_calendar={CALENDAR_HREF: [future_event]},
        sync_tokens_by_calendar={CALENDAR_HREF: "steady-1"},
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: current_now,
    )
    result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert result["created"] == 1
    obj = db_session.scalar(
        select(Object).where(
            Object.external_id == build_external_id(CALENDAR_HREF, "evt-future-horizon")
        )
    )
    assert obj is not None


def test_incremental_reconcile_tombstones_removed_recurring_occurrences(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="reconcile@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    event_href = f"{CALENDAR_HREF}weekly-expand.ics"
    for normalized in normalize_caldav_events(
        _expanded_recurring_ical(5), CALENDAR_HREF, event_href=event_href
    ):
        db_session.add(
            Object(
                user_id=BOOTSTRAP_USER_ID,
                kind=normalized["kind"],
                provider=normalized["provider"],
                external_id=normalized["external_id"],
                origin=normalized["origin"],
                state=normalized["state"],
                title=normalized["title"],
                start_at=normalized.get("start_at"),
                due_at=normalized.get("due_at"),
                metadata_=normalized["metadata"],
            )
        )
    store.update_sync_state(
        account,
        _steady_sync_state(
            {CALENDAR_HREF: {"sync_token": "token-rec", "covered_window_end": "2026-12-31T00:00:00+00:00"}}
        ),
    )
    db_session.commit()

    changed_event = CalDavEvent(
        event_href=event_href,
        etag='"weekly-expand-v2"',
        calendar_data=_expanded_recurring_ical(3),
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token-rec")],
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "token-rec": CalDavFetchResult(
                    events=[changed_event],
                    sync_token="token-rec-2",
                )
            }
        },
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )
    result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    objs = list(
        db_session.scalars(
            select(Object).where(
                Object.user_id == BOOTSTRAP_USER_ID,
                Object.metadata_["event_href"].as_string() == event_href,
            )
        ).all()
    )
    assert result["tombstoned"] == 2
    active = [obj for obj in objs if obj.status != "deleted"]
    tombstoned = [obj for obj in objs if obj.status == "deleted"]
    assert len(active) == 3
    assert len(tombstoned) == 2


def test_reconcile_does_not_touch_other_user_same_event_href(
    db_session, credential_key: str
) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()

    event_href = f"{CALENDAR_HREF}weekly-expand.ics"
    for user_id in (BOOTSTRAP_USER_ID, user_b_id):
        for normalized in normalize_caldav_events(
            _expanded_recurring_ical(5), CALENDAR_HREF, event_href=event_href
        ):
            db_session.add(
                Object(
                    user_id=user_id,
                    kind=normalized["kind"],
                    provider=normalized["provider"],
                    external_id=normalized["external_id"],
                    origin=normalized["origin"],
                    state=normalized["state"],
                    title=normalized["title"],
                    start_at=normalized.get("start_at"),
                    due_at=normalized.get("due_at"),
                    metadata_=normalized["metadata"],
                )
            )
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="reconcile-iso@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    store.update_sync_state(
        account,
        _steady_sync_state({CALENDAR_HREF: {"sync_token": "token-iso-rec"}}),
    )
    db_session.commit()

    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token-iso-rec")],
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "token-iso-rec": CalDavFetchResult(
                    events=[
                        CalDavEvent(
                            event_href=event_href,
                            etag='"v2"',
                            calendar_data=_expanded_recurring_ical(3),
                        )
                    ],
                    sync_token="token-iso-rec-2",
                )
            }
        },
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)

    owner_active = list(
        db_session.scalars(
            select(Object).where(
                Object.user_id == BOOTSTRAP_USER_ID,
                Object.metadata_["event_href"].as_string() == event_href,
                or_(Object.status.is_(None), Object.status != "deleted"),
            )
        ).all()
    )
    other_active = list(
        db_session.scalars(
            select(Object).where(
                Object.user_id == user_b_id,
                Object.metadata_["event_href"].as_string() == event_href,
                or_(Object.status.is_(None), Object.status != "deleted"),
            )
        ).all()
    )
    assert len(owner_active) == 3
    assert len(other_active) == 5


def test_stale_sync_token_resets_to_bounded_backfill(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="stale@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    store.update_sync_state(
        account,
        _steady_sync_state(
            {CALENDAR_HREF: {"sync_token": "stale-token", "covered_window_end": "2026-12-31T00:00:00+00:00"}}
        ),
    )
    db_session.commit()

    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="fresh-token")],
        query_events_by_calendar={CALENDAR_HREF: [_event("evt-stale-recover")]},
        sync_tokens_by_calendar={CALENDAR_HREF: "fresh-token"},
        stale_sync_tokens={"stale-token"},
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: now,
    )
    result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    state = account.sync_state["calendars"][CALENDAR_HREF]

    assert result["created"] == 1
    assert state["sync_token"] == "fresh-token"
    assert state.get("backfill_cursor") is None
    assert transport.sync_collection_calls == [(CALENDAR_HREF, "stale-token", 100)]
    assert CALENDAR_HREF in transport.query_calls


def test_backfill_preserves_baseline_sync_token_and_catches_post_baseline_change(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="baseline@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    db_session.commit()

    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    base_day = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    all_events = _events_in_window(80, base_day, 10)

    class BaselineTokenTransport(FakeCalDavTransport):
        def discover_calendars(self, max_results: int) -> list[CalDavCalendar]:
            self.discover_calls += 1
            token = "T2" if self.discover_calls > 1 else "T1"
            return [
                CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=token)
            ]

    transport = BaselineTokenTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="T1")],
        query_events_by_calendar={CALENDAR_HREF: all_events},
        sync_tokens_by_calendar={CALENDAR_HREF: "T1"},
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "T1": CalDavFetchResult(
                    events=[_event("evt-000", summary="Changed after baseline")],
                    sync_token="T1-after",
                )
            }
        },
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: now,
    )

    first = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=50)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    state = account.sync_state["calendars"][CALENDAR_HREF]
    assert first["created"] == 50
    assert state["pending_sync_token"] == "T1"
    assert "sync_token" not in state

    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    state = account.sync_state["calendars"][CALENDAR_HREF]
    assert state["sync_token"] == "T1"
    assert state.get("pending_sync_token") is None
    assert transport.discover_calls >= 2

    third = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=10)
    assert third["updated"] == 1
    assert transport.sync_collection_calls[0] == (CALENDAR_HREF, "T1", 100)


def test_dense_backfill_slice_splits_and_imports_all_resources(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="dense@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    db_session.commit()

    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    base = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    dense_events: list[CalDavEvent] = []
    for index in range(150):
        start = base + timedelta(hours=index)
        start_s = start.strftime("%Y%m%dT%H%M%SZ")
        end_s = (start + timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
        dense_events.append(_event(f"dense-{index:03d}", dtstart=start_s, dtend=end_s))

    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="dense-token")],
        query_events_by_calendar={CALENDAR_HREF: dense_events},
        sync_tokens_by_calendar={CALENDAR_HREF: "dense-token"},
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: now,
    )

    first = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    state = account.sync_state["calendars"][CALENDAR_HREF]
    assert first["created"] == 100
    assert "sync_token" not in state
    assert state.get("backfill_cursor") is not None

    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    state = account.sync_state["calendars"][CALENDAR_HREF]
    assert state["sync_token"] == "dense-token"
    assert state.get("backfill_cursor") is None

    count = db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.provider == "yandex_calendar",
            Object.user_id == BOOTSTRAP_USER_ID,
        )
    )
    assert count == 150


def test_incremental_reconcile_tombstones_when_changed_resource_has_one_vevent(
    db_session, credential_key: str
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="single-vevent@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    event_href = f"{CALENDAR_HREF}single-series.ics"
    for normalized in normalize_caldav_events(
        _expanded_recurring_ical(5), CALENDAR_HREF, event_href=event_href
    ):
        db_session.add(
            Object(
                user_id=BOOTSTRAP_USER_ID,
                kind=normalized["kind"],
                provider=normalized["provider"],
                external_id=normalized["external_id"],
                origin=normalized["origin"],
                state=normalized["state"],
                title=normalized["title"],
                start_at=normalized.get("start_at"),
                due_at=normalized.get("due_at"),
                metadata_=normalized["metadata"],
            )
        )
    store.update_sync_state(
        account,
        _steady_sync_state(
            {CALENDAR_HREF: {"sync_token": "token-single", "covered_window_end": "2026-12-31T00:00:00+00:00"}}
        ),
    )
    db_session.commit()

    single_occurrence_ical = (
        "BEGIN:VCALENDAR\n"
        "BEGIN:VEVENT\n"
        "UID:weekly-expand\n"
        "RECURRENCE-ID:20260829T100000Z\n"
        "SUMMARY:Only one left\n"
        "DTSTART:20260829T100000Z\n"
        "DTEND:20260829T110000Z\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token-single")],
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "token-single": CalDavFetchResult(
                    events=[
                        CalDavEvent(
                            event_href=event_href,
                            etag='"single-v2"',
                            calendar_data=single_occurrence_ical,
                        )
                    ],
                    sync_token="token-single-2",
                )
            }
        },
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )
    result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    objs = list(
        db_session.scalars(
            select(Object).where(
                Object.user_id == BOOTSTRAP_USER_ID,
                Object.metadata_["event_href"].as_string() == event_href,
            )
        ).all()
    )
    active = [obj for obj in objs if obj.status != "deleted"]
    tombstoned = [obj for obj in objs if obj.status == "deleted"]
    assert result["tombstoned"] == 4
    assert len(active) == 1
    assert len(tombstoned) == 4


def test_is_stale_sync_token_response_detects_valid_sync_token_precondition() -> None:
    from app.connectors.yandex.caldav_transport import _is_stale_sync_token_response

    xml = "<d:error xmlns:d='DAV:'><d:valid-sync-token/></d:error>"
    assert _is_stale_sync_token_response(403, xml) is True
    assert _is_stale_sync_token_response(409, "sync-token invalid") is True
    assert _is_stale_sync_token_response(403, "permission denied") is False
    assert _is_stale_sync_token_response(409, "resource conflict") is False
    assert _is_stale_sync_token_response(401, "unauthorized") is False


def test_sync_collection_stale_precondition_raises_stale_error() -> None:
    stale_xml = "<d:error xmlns:d='DAV:'><d:valid-sync-token/></d:error>"

    class StaleHttpClient:
        def request(self, method: str, url: str, **kwargs) -> httpx.Response:
            return httpx.Response(403, text=stale_xml)

    transport = CalDavHttpTransport(
        email="user@yandex.ru",
        password="pass",
        http_client=StaleHttpClient(),
    )
    with pytest.raises(YandexCalDavStaleSyncTokenError):
        transport.sync_collection(
            CALENDAR_HREF,
            "old-token",
            100,
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 12, 31, tzinfo=UTC),
        )


def test_sync_collection_permission_forbidden_raises_caldav_error_not_stale() -> None:
    class ForbiddenHttpClient:
        def request(self, method: str, url: str, **kwargs) -> httpx.Response:
            return httpx.Response(403, text="permission denied")

    transport = CalDavHttpTransport(
        email="user@yandex.ru",
        password="pass",
        http_client=ForbiddenHttpClient(),
    )
    with pytest.raises(YandexCalDavError, match="HTTP 403"):
        transport.sync_collection(
            CALENDAR_HREF,
            "steady-token",
            100,
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 12, 31, tzinfo=UTC),
        )


def test_sync_collection_unrelated_409_raises_caldav_error_not_stale() -> None:
    class ConflictHttpClient:
        def request(self, method: str, url: str, **kwargs) -> httpx.Response:
            return httpx.Response(409, text="resource conflict")

    transport = CalDavHttpTransport(
        email="user@yandex.ru",
        password="pass",
        http_client=ConflictHttpClient(),
    )
    with pytest.raises(YandexCalDavError, match="HTTP 409"):
        transport.sync_collection(
            CALENDAR_HREF,
            "steady-token",
            100,
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 12, 31, tzinfo=UTC),
        )


def test_sync_collection_permission_forbidden_does_not_trigger_backfill(
    db_session, credential_key: str
) -> None:
    class ForbiddenSyncTransport(FakeCalDavTransport):
        def sync_collection(self, calendar_href, sync_token, max_results, time_min, time_max):
            raise YandexCalDavError("caldav request failed for permission")

    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="forbidden@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    store.update_sync_state(
        account,
        _steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "steady-token",
                    "covered_window_end": "2026-12-31T00:00:00+00:00",
                }
            }
        ),
    )
    db_session.commit()

    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: ForbiddenSyncTransport(
            calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="steady-token")],
        ),
    )
    with pytest.raises(YandexCalDavError, match="caldav request failed"):
        sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=10)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert account.sync_state["calendars"][CALENDAR_HREF]["sync_token"] == "steady-token"
    assert account.sync_state["calendars"][CALENDAR_HREF].get("backfill_cursor") is None


def test_sync_collection_unrelated_409_does_not_trigger_backfill(
    db_session, credential_key: str
) -> None:
    class ConflictSyncTransport(FakeCalDavTransport):
        def sync_collection(self, calendar_href, sync_token, max_results, time_min, time_max):
            raise YandexCalDavError("caldav request failed for conflict")

    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="conflict@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    store.update_sync_state(
        account,
        _steady_sync_state(
            {
                CALENDAR_HREF: {
                    "sync_token": "steady-token",
                    "covered_window_end": "2026-12-31T00:00:00+00:00",
                }
            }
        ),
    )
    db_session.commit()

    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: ConflictSyncTransport(
            calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="steady-token")],
        ),
    )
    with pytest.raises(YandexCalDavError, match="caldav request failed"):
        sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=10)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert account.sync_state["calendars"][CALENDAR_HREF]["sync_token"] == "steady-token"


def test_bounded_reconciliation_exact_budget_leaves_range_incomplete(
    db_session, credential_key: str,
) -> None:
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="budget@yandex.ru",
        app_password="calendar-app-password",
        caldav_host="caldav.yandex.ru",
    )
    db_session.commit()

    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    window_min = now - timedelta(days=60)
    events = [
        _event(
            f"evt-budget-{index}",
            dtstart=(window_min + timedelta(days=index)).strftime("%Y%m%dT%H%M%SZ"),
            dtend=(window_min + timedelta(days=index, hours=1)).strftime("%Y%m%dT%H%M%SZ"),
        )
        for index in range(5)
    ]
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="steady-token")],
        query_events_by_calendar={CALENDAR_HREF: events},
        sync_tokens_by_calendar={CALENDAR_HREF: "steady-token"},
    )
    sync_service = build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=60,
        days_forward=90,
        default_limit=100,
        max_limit=100,
        max_calendars=10,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: now,
    )
    result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    state = account.sync_state["calendars"][CALENDAR_HREF]

    assert result["created"] == 1
    assert state.get("backfill_cursor") is not None
    assert state.get("sync_token") is None
    assert state.get("covered_window_end") is None
