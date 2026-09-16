"""PHASE 23E task lifecycle, soft delete, and MCP gateway convergence tests."""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from app.api.schemas import EdgeCreate, ObjectCreate, ObjectUpdate
from app.db.models import Edge, Object, User
from app.domain.task_lifecycle import TASK_STATUS_DELETED, TASK_STATUS_OPEN
from app.mcp.gateway_runner import execute_mcp_tool
from app.services.capture_service import CaptureService
from app.services.domain_tool_service import DomainToolService
from app.services.domain_write_mode import DomainWriteMode
from app.services.graph_service import GraphService
from app.services.today_service import TodayService
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.policy import PolicyDecision, ToolPermission, evaluate_policy
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import (
    CreateTaskInput,
    DeleteTaskInput,
    SetTaskStatusInput,
    ToolError,
    UpdateTaskInput,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _tools(db_session, fake_embedding_service, user_id: uuid.UUID | None = None) -> DomainToolService:
    return DomainToolService(
        db_session,
        user_id or BOOTSTRAP_USER_ID,
        fake_embedding_service,
    )


def _create_confirmed_task(graph: GraphService, title: str, **kwargs) -> Object:
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin="user",
            state="confirmed",
            **kwargs,
        )
    )


def test_capture_task_defaults_to_open(db_session) -> None:
    service = CaptureService(db_session, BOOTSTRAP_USER_ID)
    result = service.capture_task(text="Captured task body")
    task = db_session.get(Object, result.task_id)
    assert task is not None
    assert task.status == TASK_STATUS_OPEN


def test_agent_create_task_defaults_to_open(db_session, fake_embedding_service) -> None:
    tools = _tools(db_session, fake_embedding_service)
    output = tools.create_task(
        CreateTaskInput(title="Agent open task", confidence=0.8)
    )
    assert output.object.status == TASK_STATUS_OPEN


def test_create_task_schema_has_no_status_field() -> None:
    fields = CreateTaskInput.model_fields
    assert "status" not in fields


def test_update_task_rename_and_clear_body(db_session, fake_embedding_service) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _create_confirmed_task(graph, "Old title", body="keep me")
    tools = DomainToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        fake_embedding_service,
        write_mode=DomainWriteMode.APPROVED_CONFIRMED,
    )
    renamed = tools.update_task(
        UpdateTaskInput(object_id=task.id, title="New title")
    )
    assert renamed.changed
    assert renamed.object.title == "New title"

    cleared = tools.update_task(UpdateTaskInput(object_id=task.id, body=None))
    assert cleared.changed
    assert cleared.object.body is None


def test_update_task_clear_due_at(db_session, fake_embedding_service) -> None:
    from datetime import datetime, timezone

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    due = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    task = _create_confirmed_task(graph, "Due task", due_at=due)
    tools = DomainToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        fake_embedding_service,
        write_mode=DomainWriteMode.APPROVED_CONFIRMED,
    )
    cleared = tools.update_task(UpdateTaskInput(object_id=task.id, due_at=None))
    assert cleared.changed
    assert cleared.object.due_at is None


def test_update_task_rejects_null_title(db_session, fake_embedding_service) -> None:
    from pydantic import ValidationError

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _create_confirmed_task(graph, "Title")
    with pytest.raises(ValidationError):
        UpdateTaskInput(object_id=task.id, title=None)


def test_update_task_deleted_task_rejected(db_session, fake_embedding_service) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _create_confirmed_task(graph, "Deleted", status=TASK_STATUS_DELETED)
    tools = DomainToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        fake_embedding_service,
        write_mode=DomainWriteMode.APPROVED_CONFIRMED,
    )
    with pytest.raises(ToolError, match="deleted task cannot be modified"):
        tools.update_task(UpdateTaskInput(object_id=task.id, title="Nope"))


def test_set_task_status_transitions(db_session, fake_embedding_service) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _create_confirmed_task(graph, "Lifecycle")
    tools = DomainToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        fake_embedding_service,
        write_mode=DomainWriteMode.APPROVED_CONFIRMED,
    )
    in_progress = tools.set_task_status(
        SetTaskStatusInput(object_id=task.id, status="in_progress")
    )
    assert in_progress.changed
    assert in_progress.new_status == "in_progress"

    done = tools.set_task_status(SetTaskStatusInput(object_id=task.id, status="done"))
    assert done.new_status == "done"

    reopened = tools.set_task_status(SetTaskStatusInput(object_id=task.id, status="open"))
    assert reopened.new_status == "open"

    archived = tools.set_task_status(
        SetTaskStatusInput(object_id=task.id, status="archived")
    )
    assert archived.new_status == "archived"


def test_set_task_status_idempotent(db_session, fake_embedding_service) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _create_confirmed_task(graph, "Idempotent", status="cancelled")
    tools = DomainToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        fake_embedding_service,
        write_mode=DomainWriteMode.APPROVED_CONFIRMED,
    )
    result = tools.set_task_status(
        SetTaskStatusInput(object_id=task.id, status="cancelled")
    )
    assert result.changed is False


def test_delete_task_soft_delete_preserves_row_and_edges(
    db_session, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    evidence = _create_confirmed_task(graph, "Evidence note")
    task = _create_confirmed_task(graph, "To delete")
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=evidence.id,
            type="references",
            origin="user",
            state="confirmed",
        )
    )
    tools = DomainToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        fake_embedding_service,
        write_mode=DomainWriteMode.APPROVED_CONFIRMED,
    )
    with patch.object(GraphService, "delete_object") as delete_mock:
        result = tools.delete_task(DeleteTaskInput(object_id=task.id))
        delete_mock.assert_not_called()
    assert result.changed
    assert result.new_status == TASK_STATUS_DELETED
    assert db_session.get(Object, task.id) is not None
    edge_count = db_session.scalar(
        select(func.count()).select_from(Edge).where(Edge.source_id == task.id)
    )
    assert edge_count == 1


def test_delete_task_idempotent(db_session, fake_embedding_service) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _create_confirmed_task(graph, "Already deleted", status=TASK_STATUS_DELETED)
    tools = DomainToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        fake_embedding_service,
        write_mode=DomainWriteMode.APPROVED_CONFIRMED,
    )
    result = tools.delete_task(DeleteTaskInput(object_id=task.id))
    assert result.changed is False


def test_destructive_policy_matrix() -> None:
    assert (
        evaluate_policy(
            ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
            ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        == PolicyDecision.REQUIRE_APPROVAL
    )
    assert (
        evaluate_policy(
            ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
            ExecutionContext.MCP,
        )
        == PolicyDecision.REQUIRE_APPROVAL
    )
    assert (
        evaluate_policy(
            ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
            ExecutionContext.BASELINE,
        )
        == PolicyDecision.REQUIRE_APPROVAL
    )
    assert (
        evaluate_policy(
            ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
            ExecutionContext.APPROVED_ACTION_PLAN,
        )
        == PolicyDecision.ALLOW
    )


def test_mcp_mutations_require_approval_no_row_created(
    db_session, fake_embedding_service, patched_mcp_tool_session
) -> None:
    before = db_session.scalar(select(func.count()).select_from(Object))
    gateway = ToolExecutionGateway()
    tools = _tools(db_session, fake_embedding_service)
    result = gateway.execute(
        tools,
        "create_task",
        {"title": "MCP blocked", "confidence": 0.5},
        context=ExecutionContext.MCP,
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    after = db_session.scalar(select(func.count()).select_from(Object))
    assert after == before


def test_mcp_read_via_gateway(db_session, fake_embedding_service, patched_mcp_tool_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _create_confirmed_task(graph, "MCP read task")
    output = execute_mcp_tool("get_object", {"object_id": str(task.id)})
    assert output.object.id == task.id


def test_archived_task_excluded_from_today(db_session, fake_embedding_service) -> None:
    from datetime import datetime, timezone

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    due = datetime(2026, 8, 30, 10, 0, tzinfo=timezone.utc)
    _create_confirmed_task(graph, "Archived today", due_at=due, status="archived")
    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=due)
    titles = [task.title for task in snapshot["tasks"]]
    assert "Archived today" not in titles


def test_legacy_null_status_active_in_today(db_session, fake_embedding_service) -> None:
    from datetime import datetime, timezone

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    due = datetime(2026, 8, 30, 10, 0, tzinfo=timezone.utc)
    _create_confirmed_task(graph, "Legacy null", due_at=due, status=None)
    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(reference_at=due)
    titles = [task.title for task in snapshot["tasks"]]
    assert "Legacy null" in titles
