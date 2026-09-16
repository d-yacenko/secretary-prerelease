"""Inbox Workflow Controls A — review marker and object bookmarks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, inspect, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import ObjectCreate
from app.db.models import InboxReviewMarker, Object, ObjectBookmark, User
from app.domain.object_bookmarks import BOOKMARKS_BY_OBJECTS_MAX
from app.domain.object_visibility import tombstone_object
from app.main import app
from app.services.graph_service import GraphService
from app.services.inbox_review_marker import (
    InboxReviewMarkerService,
    feed_tuple_is_newer,
    item_is_at_or_above_marker,
)
from app.services.object_bookmark_service import ObjectBookmarkService
from app.services.object_deletion_service import ObjectDeletionService
from app.services.recent_source_service import inbox_feed_at
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient


@pytest.fixture
def wf_client(db_session, auth_headers):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as raw:
        yield AuthTestClient(raw, auth_headers)
    app.dependency_overrides.clear()


def _stamp(obj: Object, created_at: datetime, occurred_at: datetime | None = None) -> Object:
    obj.created_at = created_at
    obj.updated_at = created_at
    obj.occurred_at = occurred_at
    return obj


def _email(
    db_session: Session,
    title: str,
    *,
    created_at: datetime,
    occurred_at: datetime | None = None,
    object_id: UUID | None = None,
    user_id: UUID | None = None,
) -> Object:
    owner = user_id or BOOTSTRAP_USER_ID
    obj = Object(
        id=object_id or uuid.uuid4(),
        user_id=owner,
        kind="email",
        title=title,
        origin="source",
        state="observed",
        provider="gmail",
        external_id=f"ext-{uuid.uuid4()}",
        metadata_={},
    )
    db_session.add(obj)
    db_session.flush()
    return _stamp(obj, created_at, occurred_at or created_at)


def test_migration_0034_from_0033(db_session: Session) -> None:
    versions = sorted(
        path.name
        for path in (Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("*.py")
        if path.name[0].isdigit()
    )
    assert any(name.startswith("0034_inbox_workflow_controls") for name in versions)
    module_path = (
        Path(__file__).resolve().parents[1] / "alembic/versions/0034_inbox_workflow_controls.py"
    )
    text_src = module_path.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "0033"' in text_src
    assert "inbox_review_markers" in text_src
    assert "object_bookmarks" in text_src
    inspector = inspect(db_session.bind)
    names = inspector.get_table_names()
    assert "inbox_review_markers" in names
    assert "object_bookmarks" in names


def test_feed_tuple_helpers_same_feed_at_uuid() -> None:
    t = datetime(2026, 9, 9, 12, tzinfo=UTC)
    low = UUID("00000000-0000-4000-8000-000000000001")
    high = UUID("00000000-0000-4000-8000-000000000002")
    assert feed_tuple_is_newer(t, high, t, low)
    assert item_is_at_or_above_marker(t, high, t, low)
    assert not item_is_at_or_above_marker(t, low, t, high)
    assert item_is_at_or_above_marker(t, high, t, high)


def test_inbox_marker_absent_initially(wf_client) -> None:
    response = wf_client.get("/inbox")
    assert response.status_code == 200
    assert response.json()["review_marker"] is None


def test_set_and_move_marker_uses_server_feed_at(wf_client, db_session: Session) -> None:
    now = datetime(2026, 9, 1, 12, tzinfo=UTC)
    older = _email(db_session, "older", created_at=now - timedelta(days=2))
    newer = _email(db_session, "newer", created_at=now)
    db_session.flush()
    first = wf_client.put("/inbox/review-marker", json={"after_object_id": str(older.id)})
    assert first.status_code == 200
    body = first.json()
    assert body["anchor_object_id"] == str(older.id)
    assert datetime.fromisoformat(body["anchor_feed_at"]) == inbox_feed_at(older)
    second = wf_client.put("/inbox/review-marker", json={"after_object_id": str(newer.id)})
    assert second.status_code == 200
    assert second.json()["anchor_object_id"] == str(newer.id)
    count = db_session.scalar(select(func.count()).select_from(InboxReviewMarker))
    assert int(count or 0) == 1
    inbox = wf_client.get("/inbox").json()
    assert inbox["review_marker"]["anchor_object_id"] == str(newer.id)


def test_marker_rejects_foreign_and_missing_without_leak(wf_client, db_session: Session) -> None:
    other = uuid.uuid4()
    db_session.add(User(id=other, display_name="foreign-marker"))
    db_session.flush()
    foreign = _email(
        db_session,
        "secret",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        user_id=other,
    )
    missing = uuid.uuid4()
    foreign_resp = wf_client.put("/inbox/review-marker", json={"after_object_id": str(foreign.id)})
    missing_resp = wf_client.put("/inbox/review-marker", json={"after_object_id": str(missing)})
    assert foreign_resp.status_code == 404
    assert missing_resp.status_code == 404
    assert foreign_resp.json()["detail"] == missing_resp.json()["detail"] == "object not found"


def test_newer_object_does_not_move_persisted_boundary(wf_client, db_session: Session) -> None:
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    anchor = _email(db_session, "anchor", created_at=t0)
    wf_client.put("/inbox/review-marker", json={"after_object_id": str(anchor.id)})
    _email(db_session, "brand-new", created_at=t0 + timedelta(days=1))
    db_session.flush()
    marker = wf_client.get("/inbox").json()["review_marker"]
    assert marker["anchor_object_id"] == str(anchor.id)
    assert datetime.fromisoformat(marker["anchor_feed_at"]) == inbox_feed_at(anchor)


def test_deleted_anchor_does_not_destroy_boundary(wf_client, db_session: Session) -> None:
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    anchor = _email(db_session, "anchor", created_at=t0)
    wf_client.put("/inbox/review-marker", json={"after_object_id": str(anchor.id)})
    persisted = wf_client.get("/inbox").json()["review_marker"]
    tombstone_object(anchor)
    db_session.flush()
    after = wf_client.get("/inbox").json()["review_marker"]
    assert after["anchor_object_id"] == persisted["anchor_object_id"]
    assert after["anchor_feed_at"] == persisted["anchor_feed_at"]
    row = db_session.get(InboxReviewMarker, BOOTSTRAP_USER_ID)
    assert row is not None
    assert row.anchor_object_id == anchor.id


def test_marker_cross_session_and_clear(wf_client, db_session: Session) -> None:
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    obj = _email(db_session, "keep", created_at=t0)
    wf_client.put("/inbox/review-marker", json={"after_object_id": str(obj.id)})
    other = InboxReviewMarkerService(db_session, BOOTSTRAP_USER_ID).get_marker()
    assert other is not None
    assert other.anchor_object_id == obj.id
    cleared = wf_client.delete("/inbox/review-marker")
    assert cleared.status_code == 200
    assert cleared.json() == {"cleared": True}
    assert wf_client.get("/inbox").json()["review_marker"] is None


def test_ineligible_owned_object_rejected(wf_client, db_session: Session) -> None:
    task = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="task", title="Not in inbox", origin="user")
    )
    db_session.flush()
    response = wf_client.put("/inbox/review-marker", json={"after_object_id": str(task.id)})
    assert response.status_code == 422


def test_bookmark_create_recolor_delete(wf_client, db_session: Session) -> None:
    note = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="note", title="Tab me", origin="user")
    )
    db_session.flush()
    created = wf_client.put(f"/object-bookmarks/{note.id}", json={"color": "red"})
    assert created.status_code == 200
    assert created.json()["color"] == "red"
    recolor = wf_client.put(f"/object-bookmarks/{note.id}", json={"color": "blue"})
    assert recolor.status_code == 200
    assert recolor.json()["color"] == "blue"
    count = db_session.scalar(select(func.count()).select_from(ObjectBookmark))
    assert int(count or 0) == 1
    deleted = wf_client.delete(f"/object-bookmarks/{note.id}")
    assert deleted.status_code == 200
    assert deleted.json()["changed"] is True


def test_bookmark_invalid_color_and_kinds(wf_client, db_session: Session) -> None:
    event = _email(db_session, "event-like", created_at=datetime(2026, 9, 1, tzinfo=UTC))
    event.kind = "event"
    db_session.flush()
    bad = wf_client.put(f"/object-bookmarks/{event.id}", json={"color": "magenta"})
    assert bad.status_code == 422
    ok = wf_client.put(f"/object-bookmarks/{event.id}", json={"color": "violet"})
    assert ok.status_code == 200


def test_bookmark_isolation_and_batch_leaks_nothing(wf_client, db_session: Session) -> None:
    other = uuid.uuid4()
    db_session.add(User(id=other, display_name="foreign-bookmark"))
    db_session.flush()
    mine = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="note", title="Mine", origin="user")
    )
    foreign = GraphService(db_session, other).create_object(
        ObjectCreate(kind="note", title="Secret", origin="user")
    )
    ObjectBookmarkService(db_session, other).upsert(foreign.id, "red")
    wf_client.put(f"/object-bookmarks/{mine.id}", json={"color": "green"})
    db_session.flush()
    missing = uuid.uuid4()
    batch = wf_client.post(
        "/object-bookmarks/by-objects",
        json={"object_ids": [str(mine.id), str(foreign.id), str(missing), str(mine.id)]},
    )
    assert batch.status_code == 200
    objects = batch.json()["objects"]
    assert list(objects.keys()) == [str(mine.id)]
    assert objects[str(mine.id)]["color"] == "green"
    assert wf_client.put(f"/object-bookmarks/{foreign.id}", json={"color": "gray"}).status_code == 404
    assert wf_client.delete(f"/object-bookmarks/{foreign.id}").status_code == 404


def test_bookmark_batch_max_and_empty(wf_client) -> None:
    assert wf_client.post("/object-bookmarks/by-objects", json={"object_ids": []}).json() == {
        "objects": {}
    }
    ids = [str(uuid.uuid4()) for _ in range(BOOKMARKS_BY_OBJECTS_MAX)]
    assert wf_client.post("/object-bookmarks/by-objects", json={"object_ids": ids}).status_code == 200
    too_many = ids + [str(uuid.uuid4())]
    assert (
        wf_client.post("/object-bookmarks/by-objects", json={"object_ids": too_many}).status_code
        == 422
    )


def test_bookmark_object_deletion_cleanup(wf_client, db_session: Session) -> None:
    note = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="web_page", title="Gone", origin="user")
    )
    db_session.flush()
    wf_client.put(f"/object-bookmarks/{note.id}", json={"color": "orange"})
    ObjectDeletionService(db_session, BOOTSTRAP_USER_ID).delete_object(note.id)
    db_session.flush()
    remaining = db_session.scalar(
        select(func.count()).select_from(ObjectBookmark).where(ObjectBookmark.object_id == note.id)
    )
    assert int(remaining or 0) == 0
    batch = wf_client.post("/object-bookmarks/by-objects", json={"object_ids": [str(note.id)]})
    assert batch.json() == {"objects": {}}


def test_bookmark_batch_single_query(db_session: Session) -> None:
    notes = [
        GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
            ObjectCreate(kind="note", title=f"N{i}", origin="user")
        )
        for i in range(3)
    ]
    svc = ObjectBookmarkService(db_session, BOOTSTRAP_USER_ID)
    svc.upsert(notes[0].id, "red")
    svc.upsert(notes[1].id, "blue")
    db_session.flush()
    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", _capture)
    try:
        grouped = svc.list_by_objects([note.id for note in notes])
    finally:
        event.remove(bind, "before_cursor_execute", _capture)
    assert grouped[notes[0].id].color == "red"
    assert notes[2].id not in grouped
    select_count = sum(1 for stmt in statements if stmt.strip().lower().startswith("select"))
    assert select_count == 1
