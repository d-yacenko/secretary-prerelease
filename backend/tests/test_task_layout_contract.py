"""PL1-G2 canonical Task geography contract and topology invalidation."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.schemas import EdgeCreate, ObjectCreate, ObjectUpdate
from app.db.models import TaskLayoutState, User
from app.domain.object_visibility import tombstone_object
from app.main import app
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.provenance import (
    AGENT_ORIGIN,
    CONFIRMED_STATE,
    PROPOSED_STATE,
    REJECTED_STATE,
    USER_ORIGIN,
)
from app.services.task_layout_service import (
    TASK_LAYOUT_TOPOLOGY_EDGE_CAP,
    TASK_LAYOUT_TOPOLOGY_TASK_CAP,
    TaskLayoutCenter,
    TaskLayoutService,
)
from app.services.task_relation_service import TaskRelationService
from tests.conftest import AuthTestClient


@pytest.fixture
def owner(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Layout contract"))
    db_session.flush()
    return user_id


def test_subset_snapshot_is_rejected_and_complete_snapshot_is_usable(db_session, owner) -> None:
    left = _task(db_session, owner, "Left")
    right = _task(db_session, owner, "Right")
    service = TaskLayoutService(db_session, owner)
    with pytest.raises(ValidationError, match="current task set"):
        service.replace_snapshot(
            expected_topology_revision=1,
            algorithm_version="v",
            positions=[TaskLayoutCenter(left.id, 1.0, 1.0)],
        )
    assert db_session.get(TaskLayoutState, owner) is None

    stored = service.replace_snapshot(
        expected_topology_revision=1,
        algorithm_version="v",
        positions=[
            TaskLayoutCenter(left.id, 1.0, 2.0),
            TaskLayoutCenter(right.id, 3.0, 4.0),
        ],
    )
    assert stored.usable is True


def test_new_task_invalidates_existing_layout_and_absence_does_not_seed_state(
    db_session, owner
) -> None:
    first = _task(db_session, owner, "First")
    assert db_session.get(TaskLayoutState, owner) is None
    service = TaskLayoutService(db_session, owner)
    service.replace_snapshot(
        expected_topology_revision=1,
        algorithm_version="v",
        positions=[TaskLayoutCenter(first.id, 5.0, 6.0)],
    )
    second = _task(db_session, owner, "Second")
    current = service.read()
    assert current.topology_revision == 2
    assert current.usable is False
    assert current.positions == (TaskLayoutCenter(first.id, 5.0, 6.0),)
    assert second.id not in {item.task_id for item in current.positions}


def test_hiding_or_rejecting_a_task_keeps_remaining_coverage(db_session, owner) -> None:
    kept = _task(db_session, owner, "Kept")
    hidden = _task(db_session, owner, "Hidden")
    rejected = _task(db_session, owner, "Rejected")
    service = TaskLayoutService(db_session, owner)
    service.replace_snapshot(
        expected_topology_revision=1,
        algorithm_version="v",
        positions=[
            TaskLayoutCenter(kept.id, 1.0, 1.0),
            TaskLayoutCenter(hidden.id, 2.0, 2.0),
            TaskLayoutCenter(rejected.id, 3.0, 3.0),
        ],
    )
    tombstone_object(hidden)
    rejected.state = REJECTED_STATE
    db_session.flush()
    current = service.read()
    assert current.topology_revision == 1
    assert current.usable is True
    assert {item.task_id for item in current.positions} >= {kept.id, hidden.id, rejected.id}
    assert next(item for item in current.positions if item.task_id == kept.id) == TaskLayoutCenter(
        kept.id, 1.0, 1.0
    )


def test_layout_http_contract(db_session, owner, issue_bearer) -> None:
    task = _task(db_session, owner, "Only")
    client = _client(db_session, issue_bearer(owner))
    stale = client.put(
        "/graph/task-layout",
        json={
            "expected_topology_revision": 4,
            "algorithm_version": "v",
            "centers": [{"task_id": str(task.id), "world_x": 1, "world_y": 1}],
        },
    )
    assert stale.status_code == 409
    created = client.put(
        "/graph/task-layout",
        json={
            "expected_topology_revision": 1,
            "algorithm_version": "client",
            "centers": [{"task_id": str(task.id), "world_x": 8.5, "world_y": -1.5}],
        },
    )
    assert created.status_code == 200
    assert created.json()["usable"] is True
    other = _task(db_session, owner, "Other")
    body = client.get("/graph/task-layout")
    assert body.status_code == 200
    payload = body.json()
    assert payload["usable"] is False
    assert payload["topology_revision"] == 2
    assert payload["centers"] == [{"task_id": str(task.id), "world_x": 8.5, "world_y": -1.5}]
    incomplete = client.put(
        "/graph/task-layout",
        json={
            "expected_topology_revision": 2,
            "algorithm_version": "client",
            "centers": [{"task_id": str(task.id), "world_x": 1, "world_y": 1}],
        },
    )
    assert incomplete.status_code == 422
    infinite = client.put(
        "/graph/task-layout",
        json={
            "expected_topology_revision": 2,
            "algorithm_version": "client",
            "centers": [
                {"task_id": str(task.id), "world_x": 1, "world_y": 1},
                {"task_id": str(other.id), "world_x": "NaN", "world_y": 1},
            ],
        },
    )
    assert infinite.status_code == 422
    app.dependency_overrides.clear()


def test_topology_endpoint_returns_only_affecting_task_edges(db_session, owner, issue_bearer) -> None:
    parent = _task(db_session, owner, "Parent")
    child = _task(db_session, owner, "Child")
    graph = GraphService(db_session, owner)
    person = graph.create_object(
        ObjectCreate(kind="person", title="Ada", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    graph.create_edge(
        EdgeCreate(
            source_id=child.id,
            target_id=parent.id,
            type="part_of",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=parent.id,
            target_id=person.id,
            type="requested_by",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    client = _client(db_session, issue_bearer(owner))
    response = client.get("/graph/task-layout/topology")
    assert response.status_code == 200
    body = response.json()
    assert {item["id"] for item in body["tasks"]} == {str(parent.id), str(child.id)}
    assert {edge["type"] for edge in body["edges"]} == {"part_of"}
    assert all(edge["state"] == CONFIRMED_STATE for edge in body["edges"])
    app.dependency_overrides.clear()


def test_topology_cap_fails_closed(db_session, owner, monkeypatch) -> None:
    _task(db_session, owner, "One")
    _task(db_session, owner, "Two")
    monkeypatch.setattr(
        "app.services.task_layout_service.TASK_LAYOUT_TOPOLOGY_TASK_CAP",
        1,
    )
    with pytest.raises(ValidationError, match="task cap"):
        TaskLayoutService(db_session, owner).read_topology()
    assert TASK_LAYOUT_TOPOLOGY_TASK_CAP == 500
    assert TASK_LAYOUT_TOPOLOGY_EDGE_CAP == 2000


def test_affecting_relations_invalidate_once_and_neutral_writes_do_not(db_session, owner) -> None:
    left = _task(db_session, owner, "Left")
    right = _task(db_session, owner, "Right")
    leaf = _task(db_session, owner, "Leaf")
    service = TaskLayoutService(db_session, owner)
    service.replace_snapshot(
        expected_topology_revision=1,
        algorithm_version="v",
        positions=[
            TaskLayoutCenter(left.id, 0.0, 0.0),
            TaskLayoutCenter(right.id, 10.0, 0.0),
            TaskLayoutCenter(leaf.id, 20.0, 0.0),
        ],
    )
    graph = GraphService(db_session, owner)
    related = graph.create_edge(
        EdgeCreate(
            source_id=left.id,
            target_id=right.id,
            type="related_to",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    assert service.read().topology_revision == 2
    graph.delete_edge(related.id)
    assert service.read().topology_revision == 3

    proposed = graph.create_edge(
        EdgeCreate(
            source_id=left.id,
            target_id=right.id,
            type="related_to",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.5,
        )
    )
    assert service.read().topology_revision == 4
    graph.set_edge_state(proposed.id, CONFIRMED_STATE)
    assert service.read().topology_revision == 4
    rejected = graph.create_edge(
        EdgeCreate(
            source_id=right.id,
            target_id=left.id,
            type="depends_on",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.5,
        )
    )
    assert service.read().topology_revision == 5
    graph.set_edge_state(rejected.id, REJECTED_STATE)
    assert service.read().topology_revision == 6

    part = graph.create_edge(
        EdgeCreate(
            source_id=left.id,
            target_id=right.id,
            type="part_of",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.5,
        )
    )
    assert service.read().topology_revision == 6
    graph.set_edge_state(part.id, CONFIRMED_STATE)
    assert service.read().topology_revision == 7
    ignored = graph.create_edge(
        EdgeCreate(
            source_id=leaf.id,
            target_id=left.id,
            type="part_of",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.2,
        )
    )
    before = service.read().topology_revision
    graph.set_edge_state(ignored.id, REJECTED_STATE)
    assert service.read().topology_revision == before

    person = graph.create_object(
        ObjectCreate(kind="person", title="Bea", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    note = graph.create_object(
        ObjectCreate(kind="note", title="Mail", origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )
    relations = TaskRelationService(db_session, owner)
    _edge, created = relations.add_actor(left.id, person.id, "involves")
    assert created is True
    assert service.read().topology_revision == before
    relations.attach_evidence(left.id, note.id)
    graph.update_object(left.id, ObjectUpdate(title="Renamed", status="done"))
    current = service.read()
    assert current.topology_revision == before
    assert {item.task_id for item in current.positions} == {left.id, right.id, leaf.id}


def _task(db_session, user_id: uuid.UUID, title: str):
    return GraphService(db_session, user_id).create_object(
        ObjectCreate(kind="task", title=title, origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )


def _client(db_session, token: str) -> AuthTestClient:
    from app.api.deps import get_db

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    raw = TestClient(app)
    client = AuthTestClient(raw, {"Authorization": f"Bearer {token}"})
    raw.__enter__()
    return client
