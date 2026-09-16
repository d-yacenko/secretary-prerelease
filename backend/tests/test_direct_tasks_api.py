"""PHASE 24 — direct task REST API tests."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import Edge, Object
from app.main import app
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE
from tests.conftest import apply_embedding_service_overrides, AuthTestClient, BOOTSTRAP_USER_ID


@pytest.fixture
def task_client(db_session, fake_embedding_service, auth_headers):
    from app.api.deps import get_db, get_embedding_service

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def _create_task(db_session, title: str = "Original", body: str = "Keep body", status="open"):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            body=body,
            origin="user",
            state=CONFIRMED_STATE,
            status=status,
            due_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        )
    )


def test_patch_task_title_only(db_session, task_client):
    task = _create_task(db_session)
    db_session.flush()

    response = task_client.patch(f"/tasks/{task.id}", json={"title": "Renamed"})
    assert response.status_code == 200
    body = response.json()
    assert body["changed"] is True
    assert body["object"]["title"] == "Renamed"
    assert body["object"]["body"] == "Keep body"


def test_patch_clear_body_explicit_null(db_session, task_client):
    task = _create_task(db_session)
    db_session.flush()

    response = task_client.patch(f"/tasks/{task.id}", json={"body": None})
    assert response.status_code == 200
    assert response.json()["object"]["body"] is None


def test_patch_clear_due_at_explicit_null(db_session, task_client):
    task = _create_task(db_session)
    db_session.flush()

    response = task_client.patch(f"/tasks/{task.id}", json={"due_at": None})
    assert response.status_code == 200
    assert response.json()["object"]["due_at"] is None


def test_patch_empty_body_rejected(db_session, task_client):
    task = _create_task(db_session)
    db_session.flush()
    response = task_client.patch(f"/tasks/{task.id}", json={})
    assert response.status_code == 422


def test_patch_null_title_rejected(db_session, task_client):
    task = _create_task(db_session)
    db_session.flush()
    response = task_client.patch(f"/tasks/{task.id}", json={"title": None})
    assert response.status_code == 422


def test_soft_delete_task_preserves_row_and_edges(db_session, task_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = _create_task(db_session)
    other = graph.create_object(
        ObjectCreate(kind="note", title="Note", origin="user", state=CONFIRMED_STATE)
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=other.id,
            type="references",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    db_session.flush()

    with patch.object(GraphService, "delete_object") as delete_object:
        response = task_client.delete(f"/tasks/{task.id}")
        delete_object.assert_not_called()

    assert response.status_code == 200
    body = response.json()
    assert body["object"]["status"] == "deleted"
    assert body["changed"] is True
    assert db_session.get(Object, task.id) is not None
    edge_count = db_session.scalar(
        select(func.count()).select_from(Edge).where(Edge.source_id == task.id)
    )
    assert edge_count == 1


def test_repeated_soft_delete_idempotent(db_session, task_client):
    task = _create_task(db_session)
    db_session.flush()
    task_client.delete(f"/tasks/{task.id}")
    response = task_client.delete(f"/tasks/{task.id}")
    assert response.status_code == 200
    assert response.json()["changed"] is False


def test_set_task_status_same_is_noop(db_session, task_client):
    task = _create_task(db_session, status="open")
    db_session.flush()
    response = task_client.post(f"/tasks/{task.id}/status", json={"status": "open"})
    assert response.status_code == 200
    assert response.json()["changed"] is False


def test_deleted_task_cannot_be_edited(db_session, task_client):
    task = _create_task(db_session, status="deleted")
    db_session.flush()
    response = task_client.patch(f"/tasks/{task.id}", json={"title": "Nope"})
    assert response.status_code == 422


def test_patch_set_due_date(db_session, task_client):
    task = _create_task(db_session)
    db_session.flush()
    new_due = "2026-10-01T12:00:00+00:00"
    response = task_client.patch(f"/tasks/{task.id}", json={"due_at": new_due})
    assert response.status_code == 200
    returned = response.json()["object"]["due_at"]
    from datetime import datetime

    assert datetime.fromisoformat(returned) == datetime.fromisoformat(new_due)


def test_patch_empty_title_rejected(db_session, task_client):
    task = _create_task(db_session)
    db_session.flush()
    response = task_client.patch(f"/tasks/{task.id}", json={"title": ""})
    assert response.status_code == 422


def test_patch_extra_fields_rejected(db_session, task_client):
    task = _create_task(db_session)
    db_session.flush()
    response = task_client.patch(
        f"/tasks/{task.id}",
        json={"title": "X", "status": "done"},
    )
    assert response.status_code == 422


def test_status_extra_fields_rejected(db_session, task_client):
    task = _create_task(db_session)
    db_session.flush()
    response = task_client.post(
        f"/tasks/{task.id}/status",
        json={"status": "done", "origin": "agent"},
    )
    assert response.status_code == 422


def test_status_open_to_in_progress(db_session, task_client):
    task = _create_task(db_session, status="open")
    db_session.flush()
    response = task_client.post(f"/tasks/{task.id}/status", json={"status": "in_progress"})
    assert response.status_code == 200
    assert response.json()["object"]["status"] == "in_progress"


def test_status_done_to_open(db_session, task_client):
    task = _create_task(db_session, status="done")
    db_session.flush()
    response = task_client.post(f"/tasks/{task.id}/status", json={"status": "open"})
    assert response.status_code == 200
    assert response.json()["object"]["status"] == "open"


def test_deleted_task_cannot_change_status(db_session, task_client):
    task = _create_task(db_session, status="deleted")
    db_session.flush()
    response = task_client.post(f"/tasks/{task.id}/status", json={"status": "open"})
    assert response.status_code == 422
