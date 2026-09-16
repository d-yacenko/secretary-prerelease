"""Temporal Correctness C — recurring-series Inbox projection."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.db.models import Edge, InboxReviewMarker, Job, Object, ObjectBookmark, User
from app.domain.object_visibility import tombstone_object
from app.services.inbox_feed_cursor import decode_inbox_feed_cursor
from app.services.object_bookmark_service import ObjectBookmarkService
from app.services.recent_source_service import RecentSourceService, inbox_feed_at
from app.services.search_service import SearchService
from app.services.today_service import TodayService
from app.users.bootstrap import BOOTSTRAP_USER_ID

CREATED = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
SEP_15 = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
SEP_22 = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
SEP_29 = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
YANDEX_HREF = "/calendars/user@yandex.ru/events-1/"
YANDEX_HREF_B = "/calendars/user@yandex.ru/events-2/"
YANDEX_UID = "weekly-sync-uid"
GOOGLE_CALENDAR_ID = "primary"
GOOGLE_SERIES_ID = "google-recurring-series"

_WALL_CLOCK_SQL_TOKENS = (
    "now()",
    "current_timestamp",
    "current_date",
    "clock_timestamp(",
    "statement_timestamp(",
    "transaction_timestamp(",
)


@pytest.fixture(autouse=True)
def _isolate(db_session: Session) -> None:
    db_session.execute(
        ObjectBookmark.__table__.delete().where(ObjectBookmark.user_id == BOOTSTRAP_USER_ID)
    )
    db_session.execute(
        InboxReviewMarker.__table__.delete().where(
            InboxReviewMarker.user_id == BOOTSTRAP_USER_ID
        )
    )
    db_session.execute(Job.__table__.delete().where(Job.user_id == BOOTSTRAP_USER_ID))
    db_session.execute(Edge.__table__.delete().where(Edge.user_id == BOOTSTRAP_USER_ID))
    db_session.execute(Object.__table__.delete().where(Object.user_id == BOOTSTRAP_USER_ID))
    db_session.flush()


def _stamp(
    obj: Object,
    *,
    created_at: datetime,
    occurred_at: datetime | None = None,
    start_at: datetime | None = None,
) -> Object:
    obj.created_at = created_at
    obj.updated_at = created_at
    obj.occurred_at = occurred_at
    if start_at is not None:
        obj.start_at = start_at
    return obj


def _create(
    db_session: Session,
    *,
    title: str,
    provider: str,
    kind: str = "email",
    origin: str = "source",
    created_at: datetime,
    occurred_at: datetime | None = None,
    start_at: datetime | None = None,
    object_id: UUID | None = None,
    user_id: UUID | None = None,
    metadata: dict | None = None,
    state: str | None = None,
    status: str | None = None,
    external_id: str | None = None,
) -> Object:
    owner = user_id or BOOTSTRAP_USER_ID
    obj = Object(
        id=object_id or uuid.uuid4(),
        user_id=owner,
        kind=kind,
        title=title,
        origin=origin,
        state=state or ("observed" if origin == "source" else "confirmed"),
        status=status,
        provider=provider,
        external_id=external_id or f"ext-{uuid.uuid4()}",
        metadata_=metadata or {},
    )
    db_session.add(obj)
    db_session.flush()
    return _stamp(
        obj,
        created_at=created_at,
        occurred_at=occurred_at,
        start_at=start_at,
    )


def _yandex_meta(
    *,
    event_uid: str,
    recurrence_id: str | None,
    calendar_href: str = YANDEX_HREF,
    calendar_id: str | None = None,
) -> dict:
    metadata: dict = {
        "event_uid": event_uid,
        "calendar_href": calendar_href,
    }
    if recurrence_id is not None:
        metadata["recurrence_id"] = recurrence_id
    if calendar_id is None:
        metadata["calendar_id"] = calendar_href.rstrip("/")
    elif calendar_id != "":
        metadata["calendar_id"] = calendar_id
    return metadata


def _google_meta(
    *,
    calendar_id: str,
    recurring_event_id: str | None,
    event_id: str | None = None,
) -> dict:
    metadata: dict = {"calendar_id": calendar_id}
    if recurring_event_id is not None:
        metadata["recurring_event_id"] = recurring_event_id
    if event_id is not None:
        metadata["event_id"] = event_id
    return metadata


def _yandex_occurrence(
    db_session: Session,
    *,
    start_at: datetime,
    title: str,
    event_uid: str = YANDEX_UID,
    calendar_href: str = YANDEX_HREF,
    created_at: datetime = CREATED,
    recurrence_id: str | None = None,
    **kwargs,
) -> Object:
    rid = recurrence_id or start_at.strftime("%Y%m%dT%H%M%S")
    return _create(
        db_session,
        title=title,
        provider="yandex_calendar",
        kind="event",
        created_at=created_at,
        occurred_at=start_at,
        start_at=start_at,
        metadata=_yandex_meta(
            event_uid=event_uid,
            recurrence_id=rid,
            calendar_href=calendar_href,
        ),
        **kwargs,
    )


def _google_occurrence(
    db_session: Session,
    *,
    start_at: datetime,
    title: str,
    calendar_id: str = GOOGLE_CALENDAR_ID,
    recurring_event_id: str = GOOGLE_SERIES_ID,
    created_at: datetime = CREATED,
    **kwargs,
) -> Object:
    rid = start_at.strftime("%Y%m%dT%H%M%S")
    return _create(
        db_session,
        title=title,
        provider="google_calendar",
        kind="event",
        created_at=created_at,
        occurred_at=start_at,
        start_at=start_at,
        metadata=_google_meta(
            calendar_id=calendar_id,
            recurring_event_id=recurring_event_id,
            event_id=f"{recurring_event_id}_{rid}",
        ),
        **kwargs,
    )


def _email(db_session: Session, title: str, *, created_at: datetime, **kwargs) -> Object:
    return _create(
        db_session,
        title=title,
        provider="gmail",
        created_at=created_at,
        occurred_at=kwargs.pop("occurred_at", created_at),
        **kwargs,
    )


def _feed(db_session: Session) -> RecentSourceService:
    return RecentSourceService(db_session, BOOTSTRAP_USER_ID)


def _inbox_ids(db_session: Session, limit: int = 50) -> list[UUID]:
    return [row.id for row in _feed(db_session).list_recent(limit=limit)]


def _inbox_titles(db_session: Session, limit: int = 50) -> list[str]:
    return [row.title for row in _feed(db_session).list_recent(limit=limit)]


def _capture_sql(db_session: Session, run) -> list[str]:
    statements: list[str] = []
    bind = db_session.get_bind()

    def _on_execute(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", _on_execute)
    try:
        run()
    finally:
        event.remove(bind, "before_cursor_execute", _on_execute)
    return statements


def _projected_page(db_session: Session, cursor: str | None = None):
    service = _feed(db_session)
    result: dict = {}

    def _run() -> None:
        result["page"] = service.list_page(limit=30, cursor=cursor)

    statements = _capture_sql(db_session, _run)
    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1
    compiled = selects[0].lower()
    for token in _WALL_CLOCK_SQL_TOKENS:
        assert token not in compiled
    return result["page"]


def test_yandex_future_recurrence_one_representative(db_session: Session) -> None:
    first = _yandex_occurrence(db_session, start_at=SEP_15, title="Yandex 15 Sep")
    later = [
        _yandex_occurrence(db_session, start_at=SEP_22, title="Yandex 22 Sep"),
        _yandex_occurrence(db_session, start_at=SEP_29, title="Yandex 29 Sep"),
        _yandex_occurrence(
            db_session,
            start_at=datetime(2026, 10, 6, 10, 0, tzinfo=UTC),
            title="Yandex 06 Oct",
        ),
    ]
    db_session.flush()
    stored = db_session.scalars(
        select(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == "yandex_calendar",
        )
    ).all()
    assert len(stored) == 4
    titles = _inbox_titles(db_session)
    assert titles == ["Yandex 15 Sep"]
    assert _inbox_ids(db_session) == [first.id]
    for sibling in later:
        assert sibling.id not in _inbox_ids(db_session)


def test_google_future_recurrence_one_representative(db_session: Session) -> None:
    starts = [SEP_15 + timedelta(weeks=index) for index in range(10)]
    rows = [
        _google_occurrence(
            db_session,
            start_at=start,
            title=f"Google {start.date().isoformat()}",
        )
        for start in starts
    ]
    db_session.flush()
    stored = db_session.scalars(
        select(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == "google_calendar",
        )
    ).all()
    assert len(stored) == 10
    assert _inbox_titles(db_session) == ["Google 2026-09-15"]
    assert _inbox_ids(db_session) == [rows[0].id]


def test_historical_recurring_occurrences_keep_temporal_a(db_session: Session) -> None:
    historical_a = _yandex_occurrence(
        db_session,
        start_at=datetime(2026, 8, 25, 10, 0, tzinfo=UTC),
        title="Historical 25 Aug",
    )
    historical_b = _yandex_occurrence(
        db_session,
        start_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        title="Historical 01 Sep",
    )
    future_rep = _yandex_occurrence(db_session, start_at=SEP_15, title="Future 15 Sep")
    _yandex_occurrence(db_session, start_at=SEP_22, title="Future 22 Sep")
    db_session.flush()
    titles = _inbox_titles(db_session)
    assert "Historical 25 Aug" in titles
    assert "Historical 01 Sep" in titles
    assert "Future 15 Sep" in titles
    assert "Future 22 Sep" not in titles
    assert inbox_feed_at(historical_a) == historical_a.start_at
    assert inbox_feed_at(historical_b) == historical_b.start_at
    assert inbox_feed_at(future_rep) == CREATED


def test_future_one_off_unchanged(db_session: Session) -> None:
    one_off = _create(
        db_session,
        title="One-off December",
        provider="yandex_calendar",
        kind="event",
        created_at=CREATED,
        occurred_at=datetime(2026, 12, 7, 6, 30, tzinfo=UTC),
        start_at=datetime(2026, 12, 7, 6, 30, tzinfo=UTC),
        metadata={"calendar_id": "cal-1", "event_uid": "one-off-uid"},
    )
    google_one_off = _create(
        db_session,
        title="Google one-off",
        provider="google_calendar",
        kind="event",
        created_at=CREATED,
        occurred_at=datetime(2026, 11, 10, 9, 0, tzinfo=UTC),
        start_at=datetime(2026, 11, 10, 9, 0, tzinfo=UTC),
        metadata=_google_meta(calendar_id=GOOGLE_CALENDAR_ID, recurring_event_id=None),
    )
    db_session.flush()
    titles = set(_inbox_titles(db_session))
    assert "One-off December" in titles
    assert "Google one-off" in titles
    assert inbox_feed_at(one_off) == CREATED
    assert inbox_feed_at(google_one_off) == CREATED


def test_identical_titles_different_series_do_not_collapse(db_session: Session) -> None:
    series_a = _yandex_occurrence(
        db_session,
        start_at=SEP_15,
        title="Синхронизация",
        event_uid="series-a-uid",
    )
    _yandex_occurrence(
        db_session,
        start_at=SEP_22,
        title="Синхронизация",
        event_uid="series-a-uid",
    )
    series_b = _yandex_occurrence(
        db_session,
        start_at=SEP_15 + timedelta(hours=1),
        title="Синхронизация",
        event_uid="series-b-uid",
    )
    _yandex_occurrence(
        db_session,
        start_at=SEP_22 + timedelta(hours=1),
        title="Синхронизация",
        event_uid="series-b-uid",
    )
    db_session.flush()
    ids = set(_inbox_ids(db_session))
    assert ids == {series_a.id, series_b.id}
    assert _inbox_titles(db_session).count("Синхронизация") == 2


def test_same_yandex_uid_different_calendars_do_not_collapse(db_session: Session) -> None:
    cal_a = _yandex_occurrence(
        db_session,
        start_at=SEP_15,
        title="Same UID calendar A",
        calendar_href=YANDEX_HREF,
    )
    _yandex_occurrence(
        db_session,
        start_at=SEP_22,
        title="Same UID calendar A later",
        calendar_href=YANDEX_HREF,
    )
    cal_b = _yandex_occurrence(
        db_session,
        start_at=SEP_15,
        title="Same UID calendar B",
        calendar_href=YANDEX_HREF_B,
    )
    _yandex_occurrence(
        db_session,
        start_at=SEP_22,
        title="Same UID calendar B later",
        calendar_href=YANDEX_HREF_B,
    )
    db_session.flush()
    ids = set(_inbox_ids(db_session))
    assert ids == {cal_a.id, cal_b.id}


def test_malformed_series_metadata_fails_open(db_session: Session) -> None:
    missing_rid = _create(
        db_session,
        title="Yandex master no recurrence_id",
        provider="yandex_calendar",
        kind="event",
        created_at=CREATED,
        occurred_at=SEP_15,
        start_at=SEP_15,
        metadata=_yandex_meta(event_uid=YANDEX_UID, recurrence_id=None),
    )
    missing_cal = _create(
        db_session,
        title="Yandex no calendar identity",
        provider="yandex_calendar",
        kind="event",
        created_at=CREATED,
        occurred_at=SEP_22,
        start_at=SEP_22,
        metadata={"event_uid": "uid-x", "recurrence_id": "20260922T100000"},
    )
    google_plain = _create(
        db_session,
        title="Google missing recurring_event_id",
        provider="google_calendar",
        kind="event",
        created_at=CREATED,
        occurred_at=SEP_29,
        start_at=SEP_29,
        metadata={"calendar_id": GOOGLE_CALENDAR_ID},
    )
    empty_google = _create(
        db_session,
        title="Google empty series keys",
        provider="google_calendar",
        kind="event",
        created_at=CREATED,
        occurred_at=datetime(2026, 10, 6, 10, 0, tzinfo=UTC),
        start_at=datetime(2026, 10, 6, 10, 0, tzinfo=UTC),
        metadata={"calendar_id": "  ", "recurring_event_id": ""},
    )
    db_session.flush()
    titles = set(_inbox_titles(db_session))
    assert missing_rid.title in titles
    assert missing_cal.title in titles
    assert google_plain.title in titles
    assert empty_google.title in titles


def test_representative_stable_across_wall_clock(db_session: Session) -> None:
    first = _yandex_occurrence(db_session, start_at=SEP_15, title="Stable 15 Sep")
    _yandex_occurrence(db_session, start_at=SEP_22, title="Stable 22 Sep")
    _yandex_occurrence(db_session, start_at=SEP_29, title="Stable 29 Sep")
    db_session.flush()
    assert _inbox_ids(db_session) == [first.id]

    statements = _capture_sql(db_session, lambda: _feed(db_session).list_page(limit=30))
    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1
    compiled = selects[0].lower()
    assert "exists" in compiled
    for token in _WALL_CLOCK_SQL_TOKENS:
        assert token not in compiled
    assert _inbox_titles(db_session) == ["Stable 15 Sep"]


def test_representative_deletion_promotes_next_eligible_sibling(db_session: Session) -> None:
    first = _yandex_occurrence(db_session, start_at=SEP_15, title="Lead 15 Sep")
    second = _yandex_occurrence(db_session, start_at=SEP_22, title="Next 22 Sep")
    third = _yandex_occurrence(db_session, start_at=SEP_29, title="Later 29 Sep")
    db_session.flush()
    assert _inbox_ids(db_session) == [first.id]
    tombstone_object(first)
    db_session.flush()
    assert _inbox_ids(db_session) == [second.id]
    assert db_session.get(Object, first.id) is not None
    assert db_session.get(Object, third.id) is not None
    db_session.refresh(second)
    db_session.refresh(third)
    assert second.deleted_at is None
    assert third.deleted_at is None
    assert second.start_at == SEP_22
    assert third.start_at == SEP_29


def test_multi_page_cursor_has_no_gaps_or_duplicates(db_session: Session) -> None:
    ordinary = [
        _email(
            db_session,
            f"mail-{index:02d}",
            created_at=CREATED - timedelta(minutes=index + 1),
        )
        for index in range(65)
    ]
    series_a = [
        _yandex_occurrence(
            db_session,
            start_at=SEP_15 + timedelta(weeks=index),
            title=f"SeriesA {index:02d}",
        )
        for index in range(20)
    ]
    series_b = [
        _google_occurrence(
            db_session,
            start_at=SEP_22 + timedelta(weeks=index),
            title=f"SeriesB {index:02d}",
            recurring_event_id="second-google-series",
        )
        for index in range(5)
    ]
    one_offs = [
        _create(
            db_session,
            title=f"OneOff {index}",
            provider="google_calendar",
            kind="event",
            created_at=CREATED,
            occurred_at=datetime(2026, 11, 1 + index, 9, 0, tzinfo=UTC),
            start_at=datetime(2026, 11, 1 + index, 9, 0, tzinfo=UTC),
            metadata=_google_meta(
                calendar_id=GOOGLE_CALENDAR_ID,
                recurring_event_id=None,
                event_id=f"one-off-{index}",
            ),
        )
        for index in range(4)
    ]
    db_session.flush()

    concatenated: list[Object] = []
    cursor = None
    page_sizes: list[int] = []
    has_more_flags: list[bool] = []
    while True:
        page = _projected_page(db_session, cursor)
        page_sizes.append(len(page.items))
        has_more_flags.append(page.has_more)
        concatenated.extend(page.items)
        if not page.has_more:
            assert page.next_cursor is None
            break
        assert page.next_cursor
        decode_inbox_feed_cursor(page.next_cursor)
        cursor = page.next_cursor

    expected_ids = {row.id for row in ordinary}
    expected_ids.add(series_a[0].id)
    expected_ids.add(series_b[0].id)
    expected_ids.update(row.id for row in one_offs)
    got_ids = [row.id for row in concatenated]
    assert len(got_ids) == len(set(got_ids))
    assert set(got_ids) == expected_ids
    assert series_a[0].id in expected_ids
    assert all(row.id not in set(got_ids) for row in series_a[1:])
    assert all(row.id not in set(got_ids) for row in series_b[1:])
    assert page_sizes[:-1] == [30, 30]
    assert page_sizes[-1] == len(expected_ids) - 60
    assert has_more_flags == [True, True, False]
    pairs = [(inbox_feed_at(row), row.id) for row in concatenated]
    assert pairs == sorted(pairs, key=lambda item: (item[0], item[1]), reverse=True)
    assert len(concatenated) == 65 + 1 + 1 + 4


def test_get_inbox_eligible_matches_projected_visibility(db_session: Session) -> None:
    representative = _google_occurrence(db_session, start_at=SEP_15, title="Eligible 15 Sep")
    sibling = _google_occurrence(db_session, start_at=SEP_22, title="Hidden 22 Sep")
    ordinary = _email(db_session, "Ordinary mail", created_at=CREATED - timedelta(hours=1))
    db_session.flush()
    service = _feed(db_session)
    assert service.get_inbox_eligible(representative.id) is not None
    assert service.get_inbox_eligible(sibling.id) is None
    assert service.get_inbox_eligible(ordinary.id) is not None
    visible_ids = set(_inbox_ids(db_session))
    assert representative.id in visible_ids
    assert sibling.id not in visible_ids
    assert ordinary.id in visible_ids


def test_review_marker_rejects_suppressed_sibling(auth_client, db_session: Session) -> None:
    representative = _yandex_occurrence(db_session, start_at=SEP_15, title="Marker 15 Sep")
    sibling = _yandex_occurrence(db_session, start_at=SEP_22, title="Marker 22 Sep")
    db_session.flush()
    accepted = auth_client.put(
        "/inbox/review-marker", json={"after_object_id": str(representative.id)}
    )
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["anchor_object_id"] == str(representative.id)
    assert datetime.fromisoformat(body["anchor_feed_at"]) == inbox_feed_at(representative)
    rejected = auth_client.put(
        "/inbox/review-marker", json={"after_object_id": str(sibling.id)}
    )
    assert rejected.status_code == 422
    persisted = auth_client.get("/inbox").json()["review_marker"]
    assert persisted["anchor_object_id"] == str(representative.id)
    tombstone_object(representative)
    db_session.flush()
    after_delete = auth_client.get("/inbox").json()["review_marker"]
    assert after_delete["anchor_object_id"] == str(representative.id)
    assert after_delete["anchor_feed_at"] == persisted["anchor_feed_at"]


def test_inbox_and_inbox_feed_use_same_projection(auth_client, db_session: Session) -> None:
    for index in range(40):
        _email(
            db_session,
            f"api-mail-{index:02d}",
            created_at=CREATED - timedelta(minutes=index + 1),
        )
    first = _yandex_occurrence(db_session, start_at=SEP_15, title="API series 15")
    _yandex_occurrence(db_session, start_at=SEP_22, title="API series 22")
    _yandex_occurrence(db_session, start_at=SEP_29, title="API series 29")
    db_session.flush()
    inbox = auth_client.get("/inbox", params={"recent_limit": 30})
    assert inbox.status_code == 200
    body = inbox.json()
    service_page = _feed(db_session).list_page(limit=30)
    inbox_ids = [item["id"] for item in body["recent_source_objects"]]
    assert inbox_ids == [str(row.id) for row in service_page.items]
    assert body["recent_has_more"] is True
    assert body["recent_next_cursor"] == service_page.next_cursor
    assert str(first.id) in inbox_ids
    assert "API series 22" not in [item["title"] for item in body["recent_source_objects"]]
    feed = auth_client.get(
        "/inbox/feed",
        params={"cursor": body["recent_next_cursor"], "limit": 30},
    )
    assert feed.status_code == 200
    continued = _feed(db_session).list_page(limit=30, cursor=service_page.next_cursor)
    assert [item["id"] for item in feed.json()["items"]] == [
        str(row.id) for row in continued.items
    ]
    assert feed.json()["has_more"] == continued.has_more
    assert feed.json()["next_cursor"] == continued.next_cursor


def test_today_search_detail_and_bookmarks_keep_all_occurrences(
    auth_client, db_session: Session
) -> None:
    occurrences = [
        _yandex_occurrence(
            db_session,
            start_at=start,
            title=f"YandexWeeklyAlpha {start.date().isoformat()}",
        )
        for start in (SEP_15, SEP_22, SEP_29)
    ]
    db_session.flush()
    stored_ids = [row.id for row in occurrences]
    assert _inbox_ids(db_session) == [occurrences[0].id]
    for obj in occurrences:
        db_session.refresh(obj)
        assert obj.start_at is not None
        assert db_session.get(Object, obj.id) is not None
        detail = auth_client.get(f"/objects/{obj.id}")
        assert detail.status_code == 200
        assert detail.json()["id"] == str(obj.id)

    today_15 = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(
        reference_at=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
        timezone="UTC",
    )
    today_22 = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(
        reference_at=datetime(2026, 9, 22, 12, 0, tzinfo=UTC),
        timezone="UTC",
    )
    assert [event.id for event in today_15["calendar_events"]] == [occurrences[0].id]
    assert [event.id for event in today_22["calendar_events"]] == [occurrences[1].id]

    for obj in occurrences:
        hits = SearchService(db_session, BOOTSTRAP_USER_ID).search(
            query=obj.title,
            kind="event",
            limit=20,
        )
        assert obj.id in {item.id for item in hits}
    search_api = auth_client.get(
        "/search",
        params={"q": "YandexWeeklyAlpha", "kind": "event", "limit": 20},
    )
    assert search_api.status_code == 200
    assert {item["id"] for item in search_api.json()} >= {str(item) for item in stored_ids}

    bookmarks = ObjectBookmarkService(db_session, BOOTSTRAP_USER_ID)
    bookmarks.upsert(occurrences[0].id, "red")
    bookmarks.upsert(occurrences[1].id, "blue")
    bookmarks.upsert(occurrences[2].id, "green")
    grouped = bookmarks.list_by_objects(stored_ids)
    assert grouped[occurrences[0].id].color == "red"
    assert grouped[occurrences[1].id].color == "blue"
    assert grouped[occurrences[2].id].color == "green"
    batch = auth_client.post(
        "/object-bookmarks/by-objects",
        json={"object_ids": [str(item) for item in stored_ids]},
    )
    assert batch.status_code == 200
    assert set(batch.json()["objects"]) == {str(item) for item in stored_ids}


def test_cross_user_future_series_is_not_grouped(db_session: Session) -> None:
    other = uuid.uuid4()
    db_session.add(User(id=other, display_name="Other calendar user"))
    db_session.flush()
    mine = _yandex_occurrence(db_session, start_at=SEP_15, title="Mine 15")
    _yandex_occurrence(db_session, start_at=SEP_22, title="Mine 22")
    _yandex_occurrence(
        db_session,
        start_at=SEP_15,
        title="Theirs 15",
        user_id=other,
    )
    db_session.flush()
    assert _inbox_titles(db_session) == ["Mine 15"]
    assert RecentSourceService(db_session, other).list_recent()[0].title == "Theirs 15"
    assert mine.user_id == BOOTSTRAP_USER_ID
