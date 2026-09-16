"""Temporal Correctness A — Inbox feed_at contract and keyset pagination."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.db.models import Edge, Job, Object, User
from app.services.errors import ValidationError
from app.services.inbox_feed_cursor import decode_inbox_feed_cursor, encode_inbox_feed_cursor
from app.services.job_queue_service import utcnow
from app.services.object_primary_date import object_primary_search_datetime
from app.services.recent_source_service import (
    RecentSourceService,
    inbox_feed_at,
    inbox_feed_at_sql,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture(autouse=True)
def _isolate(db_session: Session) -> None:
    db_session.execute(Job.__table__.delete().where(Job.user_id == BOOTSTRAP_USER_ID))
    db_session.execute(Edge.__table__.delete().where(Edge.user_id == BOOTSTRAP_USER_ID))
    db_session.execute(Object.__table__.delete().where(Object.user_id == BOOTSTRAP_USER_ID))
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


def _create(
    db_session: Session,
    *,
    title: str,
    provider: str,
    kind: str = "email",
    origin: str = "source",
    created_at: datetime,
    occurred_at: datetime | None = None,
    updated_at: datetime | None = None,
    start_at: datetime | None = None,
    object_id: UUID | None = None,
    user_id: UUID | None = None,
    metadata: dict | None = None,
) -> Object:
    owner = user_id or BOOTSTRAP_USER_ID
    obj = Object(
        id=object_id or uuid.uuid4(),
        user_id=owner,
        kind=kind,
        title=title,
        origin=origin,
        state="observed" if origin == "source" else "confirmed",
        provider=provider,
        external_id=f"ext-{uuid.uuid4()}",
        metadata_=metadata or {},
    )
    db_session.add(obj)
    db_session.flush()
    return _stamp(
        obj,
        created_at=created_at,
        occurred_at=occurred_at,
        updated_at=updated_at,
        start_at=start_at,
    )


def test_email_occurred_at_orders_and_updated_at_does_not_bump(db_session: Session) -> None:
    now = utcnow()
    older = _create(
        db_session,
        title="Old mail",
        provider="gmail",
        created_at=now - timedelta(days=10),
        occurred_at=now - timedelta(days=10),
        updated_at=now,
    )
    newer = _create(
        db_session,
        title="New mail",
        provider="gmail",
        created_at=now - timedelta(days=1),
        occurred_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
    )
    db_session.commit()
    assert inbox_feed_at(older) == older.occurred_at
    assert inbox_feed_at(newer) == newer.occurred_at
    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()
    assert [row.title for row in rows[:2]] == ["New mail", "Old mail"]


def test_email_missing_occurred_at_uses_created_at(db_session: Session) -> None:
    now = utcnow()
    obj = _create(
        db_session,
        title="No occurred",
        provider="gmail",
        created_at=now - timedelta(days=2),
        occurred_at=None,
        updated_at=now,
    )
    db_session.commit()
    db_session.refresh(obj)
    assert inbox_feed_at(obj) == obj.created_at
    sql_value = db_session.scalar(select(inbox_feed_at_sql()).where(Object.id == obj.id))
    assert sql_value == obj.created_at


def test_future_calendar_feed_at_is_not_start_primary_stays_start(db_session: Session) -> None:
    created = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    start = datetime(2026, 12, 7, 6, 30, tzinfo=UTC)
    obj = _create(
        db_session,
        title="December event",
        provider="google_calendar",
        kind="event",
        created_at=created,
        occurred_at=start,
        start_at=start,
        updated_at=created + timedelta(hours=3),
    )
    db_session.commit()
    db_session.refresh(obj)
    assert inbox_feed_at(obj) == created
    assert object_primary_search_datetime(obj) == start


def test_historical_calendar_keeps_occurrence(db_session: Session) -> None:
    created = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    start = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    obj = _create(
        db_session,
        title="August event",
        provider="google_calendar",
        kind="event",
        created_at=created,
        occurred_at=start,
        start_at=start,
    )
    db_session.commit()
    assert inbox_feed_at(obj) == start


def test_source_file_occurred_at_not_updated_at(db_session: Session) -> None:
    created = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    occurred = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    obj = _create(
        db_session,
        title="Drive file",
        provider="google_drive",
        kind="file",
        created_at=created,
        occurred_at=occurred,
        updated_at=datetime(2026, 9, 8, 20, 0, tzinfo=UTC),
    )
    db_session.commit()
    assert inbox_feed_at(obj) == occurred


def test_explicit_intake_uses_created_at(db_session: Session) -> None:
    created = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
    obj = _create(
        db_session,
        title="Note",
        provider="local_device",
        kind="note",
        origin="user",
        created_at=created,
        occurred_at=created - timedelta(days=30),
        updated_at=created + timedelta(hours=5),
    )
    db_session.commit()
    assert inbox_feed_at(obj) == created


def test_old_other_provider_not_injected_ahead_of_newer_gmail(db_session: Session) -> None:
    now = utcnow()
    for index in range(40):
        _create(
            db_session,
            title=f"gmail-{index}",
            provider="gmail",
            created_at=now - timedelta(minutes=index),
            occurred_at=now - timedelta(minutes=index),
        )
    _create(
        db_session,
        title="old-drive",
        provider="google_drive",
        kind="file",
        created_at=now - timedelta(days=40),
        occurred_at=now - timedelta(days=40),
    )
    db_session.commit()
    titles = [
        row.title
        for row in RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent(limit=30)
    ]
    assert "old-drive" not in titles
    assert titles[0] == "gmail-0"


def test_empty_feed_page(auth_client) -> None:
    response = auth_client.get("/inbox")
    assert response.status_code == 200
    body = response.json()
    assert body["recent_source_objects"] == []
    assert body["recent_next_cursor"] is None
    assert body["recent_has_more"] is False


def test_first_and_final_pages_and_has_more(auth_client, db_session: Session) -> None:
    now = utcnow()
    for index in range(35):
        _create(
            db_session,
            title=f"row-{index:02d}",
            provider="gmail",
            created_at=now - timedelta(minutes=index),
            occurred_at=now - timedelta(minutes=index),
        )
    db_session.commit()
    first = auth_client.get("/inbox", params={"recent_limit": 30})
    assert first.status_code == 200
    body = first.json()
    assert len(body["recent_source_objects"]) == 30
    assert body["recent_has_more"] is True
    cursor = body["recent_next_cursor"]
    assert cursor
    decode_inbox_feed_cursor(cursor)
    second = auth_client.get("/inbox/feed", params={"cursor": cursor, "limit": 30})
    assert second.status_code == 200
    page = second.json()
    assert len(page["items"]) == 5
    assert page["has_more"] is False
    assert page["next_cursor"] is None
    first_ids = [item["id"] for item in body["recent_source_objects"]]
    second_ids = [item["id"] for item in page["items"]]
    assert len(set(first_ids) & set(second_ids)) == 0
    canonical = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent(limit=50)
    assert [str(row.id) for row in canonical] == first_ids + second_ids


def test_page_size_max_50(auth_client, db_session: Session) -> None:
    now = utcnow()
    for index in range(60):
        _create(
            db_session,
            title=f"cap-{index}",
            provider="gmail",
            created_at=now - timedelta(minutes=index),
            occurred_at=now - timedelta(minutes=index),
        )
    db_session.commit()
    ok = auth_client.get("/inbox", params={"recent_limit": 50})
    assert ok.status_code == 200
    assert len(ok.json()["recent_source_objects"]) == 50
    rejected = auth_client.get("/inbox", params={"recent_limit": 51})
    assert rejected.status_code == 422


def test_malformed_cursor_is_422(auth_client) -> None:
    response = auth_client.get("/inbox/feed", params={"cursor": "not-a-cursor"})
    assert response.status_code == 422


def test_same_feed_at_tie_orders_by_uuid(db_session: Session) -> None:
    stamp = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    low = UUID("00000000-0000-4000-8000-000000000010")
    high = UUID("00000000-0000-4000-8000-0000000000ff")
    _create(
        db_session,
        title="low-id",
        provider="gmail",
        created_at=stamp,
        occurred_at=stamp,
        object_id=low,
    )
    _create(
        db_session,
        title="high-id",
        provider="gmail",
        created_at=stamp,
        occurred_at=stamp,
        object_id=high,
    )
    db_session.commit()
    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()
    assert [row.title for row in rows] == ["high-id", "low-id"]
    page = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_page(limit=1)
    assert page.items[0].title == "high-id"
    next_page = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_page(
        limit=1, cursor=page.next_cursor
    )
    assert next_page.items[0].title == "low-id"


def test_insert_above_cursor_does_not_shift_continuation(db_session: Session) -> None:
    now = utcnow()
    for index in range(5):
        _create(
            db_session,
            title=f"old-{index}",
            provider="gmail",
            created_at=now - timedelta(minutes=10 + index),
            occurred_at=now - timedelta(minutes=10 + index),
        )
    db_session.commit()
    page1 = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_page(limit=2)
    cursor = page1.next_cursor
    expected_second = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_page(
        limit=2, cursor=cursor
    )
    _create(
        db_session,
        title="brand-new",
        provider="gmail",
        created_at=now,
        occurred_at=now,
    )
    db_session.commit()
    continued = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_page(
        limit=2, cursor=cursor
    )
    assert [row.id for row in continued.items] == [row.id for row in expected_second.items]
    assert all(row.title != "brand-new" for row in continued.items)
    head = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_page(limit=2)
    assert head.items[0].title == "brand-new"


def test_cross_user_rows_excluded(db_session: Session) -> None:
    now = utcnow()
    other = uuid.uuid4()
    db_session.add(User(id=other, display_name="Other"))
    db_session.flush()
    _create(
        db_session,
        title="mine",
        provider="gmail",
        created_at=now,
        occurred_at=now,
    )
    _create(
        db_session,
        title="theirs",
        provider="gmail",
        created_at=now,
        occurred_at=now,
        user_id=other,
    )
    db_session.commit()
    titles = [
        row.title for row in RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()
    ]
    assert titles == ["mine"]


def test_gmail_noise_and_child_attachment_excluded(db_session: Session) -> None:
    now = utcnow()
    _create(
        db_session,
        title="ok",
        provider="gmail",
        created_at=now,
        occurred_at=now,
        metadata={"labels": ["INBOX"]},
    )
    _create(
        db_session,
        title="promo",
        provider="gmail",
        created_at=now,
        occurred_at=now,
        metadata={"labels": ["CATEGORY_PROMOTIONS"]},
    )
    parent_id = uuid.uuid4()
    _create(
        db_session,
        title="parent",
        provider="gmail",
        created_at=now,
        occurred_at=now,
        object_id=parent_id,
    )
    _create(
        db_session,
        title="child.bin",
        provider="gmail",
        kind="file",
        created_at=now,
        occurred_at=now,
        metadata={"parent_email_id": str(parent_id)},
    )
    db_session.commit()
    titles = {
        row.title for row in RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()
    }
    assert "ok" in titles
    assert "parent" in titles
    assert "promo" not in titles
    assert "child.bin" not in titles


def test_page_query_is_bounded(db_session: Session) -> None:
    now = utcnow()
    for index in range(8):
        _create(
            db_session,
            title=f"q-{index}",
            provider="gmail",
            created_at=now - timedelta(minutes=index),
            occurred_at=now - timedelta(minutes=index),
        )
    db_session.commit()
    statements: list[str] = []
    bind = db_session.get_bind()

    def _capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", _capture)
    try:
        RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_page(limit=5)
    finally:
        event.remove(bind, "before_cursor_execute", _capture)
    select_statements = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert len(select_statements) == 1
    assert "row_number" not in select_statements[0].lower()


def test_cursor_roundtrip() -> None:
    stamp = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
    object_id = UUID("12345678-1234-4000-8000-1234567890ab")
    encoded = encode_inbox_feed_cursor(stamp, object_id)
    decoded_at, decoded_id = decode_inbox_feed_cursor(encoded)
    assert decoded_id == object_id
    assert decoded_at == stamp
    with pytest.raises(ValidationError):
        decode_inbox_feed_cursor("%%%")
