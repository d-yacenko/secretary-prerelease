"""Derived Task operational projection. Read-only; proposed edges do not count."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import Object
from app.domain.object_visibility import tombstone_object
from app.domain.task_operational import (
    REASON_NO_EXTERNAL_BLOCKER,
    REASON_OPEN_DEPENDENCY,
    REASON_OVERDUE,
    REASON_TERMINAL_LIFECYCLE,
    OperationalDependency,
    OperationalPerson,
    derive_task_operational_state,
)
from app.domain.task_relations import DEPENDS_ON, MAX_PROFILE_ITEMS, WAITING_ON
from app.main import app
from app.services.domain_tool_service import DomainToolService
from app.services.graph_service import GraphService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import (
    AGENT_ORIGIN,
    CONFIRMED_STATE,
    PROPOSED_STATE,
    REJECTED_STATE,
    USER_ORIGIN,
)
from app.services.task_operational_projection_service import TaskOperationalProjectionService
from app.services.task_relation_service import TaskRelationService
from app.tools.schemas import GetTaskProfileInput
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides

NOW = datetime(2026, 6, 15, 12, tzinfo=UTC)


def _derive(**overrides):
    payload = {
        "status": "open",
        "due_at": None,
        "planned_start_at": None,
        "planned_end_at": None,
        "now": NOW,
        "blocking_dependencies": (),
        "waiting_on": (),
        "delegated_to": (),
    }
    payload.update(overrides)
    return derive_task_operational_state(**payload)


def test_plain_open_task_is_actionable() -> None:
    projection = _derive()
    assert projection.operational_state == "actionable"
    assert projection.reason_codes == (REASON_NO_EXTERNAL_BLOCKER,)
    assert projection.is_overdue is False


def test_terminal_task_is_terminal() -> None:
    projection = _derive(status="done", due_at=NOW - timedelta(days=2))
    assert projection.operational_state == "terminal"
    assert projection.is_overdue is False
    assert REASON_TERMINAL_LIFECYCLE in projection.reason_codes
    assert REASON_OVERDUE not in projection.reason_codes


def test_future_planned_start_is_scheduled_later() -> None:
    start = NOW + timedelta(days=1)
    projection = _derive(planned_start_at=start, planned_end_at=start + timedelta(hours=1))
    assert projection.operational_state == "scheduled_later"
    assert projection.is_scheduled_later is True


def test_precedence_waiting_delegated_blocked_and_overdue() -> None:
    from uuid import uuid4

    olga = uuid4()
    ivan = uuid4()
    blocker = uuid4()
    start = NOW + timedelta(days=1)
    waiting = _derive(
        planned_start_at=start,
        planned_end_at=start + timedelta(hours=1),
        waiting_on=(OperationalPerson(person_id=olga, title="Olga"),),
        delegated_to=(OperationalPerson(person_id=ivan, title="Ivan"),),
    )
    assert waiting.operational_state == "waiting"
    assert waiting.is_scheduled_later is True
    delegated = _derive(delegated_to=(OperationalPerson(person_id=ivan, title="Ivan"),))
    assert delegated.operational_state == "delegated"
    blocked = _derive(
        blocking_dependencies=(
            OperationalDependency(task_id=blocker, title="Open dep", status="open"),
        ),
        waiting_on=(OperationalPerson(person_id=olga, title="Olga"),),
        due_at=NOW - timedelta(hours=1),
    )
    assert blocked.operational_state == "blocked"
    assert blocked.is_overdue is True
    assert blocked.reason_codes == (
        REASON_OPEN_DEPENDENCY,
        "waiting_on_person",
        REASON_OVERDUE,
    )


def test_overdue_coexists_with_waiting_and_skips_terminal() -> None:
    from uuid import uuid4

    overdue_waiting = _derive(
        due_at=NOW - timedelta(days=1),
        waiting_on=(OperationalPerson(person_id=uuid4(), title="Olga"),),
    )
    assert overdue_waiting.operational_state == "waiting"
    assert overdue_waiting.is_overdue is True
    completed = _derive(status="completed", due_at=NOW - timedelta(days=1))
    assert completed.operational_state == "terminal"
    assert completed.is_overdue is False


@pytest.fixture
def task_client(db_session, fake_embedding_service, auth_headers):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


def _graph(db_session) -> GraphService:
    return GraphService(db_session, BOOTSTRAP_USER_ID)


def _task(db_session, title: str, **fields) -> Object:
    return _graph(db_session).create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
            status=fields.pop("status", "open"),
            **fields,
        )
    )


def _person(db_session, title: str) -> Object:
    return PersonIdentityService(db_session, BOOTSTRAP_USER_ID).create_person(title)


def _project(db_session, task: Object):
    return TaskOperationalProjectionService(db_session, BOOTSTRAP_USER_ID).project(task, now=NOW)


def test_confirmed_relations_drive_service_state(db_session) -> None:
    task = _task(db_session, "Need Olga")
    olga = _person(db_session, "Olga")
    ivan = _person(db_session, "Ivan")
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    assert _project(db_session, task).operational_state == "actionable"
    relations.add_actor(task.id, olga.id, WAITING_ON)
    relations.add_actor(task.id, ivan.id, "delegated_to")
    projected = _project(db_session, task)
    assert projected.operational_state == "waiting"
    assert projected.waiting_on[0].title == "Olga"
    assert projected.delegated_to[0].title == "Ivan"


def test_proposed_waiting_does_not_change_actionability(db_session) -> None:
    task = _task(db_session, "Still mine")
    olga = _person(db_session, "Olga")
    _graph(db_session).create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=olga.id,
            type=WAITING_ON,
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.4,
        )
    )
    projected = _project(db_session, task)
    assert projected.operational_state == "actionable"
    assert projected.waiting_on == ()


def test_dependency_lifecycle_and_edge_state(db_session) -> None:
    task = _task(db_session, "Parent")
    open_dep = _task(db_session, "Open dep")
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    relations.add_dependency(task.id, open_dep.id)
    assert _project(db_session, task).operational_state == "blocked"
    open_dep.status = "done"
    db_session.flush()
    assert _project(db_session, task).operational_state == "actionable"
    for status in ("completed", "cancelled", "archived"):
        other = _task(db_session, f"Dep {status}", status=status)
        relations.add_dependency(task.id, other.id)
        assert _project(db_session, task).operational_state == "actionable"
    deleted = _task(db_session, "Deleted dep")
    relations.add_dependency(task.id, deleted.id)
    tombstone_object(deleted)
    db_session.flush()
    assert _project(db_session, task).operational_state == "actionable"
    rejected_target = _task(db_session, "Rejected edge target")
    edge, _created = relations.add_dependency(task.id, rejected_target.id)
    edge.state = REJECTED_STATE
    db_session.flush()
    assert _project(db_session, task).operational_state == "actionable"
    proposed_target = _task(db_session, "Proposed edge target")
    _graph(db_session).create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=proposed_target.id,
            type=DEPENDS_ON,
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.4,
        )
    )
    assert _project(db_session, task).operational_state == "actionable"
    assert not hasattr(Object, "operational_status")


def test_profile_rest_and_assistant_share_projection(task_client, db_session) -> None:
    moment = datetime.now(UTC)
    task = _task(
        db_session,
        "Due parent",
        due_at=moment - timedelta(days=1),
        planned_start_at=moment - timedelta(hours=2),
        planned_end_at=moment + timedelta(hours=2),
    )
    dep = _task(db_session, "Still open")
    TaskRelationService(db_session, BOOTSTRAP_USER_ID).add_dependency(task.id, dep.id)
    response = task_client.get(f"/tasks/{task.id}/profile")
    assert response.status_code == 200
    operational = response.json()["operational"]
    assert operational["operational_state"] == "blocked"
    assert operational["is_overdue"] is True
    assert operational["is_planned_now"] is True
    assert operational["blocking_dependencies"][0]["task_id"] == str(dep.id)
    tool = DomainToolService(db_session, BOOTSTRAP_USER_ID).get_task_profile(
        GetTaskProfileInput(task_id=task.id)
    )
    assert tool.operational.operational_state == "blocked"
    assert tool.operational.is_overdue is True
    assert tool.operational.blocking_dependencies[0].task_id == dep.id


def test_truncated_presentation_does_not_hide_a_blocker(task_client, db_session) -> None:
    task = _task(db_session, "Capped")
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    for index in range(MAX_PROFILE_ITEMS):
        done = _task(db_session, f"a{index:02d}", status="done")
        relations.add_dependency(task.id, done.id)
    hidden_open = _task(db_session, "zzz open")
    relations.add_dependency(task.id, hidden_open.id)
    response = task_client.get(f"/tasks/{task.id}/profile")
    body = response.json()
    assert body["depends_on_truncated"] is True
    assert len(body["depends_on"]) == MAX_PROFILE_ITEMS
    assert all(item["title"].startswith("a") for item in body["depends_on"])
    operational = body["operational"]
    assert operational["operational_state"] == "blocked"
    assert operational["blocking_dependencies"][0]["title"] == "zzz open"


def test_batch_projection_stays_on_requested_tasks(db_session) -> None:
    plain = _task(db_session, "Plain")
    blocked = _task(db_session, "Blocked")
    dep = _task(db_session, "Dep")
    TaskRelationService(db_session, BOOTSTRAP_USER_ID).add_dependency(blocked.id, dep.id)
    _task(db_session, "Unrequested")
    projected = TaskOperationalProjectionService(db_session, BOOTSTRAP_USER_ID).project_many(
        [plain, blocked],
        now=NOW,
    )
    assert set(projected) == {plain.id, blocked.id}
    assert projected[plain.id].operational_state == "actionable"
    assert projected[blocked.id].operational_state == "blocked"
