"""Inbox feed uses source chronology and hides child email attachments."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ObjectCreate
from app.db.models import Edge, Job, Object, User
from app.domain.object_visibility import tombstone_object
from app.services.correlation_constants import EDGE_TYPE_CONTAINS
from app.services.email_attachment_service import EmailAttachmentService
from app.services.graph_service import GraphService
from app.services.job_queue_service import utcnow
from app.services.object_primary_date import object_primary_search_datetime
from app.services.object_query_service import ObjectQueryService
from app.services.recent_source_service import (
    RecentSourceService,
    inbox_feed_at,
    inbox_feed_at_sql,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture(autouse=True)
def _isolate_recent_objects(db_session: Session) -> None:
    db_session.execute(Job.__table__.delete().where(Job.user_id == BOOTSTRAP_USER_ID))
    db_session.execute(Edge.__table__.delete().where(Edge.user_id == BOOTSTRAP_USER_ID))
    db_session.execute(
        Object.__table__.delete().where(Object.user_id == BOOTSTRAP_USER_ID)
    )
    db_session.commit()


def _stamp(
    obj: Object,
    *,
    created_at: datetime,
    occurred_at: datetime | None = None,
    updated_at: datetime | None = None,
    start_at: datetime | None = None,
) -> Object:
    obj.created_at = created_at
    obj.updated_at = updated_at if updated_at is not None else created_at
    obj.occurred_at = occurred_at
    if start_at is not None:
        obj.start_at = start_at
    return obj


def _create_source(
    graph: GraphService,
    db_session: Session,
    *,
    title: str,
    provider: str,
    kind: str = "email",
    created_at: datetime,
    occurred_at: datetime | None = None,
    updated_at: datetime | None = None,
    start_at: datetime | None = None,
    origin: str = "source",
    state: str = "observed",
    metadata: dict | None = None,
    user_id: uuid.UUID | None = None,
) -> Object:
    if user_id is not None:
        graph = GraphService(db_session, user_id)
    graph.create_object(
        ObjectCreate(
            kind=kind,
            title=title,
            origin=origin,
            state=state,
            provider=provider,
            external_id=f"ext-{uuid.uuid4()}",
            start_at=start_at,
            metadata=metadata or {},
        )
    )
    obj = db_session.scalar(select(Object).where(Object.title == title))
    assert obj is not None
    return _stamp(
        obj,
        created_at=created_at,
        occurred_at=occurred_at,
        updated_at=updated_at,
        start_at=start_at,
    )


def _titles(db_session: Session, limit: int = 30) -> list[str]:
    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent(limit=limit)
    return [row.title for row in rows]


def test_backfilled_old_email_does_not_rank_above_newer_source_email(
    db_session: Session,
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    now = utcnow()
    _create_source(
        graph,
        db_session,
        title="NEW email",
        provider="gmail",
        created_at=now - timedelta(days=1),
        occurred_at=now,
    )
    _create_source(
        graph,
        db_session,
        title="BACKFILLED email",
        provider="yandex_mail",
        created_at=now,
        occurred_at=now - timedelta(days=60),
    )
    db_session.commit()

    assert _titles(db_session, limit=5)[:2] == ["NEW email", "BACKFILLED email"]


def test_source_emails_follow_occurred_at_not_created_at(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    now = utcnow()
    for index, days_ago in enumerate((3, 1, 2)):
        _create_source(
            graph,
            db_session,
            title=f"email-{days_ago}",
            provider="gmail",
            created_at=now - timedelta(minutes=index),
            occurred_at=now - timedelta(days=days_ago),
        )
    db_session.commit()

    assert _titles(db_session, limit=5)[:3] == ["email-1", "email-2", "email-3"]


def test_source_events_rank_by_start_at_not_ingest_time(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    now = utcnow()
    _create_source(
        graph,
        db_session,
        title="Old start newly imported",
        provider="google_calendar",
        kind="event",
        created_at=now,
        occurred_at=now - timedelta(days=40),
        start_at=now - timedelta(days=40),
    )
    _create_source(
        graph,
        db_session,
        title="Newer event",
        provider="google_calendar",
        kind="event",
        created_at=now - timedelta(hours=2),
        occurred_at=now - timedelta(days=1),
        start_at=now - timedelta(days=1),
    )
    _create_source(
        graph,
        db_session,
        title="Calendar event fallback",
        provider="yandex_calendar",
        kind="calendar_event",
        created_at=now - timedelta(hours=1),
        occurred_at=now - timedelta(days=2),
        start_at=now - timedelta(days=2),
    )
    db_session.commit()

    assert _titles(db_session, limit=5)[:3] == [
        "Newer event",
        "Calendar event fallback",
        "Old start newly imported",
    ]


def test_source_chat_and_message_follow_occurred_at(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    now = utcnow()
    _create_source(
        graph,
        db_session,
        title="Old chat",
        provider="mattermost",
        kind="chat_message",
        created_at=now,
        occurred_at=now - timedelta(days=10),
    )
    _create_source(
        graph,
        db_session,
        title="New message",
        provider="mattermost",
        kind="message",
        created_at=now - timedelta(hours=3),
        occurred_at=now - timedelta(hours=1),
    )
    db_session.commit()

    assert _titles(db_session, limit=5)[:2] == ["New message", "Old chat"]


def test_explicit_intake_ranks_by_created_at(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    now = utcnow()
    _create_source(
        graph,
        db_session,
        title="Old source email",
        provider="gmail",
        created_at=now - timedelta(hours=1),
        occurred_at=now - timedelta(days=20),
    )
    local = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        title="Just added local file",
        origin="explicit",
        state="confirmed",
        provider="local_device",
        external_id=f"local-{uuid.uuid4()}",
        metadata_={"modified_at": (now - timedelta(days=400)).isoformat()},
        occurred_at=now - timedelta(days=400),
    )
    db_session.add(local)
    db_session.flush()
    _stamp(local, created_at=now, occurred_at=now - timedelta(days=400))
    user_note = graph.create_object(
        ObjectCreate(
            kind="note",
            title="User note now",
            origin="user",
            state="confirmed",
        )
    )
    _stamp(user_note, created_at=now - timedelta(minutes=1), occurred_at=now - timedelta(days=30))
    db_session.commit()

    titles = _titles(db_session, limit=10)
    assert titles.index("Just added local file") < titles.index("Old source email")
    assert titles.index("User note now") < titles.index("Old source email")


def _gmail_parent_with_attachment(db_session: Session, *, title: str, created_at: datetime) -> Object:
    parent = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        title=title,
        origin="source",
        state="observed",
        provider="gmail",
        external_id=f"gmail-{uuid.uuid4()}",
        body="parent body",
        metadata_={},
        occurred_at=created_at,
    )
    db_session.add(parent)
    db_session.flush()
    _stamp(parent, created_at=created_at, occurred_at=created_at)
    EmailAttachmentService(db_session, BOOTSTRAP_USER_ID).materialize_gmail_attachments(
        parent,
        [
            {
                "attachment_key": "att-ics",
                "attachment_id": "att-ics",
                "filename": "event.ics",
                "mime_type": "text/calendar",
                "size": 16,
            }
        ],
        lambda _desc: b"BEGIN:VCALENDAR",
    )
    return parent


def _yandex_parent_with_attachment(db_session: Session, *, title: str, created_at: datetime) -> Object:
    parent = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        title=title,
        origin="source",
        state="observed",
        provider="yandex_mail",
        external_id=f"yandex-{uuid.uuid4()}",
        metadata_={},
        occurred_at=created_at,
    )
    db_session.add(parent)
    db_session.flush()
    _stamp(parent, created_at=created_at, occurred_at=created_at)
    EmailAttachmentService(db_session, BOOTSTRAP_USER_ID).materialize_yandex_attachments(
        parent,
        [
            {
                "part_key": "part-0",
                "filename": "event.ics",
                "mime_type": "text/calendar",
                "size": 8,
                "inline_bytes": b"ICS-DATA",
            }
        ],
    )
    return parent


def test_gmail_attachment_hidden_parent_visible(db_session: Session) -> None:
    now = utcnow()
    parent = _gmail_parent_with_attachment(db_session, title="Gmail parent", created_at=now)
    db_session.commit()
    titles = _titles(db_session)
    assert "Gmail parent" in titles
    assert "event.ics" not in titles
    attachment = db_session.scalar(
        select(Object).where(Object.title == "event.ics", Object.provider == "gmail")
    )
    assert attachment is not None
    assert attachment.metadata_["parent_email_id"] == str(parent.id)


def test_yandex_attachment_hidden_parent_visible(db_session: Session) -> None:
    now = utcnow()
    _yandex_parent_with_attachment(db_session, title="Yandex parent", created_at=now)
    db_session.commit()
    titles = _titles(db_session)
    assert "Yandex parent" in titles
    assert "event.ics" not in titles


def test_standalone_source_file_without_parent_email_id_visible(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    now = utcnow()
    _create_source(
        graph,
        db_session,
        title="Drive file",
        provider="google_drive",
        kind="file",
        created_at=now,
        occurred_at=now,
    )
    empty_parent = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        title="Empty parent key file",
        origin="source",
        state="observed",
        provider="google_drive",
        external_id=f"drive-{uuid.uuid4()}",
        metadata_={"parent_email_id": ""},
        occurred_at=now,
    )
    db_session.add(empty_parent)
    db_session.flush()
    _stamp(empty_parent, created_at=now, occurred_at=now)
    db_session.commit()
    titles = set(_titles(db_session))
    assert "Drive file" in titles
    assert "Empty parent key file" in titles


def test_attachment_remains_gettable_queryable_and_linked(db_session: Session) -> None:
    now = utcnow()
    parent = _gmail_parent_with_attachment(db_session, title="Linked parent", created_at=now)
    db_session.commit()
    attachment = db_session.scalar(
        select(Object).where(Object.title == "event.ics", Object.provider == "gmail")
    )
    assert attachment is not None
    loaded = GraphService(db_session, BOOTSTRAP_USER_ID).get_object(attachment.id)
    assert loaded.id == attachment.id
    queried = ObjectQueryService(db_session, BOOTSTRAP_USER_ID).query(kinds=["file"])
    assert any(row.id == attachment.id for row in queried)
    edge = db_session.scalar(
        select(Edge).where(
            Edge.source_id == parent.id,
            Edge.target_id == attachment.id,
            Edge.type == EDGE_TYPE_CONTAINS,
        )
    )
    assert edge is not None
    db_session.refresh(attachment)
    assert attachment.deleted_at is None
    assert attachment.origin == "source"
    assert attachment.kind == "file"


def test_provider_reservation_uses_inbox_feed_at_not_created_at(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    now = utcnow()
    old = now - timedelta(days=80)
    for index in range(8):
        _create_source(
            graph,
            db_session,
            title=f"stale-provider-{index}",
            provider=f"stale_{index}",
            created_at=now - timedelta(seconds=index),
            occurred_at=old - timedelta(seconds=index),
        )
    _create_source(
        graph,
        db_session,
        title="genuinely recent gmail",
        provider="gmail",
        created_at=now - timedelta(days=2),
        occurred_at=now,
    )
    db_session.commit()

    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent(limit=8)
    titles = [row.title for row in rows]
    assert "genuinely recent gmail" in titles
    assert titles[0] == "genuinely recent gmail"


def test_attachments_do_not_consume_reserved_provider_slots(db_session: Session) -> None:
    now = utcnow()
    parent = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        title="Parent with many attachments",
        origin="source",
        state="observed",
        provider="gmail",
        external_id=f"gmail-parent-{uuid.uuid4()}",
        metadata_={},
        occurred_at=now,
    )
    db_session.add(parent)
    db_session.flush()
    _stamp(parent, created_at=now, occurred_at=now)
    descriptors = [
        {
            "attachment_key": f"att-{index}",
            "attachment_id": f"att-{index}",
            "filename": f"child-{index}.bin",
            "mime_type": "application/octet-stream",
            "size": 4,
        }
        for index in range(5)
    ]
    EmailAttachmentService(db_session, BOOTSTRAP_USER_ID).materialize_gmail_attachments(
        parent,
        descriptors,
        lambda _desc: b"data",
    )
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    for index in range(3):
        _create_source(
            graph,
            db_session,
            title=f"Other gmail {index}",
            provider="gmail",
            created_at=now - timedelta(minutes=index + 1),
            occurred_at=now - timedelta(minutes=index + 1),
        )
    db_session.commit()

    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent(limit=30)
    gmail_titles = [row.title for row in rows if row.provider == "gmail"]
    assert "Parent with many attachments" in gmail_titles
    assert all(not title.startswith("child-") for title in gmail_titles)
    assert sum(1 for title in gmail_titles if title.startswith("Other gmail")) == 3


def test_chronology_applied_before_limit(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    now = utcnow()
    for index in range(12):
        _create_source(
            graph,
            db_session,
            title=f"recent-{index}",
            provider="gmail",
            created_at=now - timedelta(days=2, minutes=index),
            occurred_at=now - timedelta(minutes=index),
        )
    _create_source(
        graph,
        db_session,
        title="old-backfill",
        provider="gmail",
        created_at=now,
        occurred_at=now - timedelta(days=90),
    )
    db_session.commit()

    titles = _titles(db_session, limit=5)
    assert len(titles) == 5
    assert "old-backfill" not in titles
    assert titles == [f"recent-{index}" for index in range(5)]


def test_equal_inbox_feed_at_is_deterministic_by_id(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    now = utcnow()
    first = _create_source(
        graph,
        db_session,
        title="tie-a",
        provider="gmail",
        created_at=now,
        occurred_at=now,
    )
    second = _create_source(
        graph,
        db_session,
        title="tie-b",
        provider="gmail",
        created_at=now,
        occurred_at=now,
    )
    db_session.commit()
    expected = sorted((first, second), key=lambda obj: (inbox_feed_at(obj), obj.id), reverse=True)
    first_pass = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent(limit=5)
    second_pass = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent(limit=5)
    assert [row.id for row in first_pass[:2]] == [row.id for row in expected]
    assert [row.id for row in first_pass] == [row.id for row in second_pass]


def test_other_user_rejected_deleted_and_gmail_noise_remain_excluded(
    db_session: Session,
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    now = utcnow()
    _create_source(
        graph,
        db_session,
        title="Visible own",
        provider="gmail",
        created_at=now,
        occurred_at=now,
        metadata={"labels": ["INBOX"]},
    )
    _create_source(
        graph,
        db_session,
        title="Rejected own",
        provider="gmail",
        created_at=now,
        occurred_at=now,
        state="rejected",
    )
    deleted = _create_source(
        graph,
        db_session,
        title="Deleted own",
        provider="gmail",
        created_at=now,
        occurred_at=now,
    )
    tombstone_object(deleted)
    _create_source(
        graph,
        db_session,
        title="Gmail promo",
        provider="gmail",
        created_at=now,
        occurred_at=now,
        metadata={"labels": ["CATEGORY_PROMOTIONS"]},
    )
    other_id = uuid.uuid4()
    db_session.add(User(id=other_id, display_name="Other"))
    db_session.flush()
    _create_source(
        graph,
        db_session,
        title="Other user email",
        provider="gmail",
        created_at=now,
        occurred_at=now,
        user_id=other_id,
    )
    db_session.commit()

    titles = set(_titles(db_session))
    assert titles == {"Visible own"}


def test_inbox_api_order_hides_attachments_and_keeps_contract(
    auth_client,
    db_session: Session,
) -> None:
    now = utcnow()
    parent = _gmail_parent_with_attachment(
        db_session, title="API parent email", created_at=now
    )
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    _create_source(
        graph,
        db_session,
        title="API older email",
        provider="yandex_mail",
        created_at=now,
        occurred_at=now - timedelta(days=10),
    )
    db_session.commit()

    response = auth_client.get("/inbox")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "unresolved_notifications",
        "recent_source_objects",
        "source_sync_status",
        "recent_next_cursor",
        "recent_has_more",
        "review_marker",
    }
    recent = body["recent_source_objects"]
    titles = [item["title"] for item in recent]
    assert "API parent email" in titles
    assert "event.ics" not in titles
    assert titles.index("API parent email") < titles.index("API older email")
    parent_row = next(item for item in recent if item["title"] == "API parent email")
    assert set(parent_row) == {
        "id",
        "title",
        "kind",
        "provider",
        "origin",
        "state",
        "status",
        "primary_at",
        "feed_at",
        "excerpt",
    }
    db_session.refresh(parent)
    expected_primary = object_primary_search_datetime(parent)
    assert parent_row["primary_at"].startswith(expected_primary.isoformat()[:19])
    assert isinstance(body["unresolved_notifications"], list)
    assert isinstance(body["source_sync_status"], list)


def test_explicit_file_with_parent_email_id_metadata_still_visible(
    db_session: Session,
) -> None:
    now = utcnow()
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        title="Explicit with similar metadata",
        origin="user",
        state="confirmed",
        provider="local_device",
        external_id=f"local-{uuid.uuid4()}",
        metadata_={"parent_email_id": str(uuid.uuid4())},
    )
    db_session.add(obj)
    db_session.flush()
    _stamp(obj, created_at=now, occurred_at=now - timedelta(days=9))
    db_session.commit()
    assert "Explicit with similar metadata" in _titles(db_session)


def _assert_feed_sql_matches_python(db_session: Session, obj: Object) -> None:
    sql_value = db_session.scalar(select(inbox_feed_at_sql()).where(Object.id == obj.id))
    python_value = inbox_feed_at(obj)
    assert sql_value is not None

    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    assert _utc(sql_value) == _utc(python_value)


def test_future_november_events_do_not_outrank_september_email(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    sep = datetime(2026, 9, 6, 12, 0, tzinfo=utcnow().tzinfo)
    _create_source(
        graph,
        db_session,
        title="Event Nov 27",
        provider="google_calendar",
        kind="event",
        created_at=datetime(2026, 8, 20, 9, 0, tzinfo=sep.tzinfo),
        occurred_at=datetime(2026, 11, 27, 6, 0, tzinfo=sep.tzinfo),
        start_at=datetime(2026, 11, 27, 6, 0, tzinfo=sep.tzinfo),
    )
    _create_source(
        graph,
        db_session,
        title="Event Nov 25",
        provider="google_calendar",
        kind="event",
        created_at=datetime(2026, 8, 19, 9, 0, tzinfo=sep.tzinfo),
        occurred_at=datetime(2026, 11, 25, 6, 0, tzinfo=sep.tzinfo),
        start_at=datetime(2026, 11, 25, 6, 0, tzinfo=sep.tzinfo),
    )
    _create_source(
        graph,
        db_session,
        title="Recent Sep email",
        provider="gmail",
        created_at=sep,
        occurred_at=sep,
    )
    db_session.commit()

    titles = _titles(db_session, limit=5)
    assert titles[0] == "Recent Sep email"
    assert titles.index("Recent Sep email") < titles.index("Event Nov 27")
    assert titles.index("Recent Sep email") < titles.index("Event Nov 25")


def test_future_events_rank_by_discovery_not_future_start(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    tz = utcnow().tzinfo
    event_a = _create_source(
        graph,
        db_session,
        title="Event A Nov 30",
        provider="google_calendar",
        kind="event",
        created_at=datetime(2026, 9, 1, 12, 0, tzinfo=tz),
        occurred_at=datetime(2026, 11, 30, 6, 0, tzinfo=tz),
        start_at=datetime(2026, 11, 30, 6, 0, tzinfo=tz),
    )
    event_b = _create_source(
        graph,
        db_session,
        title="Event B Oct 10",
        provider="google_calendar",
        kind="event",
        created_at=datetime(2026, 9, 5, 12, 0, tzinfo=tz),
        occurred_at=datetime(2026, 10, 10, 6, 0, tzinfo=tz),
        start_at=datetime(2026, 10, 10, 6, 0, tzinfo=tz),
    )
    db_session.commit()
    db_session.refresh(event_a)
    db_session.refresh(event_b)
    assert inbox_feed_at(event_a) == event_a.created_at
    assert inbox_feed_at(event_b) == event_b.created_at
    _assert_feed_sql_matches_python(db_session, event_a)
    _assert_feed_sql_matches_python(db_session, event_b)
    assert _titles(db_session, limit=5)[:2] == ["Event B Oct 10", "Event A Nov 30"]


def test_historical_calendar_backfill_uses_event_time(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    tz = utcnow().tzinfo
    start = datetime(2026, 7, 10, 10, 0, tzinfo=tz)
    created = datetime(2026, 9, 6, 12, 0, tzinfo=tz)
    obj = _create_source(
        graph,
        db_session,
        title="July event imported Sep",
        provider="yandex_calendar",
        kind="event",
        created_at=created,
        occurred_at=start,
        start_at=start,
    )
    db_session.commit()
    db_session.refresh(obj)
    assert inbox_feed_at(obj) == start
    _assert_feed_sql_matches_python(db_session, obj)


def test_newly_discovered_future_event_is_capped_at_created_at(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    tz = utcnow().tzinfo
    start = datetime(2026, 11, 27, 6, 0, tzinfo=tz)
    created = datetime(2026, 9, 6, 12, 0, tzinfo=tz)
    obj = _create_source(
        graph,
        db_session,
        title="Future discovered today",
        provider="google_calendar",
        kind="event",
        created_at=created,
        occurred_at=start,
        start_at=start,
    )
    db_session.commit()
    db_session.refresh(obj)
    assert inbox_feed_at(obj) == created
    _assert_feed_sql_matches_python(db_session, obj)


def test_calendar_occurred_at_fallback_and_created_at_only(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    tz = utcnow().tzinfo
    created = datetime(2026, 9, 6, 12, 0, tzinfo=tz)
    occurred = datetime(2026, 8, 15, 8, 0, tzinfo=tz)
    with_occurred = _create_source(
        graph,
        db_session,
        title="No start uses occurred",
        provider="google_calendar",
        kind="event",
        created_at=created,
        occurred_at=occurred,
    )
    with_occurred.start_at = None
    created_only = _create_source(
        graph,
        db_session,
        title="No start no occurred",
        provider="google_calendar",
        kind="calendar_event",
        created_at=created,
    )
    created_only.start_at = None
    created_only.occurred_at = None
    db_session.commit()
    db_session.refresh(with_occurred)
    db_session.refresh(created_only)
    assert inbox_feed_at(with_occurred) == occurred
    assert inbox_feed_at(created_only) == created
    _assert_feed_sql_matches_python(db_session, with_occurred)
    _assert_feed_sql_matches_python(db_session, created_only)


def test_calendar_updated_at_does_not_promote_old_event(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    tz = utcnow().tzinfo
    start = datetime(2026, 8, 1, 10, 0, tzinfo=tz)
    obj = _create_source(
        graph,
        db_session,
        title="Old calendar occurrence",
        provider="google_calendar",
        kind="event",
        created_at=start,
        occurred_at=start,
        start_at=start,
        updated_at=start,
    )
    obj.updated_at = datetime(2026, 9, 7, 8, 0, tzinfo=tz)
    db_session.commit()
    db_session.refresh(obj)
    assert inbox_feed_at(obj) == start
    _assert_feed_sql_matches_python(db_session, obj)


def test_inbox_primary_at_stays_start_at_while_feed_uses_created_at(
    auth_client,
    db_session: Session,
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    tz = utcnow().tzinfo
    start = datetime(2026, 11, 27, 6, 0, tzinfo=tz)
    created = datetime(2026, 9, 1, 12, 0, tzinfo=tz)
    email_at = datetime(2026, 9, 6, 12, 0, tzinfo=tz)
    event = _create_source(
        graph,
        db_session,
        title="November meeting",
        provider="google_calendar",
        kind="event",
        created_at=created,
        occurred_at=start,
        start_at=start,
    )
    _create_source(
        graph,
        db_session,
        title="September mail",
        provider="gmail",
        created_at=email_at,
        occurred_at=email_at,
    )
    db_session.commit()
    db_session.refresh(event)
    expected_primary = object_primary_search_datetime(event)
    assert expected_primary == start
    assert inbox_feed_at(event) == created

    response = auth_client.get("/inbox")
    assert response.status_code == 200
    recent = response.json()["recent_source_objects"]
    titles = [item["title"] for item in recent]
    assert titles.index("September mail") < titles.index("November meeting")
    row = next(item for item in recent if item["title"] == "November meeting")
    assert row["primary_at"].startswith(expected_primary.isoformat()[:19])


def test_future_calendar_provider_does_not_outrank_recent_gmail(db_session: Session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    tz = utcnow().tzinfo
    imported = datetime(2026, 8, 10, 12, 0, tzinfo=tz)
    for index in range(5):
        start = datetime(2026, 11, 16 + index, 6, 0, tzinfo=tz)
        _create_source(
            graph,
            db_session,
            title=f"Future GC {index}",
            provider="google_calendar",
            kind="event",
            created_at=imported - timedelta(days=index),
            occurred_at=start,
            start_at=start,
        )
    _create_source(
        graph,
        db_session,
        title="Gmail today",
        provider="gmail",
        created_at=datetime(2026, 9, 6, 12, 0, tzinfo=tz),
        occurred_at=datetime(2026, 9, 6, 12, 0, tzinfo=tz),
    )
    db_session.commit()

    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent(limit=10)
    assert rows[0].title == "Gmail today"
    assert rows[0].provider == "gmail"


def test_future_events_do_not_displace_recent_mail_before_limit(
    db_session: Session,
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    tz = utcnow().tzinfo
    imported = datetime(2026, 8, 1, 12, 0, tzinfo=tz)
    for index in range(12):
        start = datetime(2026, 11, 10, 6, 0, tzinfo=tz) + timedelta(days=index)
        _create_source(
            graph,
            db_session,
            title=f"Future far {index}",
            provider="google_calendar",
            kind="event",
            created_at=imported - timedelta(minutes=index),
            occurred_at=start,
            start_at=start,
        )
    for index in range(8):
        when = datetime(2026, 9, 6, 12, 0, tzinfo=tz) - timedelta(minutes=index)
        _create_source(
            graph,
            db_session,
            title=f"Recent mail {index}",
            provider="gmail",
            created_at=when,
            occurred_at=when,
        )
    db_session.commit()

    titles = _titles(db_session, limit=30)
    assert titles[:8] == [f"Recent mail {index}" for index in range(8)]
    assert all(not title.startswith("Future far") for title in titles[:8])
