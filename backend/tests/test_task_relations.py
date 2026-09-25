"""Canonical Task relations and the shared Task Profile."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.assistant.tool_runner import PerTurnToolBudget
from app.db.models import Edge, Object, User
from app.domain.object_visibility import tombstone_object
from app.domain.task_relations import INVOLVES, MAX_PROFILE_ITEMS, REQUESTED_BY
from app.main import app
from app.services.domain_tool_service import DomainToolService
from app.services.graph_service import GraphService
from app.services.person_graph_workspace_service import PersonGraphWorkspaceService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import (
    AGENT_ORIGIN,
    CONFIRMED_STATE,
    PROPOSED_STATE,
    REJECTED_STATE,
    USER_ORIGIN,
)
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import CreateTaskInput, GetTaskProfileInput, ToolError, UpdateTaskInput
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides


@pytest.fixture
def task_client(db_session, fake_embedding_service, auth_headers):
    from app.api.deps import get_db

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def _graph(db_session) -> GraphService:
    return GraphService(db_session, BOOTSTRAP_USER_ID)


def _task(db_session, title: str, status: str = "open") -> Object:
    return _graph(db_session).create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
            status=status,
        )
    )


def _person(db_session, title: str) -> Object:
    return PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(title)


def test_actor_roles_profile_and_removal(task_client, db_session) -> None:
    task = _task(db_session, "Ship the note")
    requester = _person(db_session, "Olga")
    delegate = _person(db_session, "Ivan")
    waiter = _person(db_session, "Nina")
    participant = _person(db_session, "Petr")
    before_status = task.status

    created = task_client.post(
        f"/tasks/{task.id}/actors",
        json={"person_id": str(requester.id), "role": "requested_by"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["created"] is True
    assert body["edge"]["type"] == REQUESTED_BY
    assert body["edge"]["origin"] == USER_ORIGIN
    assert body["edge"]["state"] == CONFIRMED_STATE
    assert body["edge"]["source_id"] == str(task.id)
    assert body["edge"]["target_id"] == str(requester.id)

    again = task_client.post(
        f"/tasks/{task.id}/actors",
        json={"person_id": str(requester.id), "role": "requested_by"},
    )
    assert again.status_code == 200
    assert again.json()["created"] is False
    assert again.json()["edge"]["id"] == body["edge"]["id"]
    assert db_session.scalar(
        select(func.count()).select_from(Edge).where(Edge.type == REQUESTED_BY, Edge.source_id == task.id)
    ) == 1

    for person, role in ((delegate, "delegated_to"), (waiter, "waiting_on"), (participant, "involves")):
        response = task_client.post(
            f"/tasks/{task.id}/actors",
            json={"person_id": str(person.id), "role": role},
        )
        assert response.status_code == 200

    both = task_client.post(
        f"/tasks/{task.id}/actors",
        json={"person_id": str(requester.id), "role": "involves"},
    )
    assert both.status_code == 200

    reversed_role = task_client.post(
        f"/tasks/{requester.id}/actors",
        json={"person_id": str(task.id), "role": "requested_by"},
    )
    assert reversed_role.status_code == 422

    profile = task_client.get(f"/tasks/{task.id}/profile")
    assert profile.status_code == 200
    card = profile.json()
    assert card["status"] == before_status
    assert [item["person_id"] for item in card["requested_by"]] == [str(requester.id)]
    assert [item["person_id"] for item in card["delegated_to"]] == [str(delegate.id)]
    assert [item["person_id"] for item in card["waiting_on"]] == [str(waiter.id)]
    assert {item["person_id"] for item in card["involves"]} == {str(participant.id), str(requester.id)}
    assert card["requested_by"][0]["title"] == "Olga"

    removed = task_client.delete(f"/tasks/{task.id}/actors/{card['waiting_on'][0]['edge_id']}")
    assert removed.status_code == 200
    assert removed.json()["changed"] is True
    assert removed.json()["edge"]["state"] == REJECTED_STATE
    kept = db_session.get(Edge, uuid.UUID(card["waiting_on"][0]["edge_id"]))
    assert kept is not None
    assert kept.state == REJECTED_STATE
    refreshed = task_client.get(f"/tasks/{task.id}/profile").json()
    assert refreshed["waiting_on"] == []
    assert refreshed["status"] == before_status
    db_session.refresh(task)
    assert task.status == before_status


def test_actor_endpoints_fail_closed(task_client, db_session) -> None:
    task = _task(db_session, "Closed")
    outsider = User(id=uuid.uuid4(), display_name="outsider")
    db_session.add(outsider)
    db_session.flush()
    foreign = PersonIdentityService(db_session, outsider.id).create_person("Foreign")
    missing = task_client.post(
        f"/tasks/{task.id}/actors",
        json={"person_id": str(foreign.id), "role": "delegated_to"},
    )
    assert missing.status_code == 404

    rejected = _person(db_session, "Rejected")
    rejected.state = REJECTED_STATE
    deleted = _person(db_session, "Deleted")
    tombstone_object(deleted)
    db_session.flush()
    assert task_client.post(
        f"/tasks/{task.id}/actors",
        json={"person_id": str(rejected.id), "role": "waiting_on"},
    ).status_code == 404
    assert task_client.post(
        f"/tasks/{task.id}/actors",
        json={"person_id": str(deleted.id), "role": "involves"},
    ).status_code == 404


def test_dependencies_evidence_and_legacy_edges(task_client, db_session) -> None:
    task = _task(db_session, "Parent")
    dependency = _task(db_session, "Child")
    dependent = _task(db_session, "Later")
    evidence = _graph(db_session).create_object(
        ObjectCreate(kind="email", title="The mail", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    person = _person(db_session, "Olga")
    graph = _graph(db_session)
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=dependency.id,
            type="depends_on",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=dependent.id,
            target_id=task.id,
            type="depends_on",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=evidence.id,
            type="references",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=person.id,
            type="related_to",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )

    profile = task_client.get(f"/tasks/{task.id}/profile").json()
    assert [item["object_id"] for item in profile["depends_on"]] == [str(dependency.id)]
    assert [item["object_id"] for item in profile["dependent_tasks"]] == [str(dependent.id)]
    assert [item["object_id"] for item in profile["evidence"]] == [str(evidence.id)]
    assert profile["requested_by"] == []
    assert profile["delegated_to"] == []
    assert profile["waiting_on"] == []
    assert profile["involves"] == []

    assert task_client.post(
        f"/tasks/{task.id}/dependencies",
        json={"depends_on_task_id": str(task.id)},
    ).status_code == 422
    note = _graph(db_session).create_object(
        ObjectCreate(kind="note", title="Not a task", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    assert task_client.post(
        f"/tasks/{task.id}/dependencies",
        json={"depends_on_task_id": str(note.id)},
    ).status_code == 422
    assert task_client.post(
        f"/tasks/{task.id}/evidence",
        json={"object_id": str(dependency.id)},
    ).status_code == 422


def test_profile_actor_list_is_bounded(task_client, db_session) -> None:
    task = _task(db_session, "Many")
    for index in range(MAX_PROFILE_ITEMS + 1):
        person = _person(db_session, f"Person {index:02d}")
        response = task_client.post(
            f"/tasks/{task.id}/actors",
            json={"person_id": str(person.id), "role": INVOLVES},
        )
        assert response.status_code == 200
    profile = task_client.get(f"/tasks/{task.id}/profile").json()
    assert len(profile["involves"]) == MAX_PROFILE_ITEMS
    assert profile["involves_truncated"] is True


def test_assistant_profile_and_additive_task_writes(db_session, fake_embedding_service) -> None:
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    person = _person(db_session, "Olga")
    dependency = _task(db_session, "Dependency")
    evidence = _graph(db_session).create_object(
        ObjectCreate(kind="email", title="Mail", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    created = tools.create_task(
        CreateTaskInput(
            title="Ask Olga",
            confidence=0.8,
            requested_by_person_id=person.id,
            delegated_to_person_ids=[person.id],
            depends_on_task_ids=[dependency.id],
            evidence_object_ids=[evidence.id],
        )
    )
    assert created.object.status == "open"
    assert created.object.state == PROPOSED_STATE
    profile = tools.get_task_profile(GetTaskProfileInput(task_id=created.object.id))
    assert [item.person_id for item in profile.requested_by] == [person.id]
    assert [item.person_id for item in profile.delegated_to] == [person.id]
    assert [item.object_id for item in profile.depends_on] == [dependency.id]
    assert [item.object_id for item in profile.evidence] == [evidence.id]
    edge = db_session.scalar(select(Edge).where(Edge.source_id == created.object.id, Edge.type == REQUESTED_BY))
    assert edge is not None
    assert edge.origin == AGENT_ORIGIN
    assert edge.state == PROPOSED_STATE

    updated = tools.update_task(
        UpdateTaskInput(
            object_id=created.object.id,
            waiting_on_person_ids=[person.id],
        )
    )
    assert updated.changed is True
    assert updated.relation_edges_created == 1
    again = tools.get_task_profile(GetTaskProfileInput(task_id=created.object.id))
    assert [item.person_id for item in again.requested_by] == [person.id]
    assert [item.person_id for item in again.delegated_to] == [person.id]
    assert [item.person_id for item in again.waiting_on] == [person.id]

    with pytest.raises(ToolError):
        tools.create_task(
            CreateTaskInput(
                title="Missing",
                confidence=0.4,
                requested_by_person_id=uuid.uuid4(),
            )
        )

    budget = PerTurnToolBudget()
    unseen = budget.run(
        BOOTSTRAP_USER_ID,
        "create_task",
        {
            "title": "Unseen",
            "confidence": 0.4,
            "depends_on_task_ids": [str(dependency.id)],
        },
    )
    assert unseen.success is False
    assert unseen.status == ToolExecutionStatus.TOOL_ERROR


def test_person_graph_shows_task_through_actor_edge(db_session) -> None:
    person = _person(db_session, "Olga")
    task = _task(db_session, "Reply")
    from app.services.task_relation_service import TaskRelationService

    TaskRelationService(db_session, BOOTSTRAP_USER_ID).add_actor(task.id, person.id, REQUESTED_BY)
    workspace = PersonGraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(root_id=person.id)
    assert task.id in {node.id for node in workspace.nodes}
    assert REQUESTED_BY in {edge.type for edge in workspace.edges}
