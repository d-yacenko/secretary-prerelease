"""Canonical part_of: one parent, no cycles, completion compatibility."""

import pytest
from fastapi.testclient import TestClient

from app.api.schemas import EdgeCreate, ObjectCreate, ObjectUpdate
from app.db.models import Edge
from app.domain.task_completion import TASK_COMPLETION_FINITE, TASK_COMPLETION_ONGOING
from app.domain.task_composition import composition_modes_compatible
from app.domain.task_relations import PART_OF, TASK_RELATION_TYPES
from app.main import app
from app.services.domain_tool_service import DomainToolService
from app.services.domain_write_mode import DomainWriteMode
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.provenance import AGENT_ORIGIN, CONFIRMED_STATE, PROPOSED_STATE, USER_ORIGIN
from app.services.relation_decision_service import RelationDecisionService
from app.services.relation_service import RelationService
from app.services.task_operational_projection_service import TaskOperationalProjectionService
from app.services.task_profile_service import TaskProfileService
from app.tools.schemas import LinkObjectsInput, ToolError
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides


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


def test_part_of_is_canonical_vocabulary() -> None:
    assert PART_OF == "part_of"
    assert PART_OF in TASK_RELATION_TYPES
    assert composition_modes_compatible(TASK_COMPLETION_FINITE, TASK_COMPLETION_FINITE)
    assert composition_modes_compatible(TASK_COMPLETION_FINITE, TASK_COMPLETION_ONGOING)
    assert composition_modes_compatible(TASK_COMPLETION_ONGOING, TASK_COMPLETION_ONGOING)
    assert not composition_modes_compatible(TASK_COMPLETION_ONGOING, TASK_COMPLETION_FINITE)


def test_part_of_completion_matrix(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    finite_child = _task(graph, "Finite child", TASK_COMPLETION_FINITE)
    finite_parent = _task(graph, "Finite parent", TASK_COMPLETION_FINITE)
    ongoing_child = _task(graph, "Ongoing child", TASK_COMPLETION_ONGOING)
    ongoing_parent = _task(graph, "Ongoing parent", TASK_COMPLETION_ONGOING)

    finite_to_finite = _part_of(graph, finite_child, finite_parent)
    finite_to_ongoing = _part_of(graph, _task(graph, "Finite leaf", TASK_COMPLETION_FINITE), ongoing_parent)
    ongoing_to_ongoing = _part_of(graph, ongoing_child, _task(graph, "Ongoing root", TASK_COMPLETION_ONGOING))
    assert finite_to_finite.type == PART_OF
    assert finite_to_ongoing.source_id != finite_to_ongoing.target_id
    assert ongoing_to_ongoing.type == PART_OF

    with pytest.raises(ValidationError, match="ongoing task cannot be part of a finite"):
        _part_of(graph, _task(graph, "Ongoing stray", TASK_COMPLETION_ONGOING), finite_parent)


def test_part_of_rejects_non_task_self_second_parent_and_cycle(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    child = _task(graph, "Child")
    parent = _task(graph, "Parent")
    other = _task(graph, "Other parent")
    note = graph.create_object(
        ObjectCreate(kind="note", title="Note", origin="user", state=CONFIRMED_STATE)
    )
    with pytest.raises(ValidationError, match="both be tasks"):
        _part_of(graph, child, note)
    with pytest.raises(ValidationError, match="cannot be part of itself"):
        _part_of(graph, child, child)

    _part_of(graph, child, parent)
    with pytest.raises(ValidationError, match="already has a composition parent"):
        _part_of(graph, child, other)
    with pytest.raises(ValidationError, match="already has a composition parent"):
        _part_of(graph, child, parent)

    left = _task(graph, "A")
    middle = _task(graph, "B")
    right = _task(graph, "C")
    _part_of(graph, left, middle)
    _part_of(graph, middle, right)
    with pytest.raises(ValidationError, match="cycle"):
        _part_of(graph, right, left)


def test_relation_api_part_of_is_idempotent_and_proposed_occupies_the_slot(
    db_session, relation_client
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    child = _task(graph, "Api child")
    parent = _task(graph, "Api parent")
    other = _task(graph, "Api other")
    db_session.flush()
    payload = {
        "source_id": str(child.id),
        "target_id": str(parent.id),
        "type": "part_of",
    }
    first = relation_client.post("/relations", json=payload)
    second = relation_client.post("/relations", json=payload)
    assert first.status_code == 200
    assert first.json()["created"] is True
    assert first.json()["edge"]["origin"] == USER_ORIGIN
    assert first.json()["edge"]["state"] == CONFIRMED_STATE
    assert second.json()["created"] is False
    assert second.json()["edge"]["id"] == first.json()["edge"]["id"]

    proposed_child = _task(graph, "Proposed child")
    graph.create_edge(
        EdgeCreate(
            source_id=proposed_child.id,
            target_id=parent.id,
            type=PART_OF,
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.7,
        )
    )
    blocked = relation_client.post(
        "/relations",
        json={
            "source_id": str(proposed_child.id),
            "target_id": str(other.id),
            "type": "part_of",
        },
    )
    assert blocked.status_code == 422


def test_confirmation_revalidates_part_of_and_reject_stays_available(
    db_session, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    child = _task(graph, "Confirm child", TASK_COMPLETION_FINITE)
    parent = _task(graph, "Confirm parent", TASK_COMPLETION_FINITE)
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    created = tools.link_objects(
        LinkObjectsInput(
            source_id=child.id,
            target_id=parent.id,
            relation_type=PART_OF,
            confidence=0.8,
        )
    )
    assert created.created is True
    assert created.edge.state == PROPOSED_STATE
    assert created.edge.source_id == child.id
    assert created.edge.target_id == parent.id

    child.completion_mode = TASK_COMPLETION_ONGOING
    db_session.flush()
    decisions = RelationDecisionService(db_session, BOOTSTRAP_USER_ID)
    with pytest.raises(ValidationError, match="ongoing task cannot be part of a finite"):
        decisions.apply_decision(created.edge.id, "confirm")
    stored = db_session.get(Edge, created.edge.id)
    assert stored is not None
    assert stored.state == PROPOSED_STATE

    rejected = decisions.apply_decision(stored.id, "reject")
    assert rejected.state == "rejected"


def test_completion_mode_change_keeps_part_of_compatible(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    finite_child = _task(graph, "Mode child", TASK_COMPLETION_FINITE)
    finite_parent = _task(graph, "Mode parent", TASK_COMPLETION_FINITE)
    _part_of(graph, finite_child, finite_parent)
    with pytest.raises(ValidationError, match="part of a finite task"):
        graph.update_object(finite_child.id, ObjectUpdate(completion_mode=TASK_COMPLETION_ONGOING))

    ongoing_child = _task(graph, "Ongoing member", TASK_COMPLETION_ONGOING)
    ongoing_parent = _task(graph, "Ongoing whole", TASK_COMPLETION_ONGOING)
    _part_of(graph, ongoing_child, ongoing_parent)
    with pytest.raises(ValidationError, match="ongoing task is part of it"):
        graph.update_object(ongoing_parent.id, ObjectUpdate(completion_mode=TASK_COMPLETION_FINITE))

    allowed_child = _task(graph, "Allowed child", TASK_COMPLETION_FINITE)
    allowed_parent = _task(graph, "Allowed parent", TASK_COMPLETION_ONGOING)
    _part_of(graph, allowed_child, allowed_parent)
    updated = graph.update_object(
        allowed_child.id, ObjectUpdate(completion_mode=TASK_COMPLETION_ONGOING)
    )
    assert updated.completion_mode == TASK_COMPLETION_ONGOING


def test_user_relation_service_creates_part_of(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    child = _task(graph, "User child")
    parent = _task(graph, "User parent")
    result = RelationService(db_session, BOOTSTRAP_USER_ID).create_relation(
        child.id, parent.id, PART_OF
    )
    assert result.created is True
    assert result.edge.type == PART_OF
    assert result.edge.origin == USER_ORIGIN
    assert result.edge.state == CONFIRMED_STATE


def test_approved_link_objects_confirms_valid_part_of(db_session, fake_embedding_service) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    child = _task(graph, "Approved child")
    parent = _task(graph, "Approved parent")
    tools = DomainToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        fake_embedding_service,
        write_mode=DomainWriteMode.APPROVED_CONFIRMED,
    )
    created = tools.link_objects(
        LinkObjectsInput(
            source_id=child.id,
            target_id=parent.id,
            relation_type=PART_OF,
            confidence=0.9,
        )
    )
    assert created.edge.state == CONFIRMED_STATE
    with pytest.raises(ToolError, match="composition parent"):
        tools.link_objects(
            LinkObjectsInput(
                source_id=child.id,
                target_id=_task(graph, "Second").id,
                relation_type=PART_OF,
                confidence=0.9,
            )
        )


def test_profile_reports_composition_separately_from_dependency(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    child = _task(graph, "Profile child")
    parent = _task(graph, "Profile parent")
    blocker = _task(graph, "Blocker")
    _part_of(graph, child, parent)
    graph.create_edge(
        EdgeCreate(
            source_id=parent.id,
            target_id=blocker.id,
            type="depends_on",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=parent.id,
            target_id=child.id,
            type="contains",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    profiles = TaskProfileService(db_session, BOOTSTRAP_USER_ID)
    child_profile = profiles.get_profile(child.id)
    parent_profile = profiles.get_profile(parent.id)
    assert child_profile.parent_task is not None
    assert child_profile.parent_task.object_id == parent.id
    assert child_profile.parent_task.title == "Profile parent"
    assert child_profile.child_tasks == []
    assert child_profile.depends_on == []
    assert parent_profile.parent_task is None
    assert [item.object_id for item in parent_profile.child_tasks] == [child.id]
    assert parent_profile.child_tasks_truncated is False
    assert [item.object_id for item in parent_profile.depends_on] == [blocker.id]
    assert parent_profile.dependent_tasks == []

    projection = TaskOperationalProjectionService(db_session, BOOTSTRAP_USER_ID)
    alone = _task(graph, "Alone")
    composed = _task(graph, "Composed")
    member = _task(graph, "Member")
    before = projection.project(composed).operational_state
    _part_of(graph, member, composed)
    after = projection.project(composed)
    assert after.operational_state == before
    assert after.blocking_dependencies == ()
    blocked = projection.project(parent)
    assert len(blocked.blocking_dependencies) == 1
    assert projection.project(alone).operational_state == before


def _task(graph: GraphService, title: str, mode: str = TASK_COMPLETION_FINITE):
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin="user",
            state=CONFIRMED_STATE,
            completion_mode=mode,
        )
    )


def _part_of(graph: GraphService, child, parent):
    return graph.create_edge(
        EdgeCreate(
            source_id=child.id,
            target_id=parent.id,
            type=PART_OF,
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
