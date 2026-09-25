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
from app.domain.task_relations import (
    DEPENDS_ON,
    INVOLVES,
    MAX_PROFILE_ITEMS,
    REFERENCES,
    REQUESTED_BY,
)
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
from app.services.task_relation_service import TaskRelationService
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


def _active_edges(db_session, source_id, target_id, edge_type) -> list[Edge]:
    return list(
        db_session.scalars(
            select(Edge).where(
                Edge.source_id == source_id,
                Edge.target_id == target_id,
                Edge.type == edge_type,
                Edge.state != REJECTED_STATE,
            )
        )
    )


def test_user_confirmation_supersedes_proposed_relations(task_client, db_session) -> None:
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    task = _task(db_session, "Confirm me")
    person = _person(db_session, "Olga")
    dependency = _task(db_session, "Blocked by")
    evidence = _graph(db_session).create_object(
        ObjectCreate(kind="email", title="Why", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    proposed_actor, created = relations.add_actor(
        task.id, person.id, REQUESTED_BY, origin=AGENT_ORIGIN, state=PROPOSED_STATE, confidence=0.6
    )
    assert created is True
    proposed_dependency, _ = relations.add_dependency(
        task.id, dependency.id, origin=AGENT_ORIGIN, state=PROPOSED_STATE, confidence=0.6
    )
    proposed_evidence, _ = relations.attach_evidence(
        task.id, evidence.id, origin=AGENT_ORIGIN, state=PROPOSED_STATE, confidence=0.6
    )
    profile = task_client.get(f"/tasks/{task.id}/profile").json()
    assert profile["requested_by"][0]["edge_state"] == PROPOSED_STATE
    assert profile["requested_by"][0]["edge_origin"] == AGENT_ORIGIN
    assert profile["depends_on"][0]["edge_state"] == PROPOSED_STATE
    assert profile["evidence"][0]["edge_origin"] == AGENT_ORIGIN

    actor = task_client.post(
        f"/tasks/{task.id}/actors",
        json={"person_id": str(person.id), "role": "requested_by"},
    )
    dependency_write = task_client.post(
        f"/tasks/{task.id}/dependencies",
        json={"depends_on_task_id": str(dependency.id)},
    )
    evidence_write = task_client.post(
        f"/tasks/{task.id}/evidence",
        json={"object_id": str(evidence.id)},
    )
    assert actor.status_code == 200
    assert dependency_write.status_code == 200
    assert evidence_write.status_code == 200
    assert actor.json()["created"] is True
    assert actor.json()["edge"]["origin"] == USER_ORIGIN
    assert actor.json()["edge"]["state"] == CONFIRMED_STATE
    db_session.refresh(proposed_actor)
    db_session.refresh(proposed_dependency)
    db_session.refresh(proposed_evidence)
    assert proposed_actor.state == REJECTED_STATE
    assert proposed_dependency.state == REJECTED_STATE
    assert proposed_evidence.state == REJECTED_STATE
    assert len(_active_edges(db_session, task.id, person.id, REQUESTED_BY)) == 1
    assert len(_active_edges(db_session, task.id, dependency.id, DEPENDS_ON)) == 1
    assert len(_active_edges(db_session, task.id, evidence.id, REFERENCES)) == 1

    repeated = task_client.post(
        f"/tasks/{task.id}/actors",
        json={"person_id": str(person.id), "role": "requested_by"},
    )
    assert repeated.json()["created"] is False
    assert repeated.json()["edge"]["id"] == actor.json()["edge"]["id"]
    confirmed_profile = task_client.get(f"/tasks/{task.id}/profile").json()
    assert confirmed_profile["requested_by"][0]["edge_state"] == CONFIRMED_STATE
    assert confirmed_profile["requested_by"][0]["edge_origin"] == USER_ORIGIN
    assert confirmed_profile["depends_on"][0]["edge_state"] == CONFIRMED_STATE
    assert confirmed_profile["evidence"][0]["edge_state"] == CONFIRMED_STATE
    assert all(item["edge_id"] != str(proposed_actor.id) for item in confirmed_profile["requested_by"])

    later, created_later = relations.add_actor(
        task.id, person.id, REQUESTED_BY, origin=AGENT_ORIGIN, state=PROPOSED_STATE, confidence=0.4
    )
    assert created_later is False
    assert later.state == CONFIRMED_STATE
    assert len(_active_edges(db_session, task.id, person.id, REQUESTED_BY)) == 1

    other = _task(db_session, "Proposal only")
    first, first_created = relations.add_dependency(
        other.id, dependency.id, origin=AGENT_ORIGIN, state=PROPOSED_STATE, confidence=0.5
    )
    second, second_created = relations.add_dependency(
        other.id, dependency.id, origin=AGENT_ORIGIN, state=PROPOSED_STATE, confidence=0.5
    )
    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    proposal_profile = task_client.get(f"/tasks/{other.id}/profile").json()
    assert proposal_profile["depends_on"][0]["edge_state"] == PROPOSED_STATE


def test_profile_read_feeds_same_turn_relation_allowlist(
    db_session, fake_embedding_service, monkeypatch
) -> None:
    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(db_session, name)

    import app.assistant.session as assistant_session_module

    monkeypatch.setattr(assistant_session_module, "SessionLocal", lambda: _TestSession())
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    person = _person(db_session, "Nina")
    dependency = _task(db_session, "Prerequisite")
    task = tools.create_task(
        CreateTaskInput(
            title="Seen through profile",
            confidence=0.7,
            requested_by_person_id=person.id,
            depends_on_task_ids=[dependency.id],
        )
    ).object
    budget = PerTurnToolBudget()
    budget.seed_seen_object_ids([task.id])
    profile_result = budget.run(
        BOOTSTRAP_USER_ID,
        "get_task_profile",
        {"task_id": str(task.id)},
    )
    assert profile_result.success is True
    assert person.id in budget.pending_seen_object_ids
    assert dependency.id in budget.pending_seen_object_ids
    blocked = budget.run(
        BOOTSTRAP_USER_ID,
        "update_task",
        {
            "object_id": str(task.id),
            "waiting_on_person_ids": [str(person.id)],
        },
    )
    assert blocked.success is False
    assert "not exposed" in (blocked.error or "")
    budget.commit_model_visible_outputs()
    allowed = budget.run(
        BOOTSTRAP_USER_ID,
        "update_task",
        {
            "object_id": str(task.id),
            "waiting_on_person_ids": [str(person.id)],
            "depends_on_task_ids": [str(dependency.id)],
        },
    )
    assert allowed.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert "not exposed" not in (allowed.error or "")
    edge_id = profile_result.output["requested_by"][0]["edge_id"]
    hidden_edge = budget.run(BOOTSTRAP_USER_ID, "remove_relation", {"edge_id": str(uuid.uuid4())})
    assert hidden_edge.success is False
    assert "not exposed" in (hidden_edge.error or "")
    visible_edge = budget.run(BOOTSTRAP_USER_ID, "remove_relation", {"edge_id": edge_id})
    assert visible_edge.status == ToolExecutionStatus.APPROVAL_REQUIRED
    invented = budget.run(
        BOOTSTRAP_USER_ID,
        "update_task",
        {
            "object_id": str(task.id),
            "involved_person_ids": [str(uuid.uuid4())],
        },
    )
    assert invented.success is False
    assert "not exposed" in (invented.error or "")


def test_invalid_relation_target_writes_nothing(db_session, fake_embedding_service) -> None:
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    person = _person(db_session, "Petr")
    before_tasks = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.kind == "task")
    )
    before_edges = db_session.scalar(select(func.count()).select_from(Edge))
    with pytest.raises(ToolError):
        tools.create_task(
            CreateTaskInput(
                title="Should not exist",
                confidence=0.4,
                requested_by_person_id=person.id,
                depends_on_task_ids=[uuid.uuid4()],
            )
        )
    after_tasks = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.kind == "task")
    )
    after_edges = db_session.scalar(select(func.count()).select_from(Edge))
    assert before_tasks == after_tasks
    assert before_edges == after_edges

    task = _task(db_session, "Keep existing")
    before_task_edges = db_session.scalar(
        select(func.count()).select_from(Edge).where(Edge.source_id == task.id)
    )
    with pytest.raises(ToolError):
        tools.update_task(
            UpdateTaskInput(
                object_id=task.id,
                delegated_to_person_ids=[person.id],
                depends_on_task_ids=[uuid.uuid4()],
            )
        )
    after_task_edges = db_session.scalar(
        select(func.count()).select_from(Edge).where(Edge.source_id == task.id)
    )
    assert before_task_edges == after_task_edges
