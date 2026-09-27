"""Deleted Task mutation rejection and soft-delete idempotency."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import Edge, Object, User
from app.domain.object_visibility import tombstone_object
from app.domain.task_lifecycle import TASK_STATUS_DELETED
from app.main import app
from app.services.domain_tool_service import DomainToolService
from app.services.domain_write_mode import DomainWriteMode
from app.services.errors import NotFoundError
from app.services.graph_service import GraphService
from app.services.pipeline_enqueue import enqueue_embed_object
from app.services.provenance import CONFIRMED_STATE
from app.tools.schemas import DeleteTaskInput, SetTaskStatusInput, ToolError, UpdateTaskInput
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


def test_deleted_task_mutation_and_delete_converge(
    db_session, fake_embedding_service, task_client, monkeypatch
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    legacy = _task(graph, "Legacy deleted", status=TASK_STATUS_DELETED)
    tombstoned = _task(graph, "Canonical deleted")
    tombstone_object(tombstoned)
    original_deleted_at = tombstoned.deleted_at
    active = _task(graph, "Active")
    evidence = _task(graph, "Evidence")
    graph.create_edge(
        EdgeCreate(
            source_id=active.id,
            target_id=evidence.id,
            type="references",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    note = graph.create_object(
        ObjectCreate(kind="note", title="Not a task", origin="user", state=CONFIRMED_STATE)
    )
    other_id = uuid.uuid4()
    db_session.add(User(id=other_id, display_name="s1-other"))
    db_session.flush()
    foreign = GraphService(db_session, other_id).create_object(
        ObjectCreate(kind="task", title="Foreign task", origin="user", state=CONFIRMED_STATE)
    )
    done = _task(graph, "Done task", status="done")
    db_session.flush()
    assert legacy.deleted_at is None
    assert original_deleted_at is not None

    tools = DomainToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        fake_embedding_service,
        defer_write_embeddings=True,
        write_mode=DomainWriteMode.APPROVED_CONFIRMED,
    )
    enqueued: list[uuid.UUID] = []
    real_enqueue = enqueue_embed_object

    def spy(session, object_id, user_id):
        enqueued.append(object_id)
        return real_enqueue(session, object_id, user_id)

    monkeypatch.setattr("app.services.pipeline_enqueue.enqueue_embed_object", spy)

    for deleted in (legacy, tombstoned):
        with pytest.raises(ToolError, match="deleted task cannot be modified"):
            tools.update_task(UpdateTaskInput(object_id=deleted.id, title="Nope"))
        with pytest.raises(ToolError, match="deleted task cannot be modified"):
            tools.set_task_status(SetTaskStatusInput(object_id=deleted.id, status="open"))
        patch = task_client.patch(f"/tasks/{deleted.id}", json={"title": "Nope"})
        assert patch.status_code == 422
        assert patch.json()["detail"] == "deleted task cannot be modified"
        status = task_client.post(f"/tasks/{deleted.id}/status", json={"status": "open"})
        assert status.status_code == 422
        assert status.json()["detail"] == "deleted task cannot be modified"
        tool_delete = tools.delete_task(DeleteTaskInput(object_id=deleted.id))
        rest_delete = task_client.delete(f"/tasks/{deleted.id}")
        assert tool_delete.changed is False
        assert rest_delete.status_code == 200
        assert rest_delete.json()["changed"] is False

    db_session.refresh(legacy)
    db_session.refresh(tombstoned)
    assert legacy.deleted_at is None
    assert legacy.status == TASK_STATUS_DELETED
    assert legacy.title == "Legacy deleted"
    assert tombstoned.deleted_at == original_deleted_at
    assert tombstoned.title == "Canonical deleted"
    assert enqueued == []

    first = tools.delete_task(DeleteTaskInput(object_id=active.id))
    assert first.changed is True
    assert first.new_status == TASK_STATUS_DELETED
    db_session.refresh(active)
    assert active.deleted_at is not None
    assert db_session.get(Object, active.id) is not None
    assert (
        db_session.scalar(select(func.count()).select_from(Edge).where(Edge.source_id == active.id))
        == 1
    )
    assert enqueued == [active.id]
    first_deleted_at = active.deleted_at
    repeated = tools.delete_task(DeleteTaskInput(object_id=active.id))
    assert repeated.changed is False
    db_session.refresh(active)
    assert active.deleted_at == first_deleted_at
    assert enqueued == [active.id]

    missing = uuid.uuid4()
    with pytest.raises(ToolError, match="object not found"):
        tools.update_task(UpdateTaskInput(object_id=missing, title="Missing"))
    assert task_client.patch(f"/tasks/{missing}", json={"title": "Missing"}).status_code == 404
    with pytest.raises(ToolError, match="object not found"):
        tools.update_task(UpdateTaskInput(object_id=foreign.id, title="Foreign"))
    assert task_client.patch(f"/tasks/{foreign.id}", json={"title": "Foreign"}).status_code == 404
    with pytest.raises(ToolError, match="operation only supports task objects"):
        tools.update_task(UpdateTaskInput(object_id=note.id, title="Note"))
    assert task_client.patch(f"/tasks/{note.id}", json={"title": "Note"}).status_code == 422
    with pytest.raises(ToolError, match="operation only supports task objects"):
        tools.delete_task(DeleteTaskInput(object_id=note.id))
    assert task_client.delete(f"/tasks/{note.id}").status_code == 422

    with pytest.raises(NotFoundError):
        graph.get_object(legacy.id)
    with pytest.raises(NotFoundError):
        graph.get_object(tombstoned.id)
    assert graph.get_object(done.id).title == "Done task"


def _task(graph: GraphService, title: str, status: str = "open") -> Object:
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin="user",
            state=CONFIRMED_STATE,
            status=status,
        )
    )
