"""Design Quality Pass B — bounded READ-only labels-by-objects projection."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_embedding_service
from app.api.schemas import ObjectCreate
from app.db.models import Edge, Object, User
from app.domain.labels import LABELS_BY_OBJECTS_MAX
from app.domain.object_visibility import tombstone_object
from app.main import app
from app.services.graph_service import GraphService
from app.services.label_service import LabelService
from app.services.provenance import REJECTED_STATE
from tests.conftest import AuthTestClient, apply_embedding_service_overrides
from tests.test_workflow_intelligence_labels_a import _note, _svc


@pytest.fixture
def labels_client(db_session, auth_headers, fake_embedding_service):
    def override_get_db():
        yield db_session

    apply_embedding_service_overrides(fake_embedding_service)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_embedding_service] = lambda: fake_embedding_service
    with TestClient(app) as raw:
        yield AuthTestClient(raw, auth_headers)
    app.dependency_overrides.clear()


def _count(session: Session) -> tuple[int, int]:
    objects = session.scalar(select(func.count()).select_from(Object)) or 0
    edges = session.scalar(select(func.count()).select_from(Edge)) or 0
    return int(objects), int(edges)


def test_empty_input_returns_empty_map(labels_client, db_session) -> None:
    before = _count(db_session)
    response = labels_client.post("/labels/by-objects", json={"object_ids": []})
    assert response.status_code == 200
    assert response.json() == {"objects": {}}
    assert _count(db_session) == before


def test_dedupes_input_ids(labels_client, db_session) -> None:
    note = _note(db_session, "Note")
    work = _svc(db_session).create_label("Work", description="office").label
    _svc(db_session).assign_label(note.id, work.id)
    db_session.commit()
    response = labels_client.post(
        "/labels/by-objects",
        json={"object_ids": [str(note.id), str(note.id)]},
    )
    assert response.status_code == 200
    body = response.json()["objects"]
    assert list(body.keys()) == [str(note.id)]
    assert [row["title"] for row in body[str(note.id)]] == ["Work"]
    assert body[str(note.id)][0]["description"] == "office"


def test_max_100_accepted(labels_client) -> None:
    ids = [str(uuid.uuid4()) for _ in range(LABELS_BY_OBJECTS_MAX)]
    response = labels_client.post("/labels/by-objects", json={"object_ids": ids})
    assert response.status_code == 200
    assert response.json() == {"objects": {}}


def test_over_100_rejected(labels_client, db_session) -> None:
    before = _count(db_session)
    ids = [str(uuid.uuid4()) for _ in range(LABELS_BY_OBJECTS_MAX + 1)]
    response = labels_client.post("/labels/by-objects", json={"object_ids": ids})
    assert response.status_code == 422
    assert _count(db_session) == before


def test_one_object_multiple_labels_deterministic(labels_client, db_session) -> None:
    note = _note(db_session, "Note")
    svc = _svc(db_session)
    beta = svc.create_label("Beta").label
    alpha = svc.create_label("Alpha").label
    svc.assign_label(note.id, beta.id)
    svc.assign_label(note.id, alpha.id)
    db_session.commit()
    response = labels_client.post("/labels/by-objects", json={"object_ids": [str(note.id)]})
    titles = [row["title"] for row in response.json()["objects"][str(note.id)]]
    assert titles == ["Alpha", "Beta"]


def test_multiple_objects_and_no_labels_omitted(labels_client, db_session) -> None:
    labeled = _note(db_session, "Labeled")
    unlabeled = _note(db_session, "Unlabeled")
    work = _svc(db_session).create_label("Work").label
    _svc(db_session).assign_label(labeled.id, work.id)
    db_session.commit()
    response = labels_client.post(
        "/labels/by-objects",
        json={"object_ids": [str(unlabeled.id), str(labeled.id)]},
    )
    body = response.json()["objects"]
    assert str(unlabeled.id) not in body
    assert [row["title"] for row in body[str(labeled.id)]] == ["Work"]


def test_rejected_assignment_excluded(labels_client, db_session) -> None:
    note = _note(db_session, "Note")
    work = _svc(db_session).create_label("Work").label
    _svc(db_session).assign_label(note.id, work.id)
    _svc(db_session).remove_label(note.id, work.id)
    db_session.commit()
    response = labels_client.post("/labels/by-objects", json={"object_ids": [str(note.id)]})
    assert response.json() == {"objects": {}}


def test_deleted_label_excluded(labels_client, db_session) -> None:
    note = _note(db_session, "Note")
    work = _svc(db_session).create_label("Work").label
    _svc(db_session).assign_label(note.id, work.id)
    _svc(db_session).delete_label(work.id)
    db_session.commit()
    response = labels_client.post("/labels/by-objects", json={"object_ids": [str(note.id)]})
    assert response.json() == {"objects": {}}


def test_deleted_source_object_excluded(labels_client, db_session) -> None:
    note = _note(db_session, "Note")
    work = _svc(db_session).create_label("Work").label
    _svc(db_session).assign_label(note.id, work.id)
    tombstone_object(note)
    db_session.commit()
    response = labels_client.post("/labels/by-objects", json={"object_ids": [str(note.id)]})
    assert response.json() == {"objects": {}}


def test_rejected_source_object_excluded(labels_client, db_session) -> None:
    note = _note(db_session, "Note")
    work = _svc(db_session).create_label("Work").label
    _svc(db_session).assign_label(note.id, work.id)
    note.state = REJECTED_STATE
    db_session.commit()
    response = labels_client.post("/labels/by-objects", json={"object_ids": [str(note.id)]})
    assert response.json() == {"objects": {}}


def test_cross_user_object_ids_leak_nothing(labels_client, db_session) -> None:
    other_user = uuid.uuid4()
    db_session.add(User(id=other_user, display_name="foreign-labels-batch"))
    db_session.flush()
    foreign_note = GraphService(db_session, other_user).create_object(
        ObjectCreate(kind="note", title="Secret", origin="user")
    )
    foreign_label = LabelService(db_session, other_user).create_label("Secret").label
    LabelService(db_session, other_user).assign_label(foreign_note.id, foreign_label.id)
    db_session.commit()
    response = labels_client.post(
        "/labels/by-objects",
        json={"object_ids": [str(foreign_note.id)]},
    )
    assert response.status_code == 200
    assert response.json() == {"objects": {}}


def test_zero_writes_and_single_bounded_query(db_session) -> None:
    notes = [_note(db_session, f"Note {index}") for index in range(3)]
    work = _svc(db_session).create_label("Work").label
    home = _svc(db_session).create_label("Home").label
    _svc(db_session).assign_label(notes[0].id, work.id)
    _svc(db_session).assign_label(notes[0].id, home.id)
    _svc(db_session).assign_label(notes[1].id, work.id)
    db_session.flush()
    before = _count(db_session)
    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", _capture)
    try:
        grouped = _svc(db_session).list_labels_by_objects([note.id for note in notes])
    finally:
        event.remove(bind, "before_cursor_execute", _capture)
    assert {row.title for row in grouped[notes[0].id]} == {"Home", "Work"}
    assert [row.title for row in grouped[notes[1].id]] == ["Work"]
    assert notes[2].id not in grouped
    assert _count(db_session) == before
    assert len(statements) == 1
    sql = statements[0].lower()
    assert "edges.source_id" in sql
    assert "join" in sql
