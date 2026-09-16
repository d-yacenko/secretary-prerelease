import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db, get_embedding_service
from app.db.models import Object
from app.main import app


@pytest.fixture
def client(db_session, auth_headers):
    from app.llm.embedding_service import FakeEmbeddingService
    from tests.conftest import apply_embedding_service_overrides, AuthTestClient

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(FakeEmbeddingService())
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def _create_object(client, kind: str, title: str, **extra) -> dict:
    payload = {"kind": kind, "title": title, "origin": "system", **extra}
    response = client.post("/objects", json=payload)
    assert response.status_code == 201
    return response.json()


def test_create_and_get_object(client) -> None:
    created = _create_object(client, "task", "Write spec")
    response = client.get(f"/objects/{created['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["title"] == "Write spec"
    assert body["metadata"] == {}
    assert "occurred_at" in body


def test_object_out_serializes_occurred_at(client, db_session) -> None:
    from datetime import UTC, datetime

    from app.api.schemas import ObjectCreate
    from app.services.graph_service import GraphService
    from app.users.bootstrap import BOOTSTRAP_USER_ID

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    obj = graph.create_object(
        ObjectCreate(kind="email", title="Dated mail", origin="system"),
    )
    occurred = datetime(2026, 8, 30, 15, 43, tzinfo=UTC)
    obj.occurred_at = occurred
    db_session.commit()

    response = client.get(f"/objects/{obj.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["occurred_at"] is not None
    assert "2026-08-30" in body["occurred_at"]


def test_patch_object(client) -> None:
    created = _create_object(client, "project", "Old title")
    response = client.patch(
        f"/objects/{created['id']}",
        json={"title": "New title", "status": "active"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "New title"
    assert body["status"] == "active"


def test_create_edge_and_neighbors(client) -> None:
    task = _create_object(client, "task", "Task A")
    email = _create_object(client, "email", "Email B")

    edge_response = client.post(
        "/edges",
        json={
            "source_id": task["id"],
            "target_id": email["id"],
            "type": "related_to",
            "origin": "system",
            "state": "observed",
        },
    )
    assert edge_response.status_code == 201
    edge = edge_response.json()

    neighbors_response = client.get(f"/objects/{task['id']}/neighbors")
    assert neighbors_response.status_code == 200
    neighbors_body = neighbors_response.json()
    assert neighbors_body["object_id"] == task["id"]
    assert len(neighbors_body["neighbors"]) == 1
    neighbor = neighbors_body["neighbors"][0]
    assert neighbor["direction"] == "outgoing"
    assert neighbor["edge"]["id"] == edge["id"]
    assert neighbor["object"]["id"] == email["id"]
    assert neighbor["edge"]["type"] == "related_to"


def test_context(client) -> None:
    parent = _create_object(client, "task", "Parent")
    child = _create_object(client, "task", "Child")
    client.post(
        "/edges",
        json={
            "source_id": parent["id"],
            "target_id": child["id"],
            "type": "parent_of",
            "origin": "system",
            "state": "observed",
        },
    )

    response = client.get(f"/objects/{parent['id']}/context")
    assert response.status_code == 200
    body = response.json()
    assert body["object"]["id"] == parent["id"]
    assert len(body["edges"]) == 1
    assert body["edges"][0]["type"] == "parent_of"
    neighbor_ids = {item["id"] for item in body["neighbors"]}
    assert neighbor_ids == {child["id"]}


def test_delete_edge(client) -> None:
    task = _create_object(client, "task", "Task")
    email = _create_object(client, "email", "Email")
    edge_response = client.post(
        "/edges",
        json={
            "source_id": task["id"],
            "target_id": email["id"],
            "type": "related_to",
            "origin": "system",
            "state": "observed",
        },
    )
    edge_id = edge_response.json()["id"]

    delete_response = client.delete(f"/edges/{edge_id}")
    assert delete_response.status_code == 204

    missing_response = client.delete(f"/edges/{edge_id}")
    assert missing_response.status_code == 404


def test_safe_object_deletion_tombstones_without_hard_delete(client, db_session) -> None:
    obj = _create_object(client, "note", "Standalone")
    response = client.delete(f"/objects/{obj['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["object_id"] == obj["id"]
    assert body["already_deleted"] is False

    missing_response = client.get(f"/objects/{obj['id']}")
    assert missing_response.status_code == 404

    assert db_session.get(Object, obj["id"]) is not None


def test_delete_object_with_edges_tombstones(client, db_session) -> None:
    task = _create_object(client, "task", "Connected task")
    email = _create_object(client, "email", "Connected email")
    client.post(
        "/edges",
        json={
            "source_id": task["id"],
            "target_id": email["id"],
            "type": "related_to",
            "origin": "system",
            "state": "observed",
        },
    )

    response = client.delete(f"/objects/{task['id']}")
    assert response.status_code == 200
    assert db_session.get(Object, task["id"]).deleted_at is not None


def test_get_missing_object_returns_404(client) -> None:
    missing_id = str(uuid.uuid4())
    response = client.get(f"/objects/{missing_id}")
    assert response.status_code == 404


def test_create_edge_missing_object_returns_404(client) -> None:
    task = _create_object(client, "task", "Only task")
    response = client.post(
        "/edges",
        json={
            "source_id": task["id"],
            "target_id": str(uuid.uuid4()),
            "type": "related_to",
            "origin": "system",
            "state": "observed",
        },
    )
    assert response.status_code == 404


def test_patch_null_title_returns_422(client) -> None:
    created = _create_object(client, "task", "Keep title")
    response = client.patch(f"/objects/{created['id']}", json={"title": None})
    assert response.status_code == 422


def test_patch_null_state_returns_422(client) -> None:
    created = _create_object(client, "task", "Keep state")
    response = client.patch(f"/objects/{created['id']}", json={"state": None})
    assert response.status_code == 422


def test_duplicate_external_object_returns_409(client) -> None:
    _create_object(
        client,
        "email",
        "First",
        provider="gmail",
        external_id="dup-msg-001",
    )
    response = client.post(
        "/objects",
        json={
            "kind": "email",
            "title": "Duplicate",
            "origin": "system",
            "provider": "gmail",
            "external_id": "dup-msg-001",
        },
    )
    assert response.status_code == 409
