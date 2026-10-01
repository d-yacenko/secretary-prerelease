"""GR1: human rejection of confirmed agent relations."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import TaskLayoutState, User
from app.main import app
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE
from tests.conftest import BOOTSTRAP_USER_ID, AuthTestClient, apply_embedding_service_overrides


@pytest.fixture
def relation_client(db_session, fake_embedding_service, auth_headers):
    from app.api.deps import get_db

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def _task(graph: GraphService, title: str):
    return graph.create_object(
        ObjectCreate(kind="task", title=title, origin="user", state=CONFIRMED_STATE, status="open")
    )


def _note(graph: GraphService, title: str):
    return graph.create_object(
        ObjectCreate(kind="note", title=title, origin="user", state=CONFIRMED_STATE)
    )


def _agent_edge(graph: GraphService, source, target, edge_type: str, *, state: str = "confirmed"):
    return graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type=edge_type,
            origin="agent",
            state=state,
            confidence=0.9,
        )
    )


def _reject(client, edge_id):
    return client.post(f"/relations/{edge_id}/decision", json={"decision": "reject"})


def test_confirmed_agent_removable_edges_reject_in_place(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    parent = _task(graph, "Parent")
    child = _task(graph, "Child")
    other = _task(graph, "Other")
    related = _agent_edge(graph, parent, other, "related_to")
    directed = _agent_edge(graph, child, parent, "depends_on")
    structural = _agent_edge(graph, child, parent, "part_of")
    db_session.flush()

    for edge in (related, directed, structural):
        response = _reject(relation_client, edge.id)
        assert response.status_code == 200
        body = response.json()["edge"]
        assert body["id"] == str(edge.id)
        assert body["state"] == "rejected"
        assert body["origin"] == "agent"
    assert db_session.get(type(related), related.id).state == "rejected"


def test_confirmed_agent_confirm_rejected_and_foreign_edges_stay_closed(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _task(graph, "Source")
    target = _task(graph, "Target")
    confirmed = _agent_edge(graph, source, target, "references")
    rejected = _agent_edge(graph, source, target, "related_to", state="rejected")
    user_edge = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type="related_to",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    source_edge = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=_note(graph, "Source note").id,
            type="references",
            origin="source",
            state="observed",
        )
    )
    system_edge = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=_note(graph, "System note").id,
            type="references",
            origin="system",
            state=CONFIRMED_STATE,
        )
    )
    protected = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=_note(graph, "Folder").id,
            type="contains",
            origin="agent",
            state=CONFIRMED_STATE,
            confidence=0.9,
        )
    )
    db_session.flush()

    assert relation_client.post(
        f"/relations/{confirmed.id}/decision",
        json={"decision": "confirm"},
    ).status_code == 422
    assert _reject(relation_client, rejected.id).status_code == 422
    assert relation_client.post(
        f"/relations/{rejected.id}/decision",
        json={"decision": "confirm"},
    ).status_code == 422
    assert _reject(relation_client, user_edge.id).status_code == 422
    assert _reject(relation_client, source_edge.id).status_code == 422
    assert _reject(relation_client, system_edge.id).status_code == 422
    assert _reject(relation_client, protected.id).status_code == 422

    other = User(id=uuid.uuid4(), display_name="gr1-other")
    db_session.add(other)
    db_session.flush()
    other_graph = GraphService(db_session, other.id)
    foreign = _agent_edge(
        other_graph,
        _task(other_graph, "Foreign source"),
        _task(other_graph, "Foreign target"),
        "related_to",
    )
    db_session.flush()
    assert _reject(relation_client, foreign.id).status_code == 404


def test_task_map_rejection_invalidates_topology_once(db_session, relation_client):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    left = _task(graph, "Left")
    right = _task(graph, "Right")
    note = _note(graph, "Evidence")
    db_session.add(TaskLayoutState(user_id=BOOTSTRAP_USER_ID, topology_revision=1))
    db_session.flush()
    task_edge = _agent_edge(graph, left, right, "depends_on")
    flow_edge = _agent_edge(graph, left, note, "references")
    db_session.flush()
    state = db_session.get(TaskLayoutState, BOOTSTRAP_USER_ID)
    after_create = state.topology_revision

    assert _reject(relation_client, task_edge.id).status_code == 200
    db_session.refresh(state)
    assert state.topology_revision == after_create + 1

    before_flow = state.topology_revision
    assert _reject(relation_client, flow_edge.id).status_code == 200
    db_session.refresh(state)
    assert state.topology_revision == before_flow
