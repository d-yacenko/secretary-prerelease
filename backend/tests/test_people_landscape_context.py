"""PL1-C: bounded confirmed part_of Task context for the People workspace."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.schemas import EdgeCreate, ObjectCreate
from app.domain.task_relations import TASK_ACTOR_ROLES
from app.main import app
from app.services.graph_service import GraphService
from app.services.graph_workspace_service import (
    PEOPLE_LANDSCAPE_TASK_CONTEXT_CAP,
    GraphWorkspaceService,
)
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import CONFIRMED_STATE, PROPOSED_STATE, REJECTED_STATE, USER_ORIGIN
from app.services.task_relation_service import TaskRelationService
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides


@pytest.fixture
def people_client(db_session, fake_embedding_service, auth_headers):
    from app.api.deps import get_db

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def _person(db_session, name: str):
    return PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(name)


def _task(graph: GraphService, title: str, status: str | None = "open"):
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
            status=status,
        )
    )


def _part_of(graph: GraphService, child, parent, state: str = CONFIRMED_STATE):
    return graph.create_edge(
        EdgeCreate(
            source_id=child.id,
            target_id=parent.id,
            type="part_of",
            origin=USER_ORIGIN,
            state=state,
        )
    )


def _add_actor(relations: TaskRelationService, task, person_id, role: str):
    return relations.add_actor(task.id, person_id, role)


def _workspace(client, query: str) -> dict:
    response = client.get("/graph/people-workspace", params={"q": query, "seed_limit": 24})
    assert response.status_code == 200, response.text
    return response.json()


def test_context_cap_constant_is_five_hundred():
    assert PEOPLE_LANDSCAPE_TASK_CONTEXT_CAP == 500
    assert set(TASK_ACTOR_ROLES) == {"requested_by", "delegated_to", "waiting_on", "involves"}


def test_no_complete_anchors_returns_empty_complete_context(people_client, db_session):
    _person(db_session, "Landscape-context Empty")
    body = _workspace(people_client, "Landscape-context Empty")
    assert body["landscape_tasks"] == []
    assert body["landscape_task_edges"] == []
    assert body["landscape_task_context_complete"] is True


def test_complete_anchors_expand_to_full_constellations(people_client, db_session, fake_embedding_service):
    ada = _person(db_session, "Landscape-context Ada")
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    parent = _task(graph, "Context parent")
    child = _task(graph, "Context child")
    sibling = _task(graph, "Context sibling")
    done_child = _task(graph, "Context done child", status="done")
    other = _task(graph, "Context other root")
    other_child = _task(graph, "Context other child")
    proposed = _task(graph, "Context proposed child")
    mail = graph.create_object(
        ObjectCreate(kind="email", title="Context mail", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    _part_of(graph, child, parent)
    _part_of(graph, sibling, parent)
    _part_of(graph, done_child, parent)
    _part_of(graph, other_child, other)
    _part_of(graph, proposed, parent, state=PROPOSED_STATE)
    kept_edge = graph.create_edge(
        EdgeCreate(
            source_id=sibling.id,
            target_id=child.id,
            type="depends_on",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    rejected_edge = graph.create_edge(
        EdgeCreate(
            source_id=parent.id,
            target_id=child.id,
            type="depends_on",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    rejected_edge.state = REJECTED_STATE
    db_session.flush()
    graph.create_edge(
        EdgeCreate(
            source_id=parent.id,
            target_id=mail.id,
            type="related_to",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    _add_actor(relations, child, ada.id, "requested_by")
    _add_actor(relations, child, ada.id, "waiting_on")
    _add_actor(relations, other_child, ada.id, "involves")

    body = _workspace(people_client, "Landscape-context Ada")
    tasks = body["landscape_tasks"]
    titles = {item["title"] for item in tasks}
    assert titles == {
        "Context parent",
        "Context child",
        "Context sibling",
        "Context done child",
        "Context other root",
        "Context other child",
    }
    assert {item["kind"] for item in tasks} == {"task"}
    assert [item["id"] for item in tasks] == sorted(item["id"] for item in tasks)
    assert len(tasks) == len({item["id"] for item in tasks})
    edge_ids = [item["id"] for item in body["landscape_task_edges"]]
    assert edge_ids == sorted(edge_ids)
    assert str(kept_edge.id) in edge_ids
    assert str(rejected_edge.id) not in edge_ids
    assert all(item["state"] != "rejected" for item in body["landscape_task_edges"])
    assert {item["type"] for item in body["landscape_task_edges"]} <= {"part_of", "depends_on"}
    assert body["landscape_task_context_complete"] is True


def test_incomplete_anchor_set_contributes_nothing(people_client, db_session, fake_embedding_service):
    partial = _person(db_session, "Landscape-context Partial")
    kept = _person(db_session, "Landscape-context Kept")
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    for index in range(65):
        task = _task(graph, f"Context overflow {index}")
        _add_actor(relations, task, partial.id, "involves")
    kept_task = _task(graph, "Context kept only")
    _add_actor(relations, kept_task, kept.id, "delegated_to")

    body = _workspace(people_client, "Landscape-context")
    people = {item["title"]: item for item in body["people"]}
    assert people["Landscape-context Partial"]["landscape_task_ids_complete"] is False
    assert people["Landscape-context Kept"]["landscape_task_ids_complete"] is True
    assert [item["title"] for item in body["landscape_tasks"]] == ["Context kept only"]
    assert body["landscape_task_context_complete"] is True


def test_unresolved_anchor_fails_closed(db_session):
    tasks, edges, complete = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).landscape_task_context(
        {uuid.uuid4()}
    )
    assert tasks == []
    assert edges == []
    assert complete is False


def test_context_overflow_fails_closed_without_partial_geometry(
    people_client,
    db_session,
    fake_embedding_service,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.graph_workspace_service.PEOPLE_LANDSCAPE_TASK_CONTEXT_CAP",
        1,
    )
    ada = _person(db_session, "Landscape-context Overflow")
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    parent = _task(graph, "Context cap parent")
    child = _task(graph, "Context cap child")
    _part_of(graph, child, parent)
    _add_actor(relations, parent, ada.id, "requested_by")

    body = _workspace(people_client, "Landscape-context Overflow")
    assert body["landscape_tasks"] == []
    assert body["landscape_task_edges"] == []
    assert body["landscape_task_context_complete"] is False
    assert body["people"][0]["landscape_task_ids_complete"] is True
    assert body["people"][0]["landscape_task_ids"] == [str(parent.id)]
