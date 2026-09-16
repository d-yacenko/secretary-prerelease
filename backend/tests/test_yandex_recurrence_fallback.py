"""Temporal Correctness B-R3 — Yandex dateutil recurrence fallback."""

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
    normalize_caldav_resource,
)
from app.connectors.yandex.calendar_sync import build_yandex_calendar_sync_service
from app.connectors.yandex.constants import (
    CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION,
    LIVE_CALENDAR_LOOKBACK_DAYS,
    MAX_YANDEX_FALLBACK_RECURRENCE_CANDIDATES,
)
from app.connectors.yandex.errors import YandexConnectorError
from app.db.engine import engine
from app.db.models import Object
from app.services.today_service import TodayService
from app.users.bootstrap import BOOTSTRAP_USER_ID

FIXED_NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
CALENDAR_HREF = "/calendars/user@yandex.ru/events-1/"
PROBLEM_UID = "problem-weekly"
OP_MIN = FIXED_NOW - timedelta(days=LIVE_CALENDAR_LOOKBACK_DAYS)
OP_MAX = FIXED_NOW + timedelta(days=90)


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


def _today_ids(db_session, reference_at=FIXED_NOW):
    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(
        reference_at=reference_at,
        timezone="Europe/Moscow",
    )
    return {obj.external_id for obj in snapshot["calendar_events"]}


def _problem_master_ical() -> str:
    return (
        "BEGIN:VCALENDAR\n"
        "BEGIN:VEVENT\n"
        f"UID:{PROBLEM_UID}\n"
        "SUMMARY:Problem series\n"
        "DTSTART;TZID=Europe/Moscow:20260909T095500\n"
        "DTEND;TZID=Europe/Moscow:20260909T175500\n"
        "RRULE:FREQ=WEEKLY;BYDAY=WE,TH,FR\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )


def _sync_service(db_session, credential_key, transport, **kwargs):
    return build_yandex_calendar_sync_service(
        session=db_session,
        credential_key=credential_key,
        days_back=kwargs.get("days_back", 60),
        days_forward=kwargs.get("days_forward", 90),
        default_limit=kwargs.get("default_limit", 100),
        max_limit=kwargs.get("max_limit", 100),
        max_calendars=kwargs.get("max_calendars", 10),
        transport_factory=lambda snapshot: transport,
        now_factory=kwargs.get("now_factory", lambda: FIXED_NOW),
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


def test_weekly_wethfr_fallback_materializes_today(db_session, credential_key) -> None:
    _, account = _yandex_account(db_session, credential_key, email="problem@yandex.ru")
    href = f"{CALENDAR_HREF}{PROBLEM_UID}.ics"
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={
            CALENDAR_HREF: [CalDavEvent(event_href=href, etag='"p1"', calendar_data=_problem_master_ical())]
        },
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
    external_id = build_external_id(CALENDAR_HREF, PROBLEM_UID, "20260909T095500")
    obj = db_session.scalar(select(Object).where(Object.external_id == external_id))
    assert obj is not None
    assert obj.kind == "event"
    assert obj.metadata_["recurrence_id"] == "20260909T095500"
    assert obj.metadata_["recurrence_expansion"] == "fallback"
    assert db_session.scalar(select(Object).where(Object.external_id == build_external_id(CALENDAR_HREF, PROBLEM_UID))) is None or db_session.scalar(select(Object).where(Object.external_id == build_external_id(CALENDAR_HREF, PROBLEM_UID))).status == "deleted"
    assert external_id in _today_ids(db_session)


def test_daily_fallback_normalize() -> None:
    ical = (
        "BEGIN:VEVENT\nUID:daily-1\nSUMMARY:Daily\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\n"
        "RRULE:FREQ=DAILY;COUNT=3\nEND:VEVENT\n"
    )
    events = normalize_caldav_events(
        ical, CALENDAR_HREF, time_min=OP_MIN, time_max=OP_MAX, allow_fallback=True
    )
    rids = [item["metadata"]["recurrence_id"] for item in events]
    assert rids == ["20260909T100000Z", "20260910T100000Z", "20260911T100000Z"]
    assert all(item["metadata"]["recurrence_expansion"] == "fallback" for item in events)


def test_count_ends_before_window_does_not_fabricate() -> None:
    ical = (
        "BEGIN:VEVENT\nUID:ended-count\nSUMMARY:Ended\n"
        "DTSTART:20260101T100000Z\nDTEND:20260101T110000Z\n"
        "RRULE:FREQ=WEEKLY;COUNT=2\nEND:VEVENT\n"
    )
    events = normalize_caldav_events(
        ical, CALENDAR_HREF, time_min=OP_MIN, time_max=OP_MAX, allow_fallback=True
    )
    assert events == []


def test_until_ends_before_window_does_not_fabricate() -> None:
    ical = (
        "BEGIN:VEVENT\nUID:ended-until\nSUMMARY:Ended\n"
        "DTSTART:20260101T100000Z\nDTEND:20260101T110000Z\n"
        "RRULE:FREQ=WEEKLY;UNTIL=20260120T100000Z\nEND:VEVENT\n"
    )
    events = normalize_caldav_events(
        ical, CALENDAR_HREF, time_min=OP_MIN, time_max=OP_MAX, allow_fallback=True
    )
    assert events == []


def test_moscow_timed_recurrence_identity() -> None:
    events = normalize_caldav_events(
        _problem_master_ical(),
        CALENDAR_HREF,
        time_min=OP_MIN,
        time_max=OP_MAX,
        allow_fallback=True,
    )
    today = [item for item in events if item["metadata"]["recurrence_id"] == "20260909T095500"]
    assert len(today) == 1
    assert today[0]["start_at"] == datetime(2026, 9, 9, 6, 55, tzinfo=UTC)


def test_dst_timezone_recurrence() -> None:
    ical = (
        "BEGIN:VEVENT\nUID:dst-1\nSUMMARY:DST\n"
        "DTSTART;TZID=America/New_York:20260307T100000\n"
        "DTEND;TZID=America/New_York:20260307T110000\n"
        "RRULE:FREQ=DAILY;COUNT=4\nEND:VEVENT\n"
    )
    window_min = datetime(2026, 3, 7, tzinfo=UTC)
    window_max = datetime(2026, 3, 12, tzinfo=UTC)
    events = normalize_caldav_events(
        ical, CALENDAR_HREF, time_min=window_min, time_max=window_max, allow_fallback=True
    )
    assert len(events) == 4
    assert events[0]["metadata"]["recurrence_id"] == "20260307T100000"
    assert events[-1]["metadata"]["recurrence_id"] == "20260310T100000"


def test_all_day_date_recurrence() -> None:
    ical = (
        "BEGIN:VEVENT\nUID:allday-1\nSUMMARY:All day\n"
        "DTSTART;VALUE=DATE:20260909\nDTEND;VALUE=DATE:20260910\n"
        "RRULE:FREQ=DAILY;COUNT=2\nEND:VEVENT\n"
    )
    events = normalize_caldav_events(
        ical, CALENDAR_HREF, time_min=OP_MIN, time_max=OP_MAX, allow_fallback=True
    )
    assert [item["metadata"]["recurrence_id"] for item in events] == ["20260909", "20260910"]
    assert events[0]["external_id"] == build_external_id(CALENDAR_HREF, "allday-1", "20260909")


def test_exdate_removes_occurrence() -> None:
    ical = (
        "BEGIN:VEVENT\nUID:ex-1\nSUMMARY:Ex\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\n"
        "RRULE:FREQ=DAILY;COUNT=3\n"
        "EXDATE:20260910T100000Z\nEND:VEVENT\n"
    )
    events = normalize_caldav_events(
        ical, CALENDAR_HREF, time_min=OP_MIN, time_max=OP_MAX, allow_fallback=True
    )
    assert [item["metadata"]["recurrence_id"] for item in events] == [
        "20260909T100000Z",
        "20260911T100000Z",
    ]


def test_rdate_adds_occurrence() -> None:
    ical = (
        "BEGIN:VEVENT\nUID:rd-1\nSUMMARY:Rd\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\n"
        "RRULE:FREQ=DAILY;COUNT=1\n"
        "RDATE:20260912T100000Z\nEND:VEVENT\n"
    )
    events = normalize_caldav_events(
        ical, CALENDAR_HREF, time_min=OP_MIN, time_max=OP_MAX, allow_fallback=True
    )
    rids = {item["metadata"]["recurrence_id"] for item in events}
    assert "20260909T100000Z" in rids
    assert "20260912T100000Z" in rids


def test_provider_rid_override_wins_and_no_duplicate() -> None:
    ical = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
        f"UID:{PROBLEM_UID}\nSUMMARY:Master\n"
        "DTSTART;TZID=Europe/Moscow:20260909T095500\n"
        "DTEND;TZID=Europe/Moscow:20260909T175500\n"
        "RRULE:FREQ=WEEKLY;BYDAY=WE,TH,FR\nEND:VEVENT\n"
        "BEGIN:VEVENT\n"
        f"UID:{PROBLEM_UID}\nSUMMARY:Moved title\n"
        "RECURRENCE-ID:20260909T095500\n"
        "DTSTART;TZID=Europe/Moscow:20260909T110000\n"
        "DTEND;TZID=Europe/Moscow:20260909T120000\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )
    events = normalize_caldav_events(
        ical, CALENDAR_HREF, time_min=OP_MIN, time_max=datetime(2026, 9, 9, 23, tzinfo=UTC), allow_fallback=True
    )
    today = [item for item in events if item["metadata"]["recurrence_id"] == "20260909T095500"]
    assert len(today) == 1
    assert today[0]["title"] == "Moved title"
    assert today[0]["metadata"]["recurrence_expansion"] == "provider"
    assert today[0]["start_at"] == datetime(2026, 9, 9, 8, 0, tzinfo=UTC)


def test_cancelled_override_tombstones(db_session, credential_key) -> None:
    _, account = _yandex_account(db_session, credential_key, email="cancel@yandex.ru")
    href = f"{CALENDAR_HREF}cancel.ics"
    external_id = build_external_id(CALENDAR_HREF, "cancel-1", "20260909T100000Z")
    db_session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="event",
            provider="yandex_calendar",
            external_id=external_id,
            origin="source",
            state="observed",
            title="Master",
            start_at=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
            metadata_={"event_href": href},
        )
    )
    db_session.commit()
    ical = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:cancel-1\nSUMMARY:Master\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\n"
        "RRULE:FREQ=DAILY;COUNT=1\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:cancel-1\nSUMMARY:Master\nSTATUS:CANCELLED\n"
        "RECURRENCE-ID:20260909T100000Z\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={CALENDAR_HREF: [CalDavEvent(event_href=href, etag='"c"', calendar_data=ical)]},
    )
    sync = _sync_service(db_session, credential_key, transport)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    obj = db_session.scalar(select(Object).where(Object.external_id == external_id))
    assert obj is not None
    assert obj.status == "deleted"


def test_fallback_identity_matches_later_provider_expansion(db_session, credential_key) -> None:
    _, account = _yandex_account(db_session, credential_key, email="ident@yandex.ru")
    href = f"{CALENDAR_HREF}ident.ics"
    master = (
        "BEGIN:VEVENT\nUID:ident-1\nSUMMARY:Series\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\n"
        "RRULE:FREQ=DAILY;COUNT=1\nEND:VEVENT\n"
    )
    expanded = (
        "BEGIN:VEVENT\nUID:ident-1\nSUMMARY:Series\n"
        "RECURRENCE-ID:20260909T100000Z\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\nEND:VEVENT\n"
    )
    query_events = [CalDavEvent(event_href=href, etag='"i1"', calendar_data=master)]
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={CALENDAR_HREF: query_events},
    )
    sync = _sync_service(db_session, credential_key, transport)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    external_id = build_external_id(CALENDAR_HREF, "ident-1", "20260909T100000Z")
    first = db_session.scalar(select(Object).where(Object.external_id == external_id))
    assert first is not None
    assert first.metadata_["recurrence_expansion"] == "fallback"
    first_id = first.id
    query_events[0] = CalDavEvent(event_href=href, etag='"i2"', calendar_data=expanded)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    second = db_session.scalar(select(Object).where(Object.external_id == external_id))
    assert second is not None
    assert second.id == first_id
    assert second.metadata_["recurrence_expansion"] == "provider"


def test_provider_expanded_no_duplicate_fallback() -> None:
    ical = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:good-1\nSUMMARY:Master\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\n"
        "RRULE:FREQ=DAILY;COUNT=1\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:good-1\nSUMMARY:Occ\n"
        "RECURRENCE-ID:20260909T100000Z\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )
    events = normalize_caldav_events(
        ical, CALENDAR_HREF, time_min=OP_MIN, time_max=OP_MAX, allow_fallback=True
    )
    assert len(events) == 1
    assert events[0]["metadata"]["recurrence_expansion"] == "provider"


def test_resync_idempotent(db_session, credential_key) -> None:
    _, account = _yandex_account(db_session, credential_key, email="idemp@yandex.ru")
    href = f"{CALENDAR_HREF}{PROBLEM_UID}.ics"
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={
            CALENDAR_HREF: [CalDavEvent(event_href=href, etag='"p1"', calendar_data=_problem_master_ical())]
        },
    )
    sync = _sync_service(db_session, credential_key, transport)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    first = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.user_id == BOOTSTRAP_USER_ID)
    )
    ids = {
        obj.id
        for obj in db_session.scalars(
            select(Object).where(Object.user_id == BOOTSTRAP_USER_ID, Object.kind == "event")
        )
    }
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    second = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.user_id == BOOTSTRAP_USER_ID)
    )
    ids_after = {
        obj.id
        for obj in db_session.scalars(
            select(Object).where(Object.user_id == BOOTSTRAP_USER_ID, Object.kind == "event")
        )
    }
    assert first == second
    assert ids == ids_after


def test_legacy_master_tombstoned(db_session, credential_key) -> None:
    _, account = _yandex_account(db_session, credential_key, email="legacy@yandex.ru")
    href = f"{CALENDAR_HREF}{PROBLEM_UID}.ics"
    master_external = build_external_id(CALENDAR_HREF, PROBLEM_UID)
    db_session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="event",
            provider="yandex_calendar",
            external_id=master_external,
            origin="source",
            state="observed",
            title="Legacy master",
            start_at=datetime(2026, 9, 9, 6, 55, tzinfo=UTC),
            metadata_={"event_href": href, "rrule": "FREQ=WEEKLY;BYDAY=WE,TH,FR"},
        )
    )
    db_session.commit()
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={
            CALENDAR_HREF: [CalDavEvent(event_href=href, etag='"p1"', calendar_data=_problem_master_ical())]
        },
    )
    sync = _sync_service(db_session, credential_key, transport)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    legacy = db_session.scalar(select(Object).where(Object.external_id == master_external))
    assert legacy is not None
    assert legacy.status == "deleted"
    assert legacy.metadata_.get("recurrence_master_superseded") is True
    assert "caldav_deleted" not in (legacy.metadata_ or {})


def test_malformed_rrule_leaves_legacy_master(db_session, credential_key) -> None:
    _, account = _yandex_account(db_session, credential_key, email="badrrule@yandex.ru")
    href = f"{CALENDAR_HREF}bad.ics"
    master_external = build_external_id(CALENDAR_HREF, "bad-1")
    db_session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="event",
            provider="yandex_calendar",
            external_id=master_external,
            origin="source",
            state="observed",
            title="Legacy",
            start_at=FIXED_NOW,
            metadata_={"event_href": href},
        )
    )
    db_session.commit()
    ical = (
        "BEGIN:VEVENT\nUID:bad-1\nSUMMARY:Bad\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\n"
        "RRULE:FREQ=NOT-A-FREQ\nEND:VEVENT\n"
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={CALENDAR_HREF: [CalDavEvent(event_href=href, etag='"b"', calendar_data=ical)]},
    )
    sync = _sync_service(db_session, credential_key, transport)
    with pytest.raises(YandexConnectorError):
        sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    legacy = db_session.scalar(select(Object).where(Object.external_id == master_external))
    assert legacy is not None
    assert legacy.status != "deleted"


def test_candidate_cap_fails_closed_without_partial_recon(db_session, credential_key) -> None:
    _, account = _yandex_account(db_session, credential_key, email="cap@yandex.ru")
    href = f"{CALENDAR_HREF}minutely.ics"
    ical = (
        "BEGIN:VEVENT\nUID:cap-1\nSUMMARY:Minutely\n"
        f"DTSTART:{FIXED_NOW.strftime('%Y%m%dT%H%M%SZ')}\n"
        f"DTEND:{(FIXED_NOW + timedelta(minutes=1)).strftime('%Y%m%dT%H%M%SZ')}\n"
        "RRULE:FREQ=MINUTELY\nEND:VEVENT\n"
    )
    existing = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="event",
        provider="yandex_calendar",
        external_id=build_external_id(CALENDAR_HREF, "cap-1", "keep"),
        origin="source",
        state="observed",
        title="Keep",
        start_at=FIXED_NOW,
        metadata_={"event_href": href},
    )
    db_session.add(existing)
    db_session.commit()
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={CALENDAR_HREF: [CalDavEvent(event_href=href, etag='"m"', calendar_data=ical)]},
    )
    sync = _sync_service(db_session, credential_key, transport)
    with pytest.raises(YandexConnectorError, match="MAX_YANDEX_FALLBACK_RECURRENCE_CANDIDATES"):
        sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    kept = db_session.scalar(select(Object).where(Object.id == existing.id))
    assert kept.status != "deleted"
    assert MAX_YANDEX_FALLBACK_RECURRENCE_CANDIDATES == 256


def test_partial_resource_budget_replays_same_href(db_session, credential_key) -> None:
    _, account = _yandex_account(db_session, credential_key, email="partial@yandex.ru")
    href = f"{CALENDAR_HREF}many.ics"
    vevents = []
    for index in range(5):
        start = FIXED_NOW + timedelta(days=index)
        stamp = start.strftime("%Y%m%dT%H%M%SZ")
        vevents.append(
            "BEGIN:VEVENT\nUID:many-1\nSUMMARY:Many\n"
            f"RECURRENCE-ID:{stamp}\nDTSTART:{stamp}\n"
            f"DTEND:{(start + timedelta(hours=1)).strftime('%Y%m%dT%H%M%SZ')}\nEND:VEVENT"
        )
    ical = "BEGIN:VCALENDAR\n" + "\n".join(vevents) + "\nEND:VCALENDAR\n"
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={CALENDAR_HREF: [CalDavEvent(event_href=href, etag='"n"', calendar_data=ical)]},
    )
    sync = _sync_service(db_session, credential_key, transport)
    first = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=2)
    assert first["created"] == 2
    store = YandexCalendarAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    cursor = account.sync_state["calendars"][CALENDAR_HREF].get("operational_href_cursor")
    assert cursor in (None, "")
    second = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    assert second["created"] == 3
    count = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(Object.user_id == BOOTSTRAP_USER_ID, Object.kind == "event", Object.status.is_(None))
    )
    assert count == 5


def test_unexpanded_master_without_fallback_still_skipped() -> None:
    assert normalize_caldav_events(_problem_master_ical(), CALENDAR_HREF) == []
    result = normalize_caldav_resource(_problem_master_ical(), CALENDAR_HREF, allow_fallback=False)
    assert result.events == []
    assert result.occurrence_set_complete is False


def _seed_occurrence(
    db_session,
    *,
    href: str,
    uid: str,
    recurrence_id: str,
    start_at: datetime,
    title: str = "Seeded",
) -> Object:
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="event",
        provider="yandex_calendar",
        external_id=build_external_id(CALENDAR_HREF, uid, recurrence_id),
        origin="source",
        state="observed",
        title=title,
        start_at=start_at,
        due_at=start_at + timedelta(hours=1),
        occurred_at=start_at,
        metadata_={"event_href": href, "recurrence_id": recurrence_id, "event_uid": uid},
    )
    db_session.add(obj)
    return obj


def test_incremental_fallback_does_not_tombstone_history_outside_coverage(
    db_session, credential_key
) -> None:
    store, account = _yandex_account(db_session, credential_key, email="cover@yandex.ru")
    href = f"{CALENDAR_HREF}cover.ics"
    uid = "cover-1"
    historical = [
        (datetime(2026, 8, 5, 6, 55, tzinfo=UTC), "20260805T095500"),
        (datetime(2026, 8, 20, 6, 55, tzinfo=UTC), "20260820T095500"),
    ]
    for start, rid in historical:
        _seed_occurrence(db_session, href=href, uid=uid, recurrence_id=rid, start_at=start, title="History")
    stale_in_window = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    _seed_occurrence(
        db_session,
        href=href,
        uid=uid,
        recurrence_id="20260912T100000Z",
        start_at=stale_in_window,
        title="Stale Saturday",
    )
    db_session.commit()
    store.update_sync_state(
        account,
        {
            "normalization_version": CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION,
            "calendars": {CALENDAR_HREF: {"sync_token": "token-start"}},
        },
    )
    db_session.commit()
    master = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
        f"UID:{uid}\nSUMMARY:Cover series\n"
        "DTSTART;TZID=Europe/Moscow:20260909T095500\n"
        "DTEND;TZID=Europe/Moscow:20260909T175500\n"
        "RRULE:FREQ=WEEKLY;BYDAY=WE,TH,FR\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token-next")],
        query_events_by_calendar={CALENDAR_HREF: []},
        sync_tokens_by_calendar={CALENDAR_HREF: "token-next"},
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "token-start": CalDavFetchResult(
                    events=[CalDavEvent(event_href=href, etag='"c1"', calendar_data=master)],
                    sync_token="token-next",
                )
            }
        },
    )
    sync = _sync_service(db_session, credential_key, transport, days_back=60, days_forward=90)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    for start, rid in historical:
        obj = db_session.scalar(
            select(Object).where(Object.external_id == build_external_id(CALENDAR_HREF, uid, rid))
        )
        assert obj is not None
        assert obj.status != "deleted"
    stale = db_session.scalar(
        select(Object).where(
            Object.external_id == build_external_id(CALENDAR_HREF, uid, "20260912T100000Z")
        )
    )
    assert stale is not None
    assert stale.status == "deleted"
    today = db_session.scalar(
        select(Object).where(Object.external_id == build_external_id(CALENDAR_HREF, uid, "20260909T095500"))
    )
    assert today is not None
    assert today.status != "deleted"
    assert today.metadata_["recurrence_expansion"] == "fallback"


def test_incremental_provider_expanded_does_not_tombstone_history_outside_coverage(
    db_session, credential_key
) -> None:
    store, account = _yandex_account(db_session, credential_key, email="cover-p@yandex.ru")
    href = f"{CALENDAR_HREF}cover-p.ics"
    uid = "cover-p"
    hist_start = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
    _seed_occurrence(
        db_session,
        href=href,
        uid=uid,
        recurrence_id="20260810T100000Z",
        start_at=hist_start,
        title="History",
    )
    stale_start = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    _seed_occurrence(
        db_session,
        href=href,
        uid=uid,
        recurrence_id="20260916T100000Z",
        start_at=stale_start,
        title="Stale future",
    )
    db_session.commit()
    store.update_sync_state(
        account,
        {
            "normalization_version": CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION,
            "calendars": {CALENDAR_HREF: {"sync_token": "token-start"}},
        },
    )
    db_session.commit()
    ical = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
        f"UID:{uid}\nSUMMARY:Master\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\n"
        "RRULE:FREQ=DAILY;COUNT=1\nEND:VEVENT\n"
        "BEGIN:VEVENT\n"
        f"UID:{uid}\nSUMMARY:Today occ\n"
        "RECURRENCE-ID:20260909T100000Z\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token="token-next")],
        query_events_by_calendar={CALENDAR_HREF: []},
        sync_tokens_by_calendar={CALENDAR_HREF: "token-next"},
        sync_batches_by_calendar={
            CALENDAR_HREF: {
                "token-start": CalDavFetchResult(
                    events=[CalDavEvent(event_href=href, etag='"p1"', calendar_data=ical)],
                    sync_token="token-next",
                )
            }
        },
    )
    sync = _sync_service(db_session, credential_key, transport, days_back=60, days_forward=90)
    sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    hist = db_session.scalar(
        select(Object).where(Object.external_id == build_external_id(CALENDAR_HREF, uid, "20260810T100000Z"))
    )
    assert hist is not None
    assert hist.status != "deleted"
    stale = db_session.scalar(
        select(Object).where(Object.external_id == build_external_id(CALENDAR_HREF, uid, "20260916T100000Z"))
    )
    assert stale is not None
    assert stale.status == "deleted"
    today = db_session.scalar(
        select(Object).where(Object.external_id == build_external_id(CALENDAR_HREF, uid, "20260909T100000Z"))
    )
    assert today is not None
    assert today.status != "deleted"
    assert today.metadata_["recurrence_expansion"] == "provider"


def test_timed_duration_preserved() -> None:
    ical = (
        "BEGIN:VEVENT\nUID:dur-1\nSUMMARY:Dur\n"
        "DTSTART:20260909T100000Z\nDURATION:PT2H30M\n"
        "RRULE:FREQ=DAILY;COUNT=1\nEND:VEVENT\n"
    )
    events = normalize_caldav_events(
        ical, CALENDAR_HREF, time_min=OP_MIN, time_max=OP_MAX, allow_fallback=True
    )
    assert len(events) == 1
    assert events[0]["start_at"] == datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
    assert events[0]["due_at"] == datetime(2026, 9, 9, 12, 30, tzinfo=UTC)


def test_all_day_duration_preserved() -> None:
    ical = (
        "BEGIN:VEVENT\nUID:dur-d\nSUMMARY:Dur day\n"
        "DTSTART;VALUE=DATE:20260909\nDURATION:P2D\n"
        "RRULE:FREQ=DAILY;COUNT=1\nEND:VEVENT\n"
    )
    events = normalize_caldav_events(
        ical, CALENDAR_HREF, time_min=OP_MIN, time_max=OP_MAX, allow_fallback=True
    )
    assert events[0]["due_at"] == datetime(2026, 9, 11, tzinfo=UTC)


def test_timed_dtstart_only_zero_duration() -> None:
    ical = (
        "BEGIN:VEVENT\nUID:dur-z\nSUMMARY:Zero\n"
        "DTSTART:20260909T100000Z\n"
        "RRULE:FREQ=DAILY;COUNT=1\nEND:VEVENT\n"
    )
    events = normalize_caldav_events(
        ical, CALENDAR_HREF, time_min=OP_MIN, time_max=OP_MAX, allow_fallback=True
    )
    assert events[0]["due_at"] == events[0]["start_at"]


def test_date_dtstart_only_defaults_one_day() -> None:
    ical = (
        "BEGIN:VEVENT\nUID:dur-date\nSUMMARY:Date\n"
        "DTSTART;VALUE=DATE:20260909\n"
        "RRULE:FREQ=DAILY;COUNT=1\nEND:VEVENT\n"
    )
    events = normalize_caldav_events(
        ical, CALENDAR_HREF, time_min=OP_MIN, time_max=OP_MAX, allow_fallback=True
    )
    assert events[0]["due_at"] == datetime(2026, 9, 10, tzinfo=UTC)


def test_malformed_duration_fails_closed() -> None:
    ical = (
        "BEGIN:VEVENT\nUID:dur-bad\nSUMMARY:Bad\n"
        "DTSTART:20260909T100000Z\nDURATION:P1Y\n"
        "RRULE:FREQ=DAILY;COUNT=1\nEND:VEVENT\n"
    )
    with pytest.raises(YandexConnectorError, match="DURATION"):
        normalize_caldav_events(
            ical, CALENDAR_HREF, time_min=OP_MIN, time_max=OP_MAX, allow_fallback=True
        )


def test_dtend_and_duration_rejected() -> None:
    ical = (
        "BEGIN:VEVENT\nUID:dur-both\nSUMMARY:Both\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\nDURATION:PT1H\n"
        "RRULE:FREQ=DAILY;COUNT=1\nEND:VEVENT\n"
    )
    with pytest.raises(YandexConnectorError, match="DTEND and DURATION"):
        normalize_caldav_events(
            ical, CALENDAR_HREF, time_min=OP_MIN, time_max=OP_MAX, allow_fallback=True
        )


def test_multiple_rrule_fails_closed_without_legacy_cleanup(db_session, credential_key) -> None:
    _, account = _yandex_account(db_session, credential_key, email="multirrule@yandex.ru")
    href = f"{CALENDAR_HREF}multi.ics"
    master_external = build_external_id(CALENDAR_HREF, "multi-1")
    stale = _seed_occurrence(
        db_session,
        href=href,
        uid="multi-1",
        recurrence_id="20260909T100000Z",
        start_at=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
        title="Keep",
    )
    db_session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="event",
            provider="yandex_calendar",
            external_id=master_external,
            origin="source",
            state="observed",
            title="Legacy",
            start_at=FIXED_NOW,
            metadata_={"event_href": href},
        )
    )
    db_session.commit()
    ical = (
        "BEGIN:VEVENT\nUID:multi-1\nSUMMARY:Multi\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\n"
        "RRULE:FREQ=WEEKLY;BYDAY=WE\n"
        "RRULE:FREQ=WEEKLY;BYDAY=FR\nEND:VEVENT\n"
    )
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={CALENDAR_HREF: [CalDavEvent(event_href=href, etag='"m"', calendar_data=ical)]},
    )
    sync = _sync_service(db_session, credential_key, transport)
    with pytest.raises(YandexConnectorError, match="multiple RRULE"):
        sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    legacy = db_session.scalar(select(Object).where(Object.external_id == master_external))
    assert legacy is not None
    assert legacy.status != "deleted"
    kept = db_session.scalar(select(Object).where(Object.id == stale.id))
    assert kept.status != "deleted"


def test_recurring_fallback_reports_operational_coverage() -> None:
    result = normalize_caldav_resource(
        _problem_master_ical(),
        CALENDAR_HREF,
        time_min=OP_MIN,
        time_max=OP_MAX,
        allow_fallback=True,
    )
    assert result.occurrence_set_complete is True
    assert result.occurrence_coverage_min == OP_MIN
    assert result.occurrence_coverage_max == OP_MAX


@pytest.fixture
def autoflush_false_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False)
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _count1_ical(uid: str) -> str:
    return (
        "BEGIN:VEVENT\n"
        f"UID:{uid}\nSUMMARY:Series\n"
        "DTSTART:20260909T100000Z\nDTEND:20260909T110000Z\n"
        "RRULE:FREQ=DAILY;COUNT=1\nEND:VEVENT\n"
    )


def test_autoflush_false_supersession_not_marked_caldav_deleted(
    autoflush_false_session, credential_key
) -> None:
    session = autoflush_false_session
    _, account = _yandex_account(session, credential_key, email="af-legacy@yandex.ru")
    href = f"{CALENDAR_HREF}af-legacy.ics"
    uid = "af-legacy"
    master_external = build_external_id(CALENDAR_HREF, uid)
    session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="event",
            provider="yandex_calendar",
            external_id=master_external,
            origin="source",
            state="observed",
            title="Legacy master",
            start_at=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
            metadata_={"event_href": href, "event_uid": uid},
        )
    )
    stale = _seed_occurrence(
        session,
        href=href,
        uid=uid,
        recurrence_id="20260912T100000Z",
        start_at=datetime(2026, 9, 12, 10, 0, tzinfo=UTC),
        title="Stale",
    )
    session.commit()
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={
            CALENDAR_HREF: [CalDavEvent(event_href=href, etag='"a1"', calendar_data=_count1_ical(uid))]
        },
    )
    sync = _sync_service(session, credential_key, transport)
    result = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    session.expire_all()
    legacy = session.scalar(select(Object).where(Object.external_id == master_external))
    assert legacy is not None
    assert legacy.status == "deleted"
    assert legacy.metadata_.get("recurrence_master_superseded") is True
    assert "caldav_deleted" not in (legacy.metadata_ or {})
    assert "deleted_at" not in (legacy.metadata_ or {})
    stale = session.scalar(select(Object).where(Object.id == stale.id))
    assert stale.status == "deleted"
    assert stale.metadata_.get("caldav_deleted") is True
    today = session.scalar(
        select(Object).where(
            Object.external_id == build_external_id(CALENDAR_HREF, uid, "20260909T100000Z")
        )
    )
    assert today is not None
    assert today.status != "deleted"
    assert result["created"] == 1
    assert result["tombstoned"] == 2
    assert result["created"] + result["updated"] + result["tombstoned"] == 3


def test_autoflush_false_repairs_false_caldav_deleted_on_superseded_master(
    autoflush_false_session, credential_key
) -> None:
    session = autoflush_false_session
    _, account = _yandex_account(session, credential_key, email="af-repair@yandex.ru")
    href = f"{CALENDAR_HREF}af-repair.ics"
    uid = "af-repair"
    master_external = build_external_id(CALENDAR_HREF, uid)
    session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="event",
            provider="yandex_calendar",
            external_id=master_external,
            origin="source",
            state="observed",
            title="Legacy master",
            start_at=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
            status="deleted",
            metadata_={
                "event_href": href,
                "event_uid": uid,
                "recurrence_master_superseded": True,
                "caldav_deleted": True,
                "deleted_at": "2026-09-09T11:55:16+00:00",
            },
        )
    )
    occ = _seed_occurrence(
        session,
        href=href,
        uid=uid,
        recurrence_id="20260909T100000Z",
        start_at=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
        title="Today",
    )
    session.commit()
    transport = FakeCalDavTransport(
        calendars=[CalDavCalendar(href=CALENDAR_HREF, display_name="Work", sync_token=None)],
        query_events_by_calendar={
            CALENDAR_HREF: [CalDavEvent(event_href=href, etag='"a1"', calendar_data=_count1_ical(uid))]
        },
    )
    sync = _sync_service(session, credential_key, transport)
    first = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    session.expire_all()
    legacy = session.scalar(select(Object).where(Object.external_id == master_external))
    assert legacy.status == "deleted"
    assert legacy.metadata_.get("recurrence_master_superseded") is True
    assert "caldav_deleted" not in (legacy.metadata_ or {})
    assert "deleted_at" not in (legacy.metadata_ or {})
    kept = session.scalar(select(Object).where(Object.id == occ.id))
    assert kept.status != "deleted"
    assert first["tombstoned"] == 1
    second = sync.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    session.expire_all()
    legacy = session.scalar(select(Object).where(Object.external_id == master_external))
    assert legacy.status == "deleted"
    assert "caldav_deleted" not in (legacy.metadata_ or {})
    assert second["tombstoned"] == 0
    assert session.scalar(select(Object).where(Object.id == occ.id)).status != "deleted"
