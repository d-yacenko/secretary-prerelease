"""PHASE 24 — direct relation API tests."""

import pytest
from fastapi.testclient import TestClient

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import Object, User
from app.main import app
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE
from tests.conftest import apply_embedding_service_overrides, AuthTestClient, BOOTSTRAP_USER_ID


@pytest.fixture
def relation_client(db_session, fake_embedding_service, auth_headers):
    from app.api.deps import get_db, get_embedding_service

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def _object(graph: GraphService, title: str, status: str | None = None):
    return graph.create_object(
        ObjectCreate(
            kind="note",
            title=title,
            origin="user",
            state=CONFIRMED_STATE,
            status=status,
        )
    )


def test_create_relation_user_confirmed(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _object(graph, "Source")
    target = _object(graph, "Target")
    db_session.flush()

    response = relation_client.post(
        "/relations",
        json={
            "source_id": str(source.id),
            "target_id": str(target.id),
            "type": "depends_on",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["edge"]["type"] == "depends_on"
    assert body["edge"]["origin"] == "user"
    assert body["edge"]["state"] == "confirmed"


def test_duplicate_relation_idempotent(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _object(graph, "A")
    target = _object(graph, "B")
    db_session.flush()
    payload = {
        "source_id": str(source.id),
        "target_id": str(target.id),
        "type": "related_to",
    }
    first = relation_client.post("/relations", json=payload)
    second = relation_client.post("/relations", json=payload)
    assert first.json()["created"] is True
    assert second.json()["created"] is False


def test_self_relation_rejected(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    obj = _object(graph, "Self")
    db_session.flush()
    response = relation_client.post(
        "/relations",
        json={
            "source_id": str(obj.id),
            "target_id": str(obj.id),
            "type": "references",
        },
    )
    assert response.status_code == 422


def test_delete_relation_keeps_objects(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _object(graph, "Keep source")
    target = _object(graph, "Keep target")
    edge = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type="references",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    db_session.flush()

    response = relation_client.delete(f"/relations/{edge.id}")
    assert response.status_code == 204
    assert db_session.get(Object, source.id) is not None
    assert db_session.get(Object, target.id) is not None


def test_delete_agent_origin_relation_rejected(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _object(graph, "Agent source")
    target = _object(graph, "Agent target")
    edge = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type="references",
            origin="agent",
            state=CONFIRMED_STATE,
            confidence=0.8,
        )
    )
    db_session.flush()

    response = relation_client.delete(f"/relations/{edge.id}")
    assert response.status_code == 422
    assert db_session.get(Object, source.id) is not None
    assert db_session.get(Object, target.id) is not None


def test_create_related_to_references_depends_on(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    a = _object(graph, "A")
    b = _object(graph, "B")
    db_session.flush()
    for relation_type in ("related_to", "references", "depends_on"):
        response = relation_client.post(
            "/relations",
            json={
                "source_id": str(a.id),
                "target_id": str(b.id),
                "type": relation_type,
            },
        )
        assert response.status_code == 200
        assert response.json()["edge"]["type"] == relation_type


def _proposed_edge(graph: GraphService, source, target, relation_type: str = "related_to"):
    return graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type=relation_type,
            origin="agent",
            state="proposed",
            confidence=0.9,
        )
    )


def test_relation_decision_confirm_api(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _object(graph, "Source")
    target = _object(graph, "Target")
    edge = _proposed_edge(graph, source, target)
    db_session.flush()
    response = relation_client.post(
        f"/relations/{edge.id}/decision",
        json={"decision": "confirm"},
    )
    assert response.status_code == 200
    assert response.json()["edge"]["state"] == "confirmed"


def test_relation_decision_reject_api(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _object(graph, "Source")
    target = _object(graph, "Target")
    edge = _proposed_edge(graph, source, target)
    db_session.flush()
    response = relation_client.post(
        f"/relations/{edge.id}/decision",
        json={"decision": "reject"},
    )
    assert response.status_code == 200
    assert response.json()["edge"]["state"] == "rejected"


def test_relation_decision_wrong_user_404(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    other_user = User(display_name="Other")
    db_session.add(other_user)
    db_session.flush()
    other_graph = GraphService(db_session, other_user.id)
    source = other_graph.create_object(
        ObjectCreate(kind="note", title="Other source", origin="user", state=CONFIRMED_STATE)
    )
    target = other_graph.create_object(
        ObjectCreate(kind="note", title="Other target", origin="user", state=CONFIRMED_STATE)
    )
    edge = _proposed_edge(other_graph, source, target)
    db_session.flush()
    response = relation_client.post(
        f"/relations/{edge.id}/decision",
        json={"decision": "confirm"},
    )
    assert response.status_code == 404


def test_relation_decision_source_observed_rejected(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _object(graph, "Source")
    target = _object(graph, "Target")
    edge = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type="references",
            origin="source",
            state="observed",
        )
    )
    db_session.flush()
    response = relation_client.post(
        f"/relations/{edge.id}/decision",
        json={"decision": "confirm"},
    )
    assert response.status_code == 422


def test_relation_decision_user_confirmed_rejected(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _object(graph, "Source")
    target = _object(graph, "Target")
    edge = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type="related_to",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    db_session.flush()
    response = relation_client.post(
        f"/relations/{edge.id}/decision",
        json={"decision": "confirm"},
    )
    assert response.status_code == 422


def test_relation_decision_already_confirmed_cannot_transition(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _object(graph, "Source")
    target = _object(graph, "Target")
    edge = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type="related_to",
            origin="agent",
            state="confirmed",
            confidence=0.9,
        )
    )
    db_session.flush()
    response = relation_client.post(
        f"/relations/{edge.id}/decision",
        json={"decision": "reject"},
    )
    assert response.status_code == 422


def test_relation_decision_already_rejected_cannot_transition(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _object(graph, "Source")
    target = _object(graph, "Target")
    edge = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type="related_to",
            origin="agent",
            state="rejected",
            confidence=0.9,
        )
    )
    db_session.flush()
    response = relation_client.post(
        f"/relations/{edge.id}/decision",
        json={"decision": "confirm"},
    )
    assert response.status_code == 422


def test_relation_decision_invalid_schema(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _object(graph, "Source")
    target = _object(graph, "Target")
    edge = _proposed_edge(graph, source, target)
    db_session.flush()
    response = relation_client.post(
        f"/relations/{edge.id}/decision",
        json={"decision": "approve"},
    )
    assert response.status_code == 422
