"""PHASE 24 — graph workspace read model tests."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import User
from app.main import app
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE
from tests.conftest import apply_embedding_service_overrides, AuthTestClient, BOOTSTRAP_USER_ID


@pytest.fixture
def graph_user_b_id(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="graph-user-b"))
    db_session.flush()
    return user_id


@pytest.fixture
def graph_client(db_session, fake_embedding_service, auth_headers):
    from app.api.deps import get_db, get_embedding_service

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def _task(graph: GraphService, title: str, status: str | None = "open", due_at=None) -> object:
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin="user",
            state=CONFIRMED_STATE,
            status=status,
            due_at=due_at,
        )
    )


def test_default_overview_returns_active_confirmed_tasks(
    db_session, fake_embedding_service, graph_client
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    active = _task(graph, "ACTIVE-1", status="open")
    _task(graph, "DONE-1", status="done")
    db_session.flush()

    response = graph_client.get("/graph/workspace")
    assert response.status_code == 200
    body = response.json()
    node_ids = {node["id"] for node in body["nodes"]}
    assert str(active.id) in node_ids
    assert "DONE-1" not in {node["title"] for node in body["nodes"]}


def test_deleted_neighbor_excluded_from_overview_expansion(
    db_session, fake_embedding_service, graph_client
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _task(graph, "SEED")
    deleted = graph.create_object(
        ObjectCreate(
            kind="note",
            title="Deleted neighbor",
            origin="user",
            state=CONFIRMED_STATE,
            status="deleted",
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=deleted.id,
            type="references",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    db_session.flush()

    response = graph_client.get("/graph/workspace")
    titles = {node["title"] for node in response.json()["nodes"]}
    assert "SEED" in titles
    assert "Deleted neighbor" not in titles


def test_rooted_workspace_allows_terminal_task(
    db_session, fake_embedding_service, graph_client
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    done = _task(graph, "DONE-ROOT", status="done")
    db_session.flush()

    response = graph_client.get(f"/graph/workspace?root_id={done.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["root_id"] == str(done.id)
    assert any(node["id"] == str(done.id) for node in body["nodes"])


def test_rooted_deleted_task_can_be_inspected(
    db_session, fake_embedding_service, graph_client
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    deleted = _task(graph, "DELETED-ROOT", status="deleted")
    db_session.flush()

    response = graph_client.get(f"/graph/workspace?root_id={deleted.id}")
    assert response.status_code == 200
    assert response.json()["nodes"][0]["status"] == "deleted"


def test_workspace_no_duplicate_ids(
    db_session, fake_embedding_service, graph_client
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    a = _task(graph, "A")
    b = _task(graph, "B")
    graph.create_edge(
        EdgeCreate(
            source_id=a.id,
            target_id=b.id,
            type="related_to",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=b.id,
            target_id=a.id,
            type="depends_on",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    db_session.flush()

    response = graph_client.get(f"/graph/workspace?root_id={a.id}")
    body = response.json()
    node_ids = [node["id"] for node in body["nodes"]]
    edge_ids = [edge["id"] for edge in body["edges"]]
    assert len(node_ids) == len(set(node_ids))
    assert len(edge_ids) == len(set(edge_ids))


def test_workspace_edges_have_endpoints_in_nodes(
    db_session, fake_embedding_service, graph_client
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _task(graph, "EDGE-ENDPOINTS")
    note = graph.create_object(
        ObjectCreate(kind="note", title="Note", origin="user", state=CONFIRMED_STATE)
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=note.id,
            type="references",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    db_session.flush()

    body = graph_client.get(f"/graph/workspace?root_id={task.id}").json()
    node_ids = {node["id"] for node in body["nodes"]}
    for edge in body["edges"]:
        assert edge["source_id"] in node_ids
        assert edge["target_id"] in node_ids


def test_rejected_objects_and_edges_excluded(
    db_session, fake_embedding_service, graph_client
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _task(graph, "REJECT-FILTER")
    rejected = graph.create_object(
        ObjectCreate(
            kind="note",
            title="Rejected note",
            origin="user",
            state=REJECTED_STATE,
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=rejected.id,
            type="references",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    db_session.flush()

    titles = {node["title"] for node in graph_client.get("/graph/workspace").json()["nodes"]}
    assert "Rejected note" not in titles


def test_wrong_user_root_returns_404(
    db_session, fake_embedding_service, auth_headers, graph_user_b_id
):
    foreign_graph = GraphService(db_session, graph_user_b_id, fake_embedding_service)
    task = _task(foreign_graph, "FOREIGN")
    db_session.flush()

    from app.api.deps import get_db, get_embedding_service

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        client = AuthTestClient(test_client, auth_headers)
        response = client.get(f"/graph/workspace?root_id={task.id}")
        assert response.status_code == 404
    app.dependency_overrides.clear()
