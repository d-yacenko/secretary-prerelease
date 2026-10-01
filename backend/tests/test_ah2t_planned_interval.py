"""AH2-T: model tools write the canonical planned Task execution interval."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from mcp.client import Client
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.schemas import ObjectCreate, TaskPatchRequest
from app.db.models import Edge, Object
from app.mcp import server as mcp_server
from app.mcp.server import create_mcp_server
from app.services.domain_tool_service import DomainToolService
from app.services.graph_service import GraphService
from app.services.provenance import AGENT_ORIGIN, CONFIRMED_STATE, PROPOSED_STATE, USER_ORIGIN
from app.services.task_mutation_service import TaskMutationService
from app.tools.assistant_contracts import ASSISTANT_FUNCTION_SCHEMAS
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.policy import PolicyDecision, ToolPermission, evaluate_policy
from app.tools.registry import TOOL_REGISTRY
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import CreateTaskInput, UpdateTaskInput
from app.users.bootstrap import BOOTSTRAP_USER_ID

START = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
END = datetime(2026, 10, 2, 11, 0, tzinfo=UTC)
LATER_END = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def _counts(db_session) -> tuple[int, int]:
    objects = db_session.scalar(select(func.count()).select_from(Object))
    edges = db_session.scalar(select(func.count()).select_from(Edge))
    return objects, edges


def _user_task(db_session, title: str = "Interval") -> Object:
    return GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
            status="open",
        )
    )


def test_create_and_update_inputs_accept_only_a_whole_interval() -> None:
    CreateTaskInput(title="Open", confidence=0.5)
    created = CreateTaskInput(
        title="Planned",
        confidence=0.5,
        planned_start_at=START,
        planned_end_at=END,
    )
    assert created.planned_start_at == START
    UpdateTaskInput(object_id=uuid.uuid4())
    UpdateTaskInput(
        object_id=uuid.uuid4(),
        planned_start_at=START,
        planned_end_at=END,
    )
    cleared = UpdateTaskInput.model_validate(
        {
            "object_id": str(uuid.uuid4()),
            "planned_start_at": None,
            "planned_end_at": None,
        }
    )
    assert cleared.planned_start_at is None
    assert cleared.planned_end_at is None
    for model, payload in (
        (CreateTaskInput, {"title": "Half", "confidence": 0.5, "planned_start_at": START.isoformat()}),
        (
            CreateTaskInput,
            {
                "title": "Mixed",
                "confidence": 0.5,
                "planned_start_at": None,
                "planned_end_at": END.isoformat(),
            },
        ),
        (
            CreateTaskInput,
            {
                "title": "Equal",
                "confidence": 0.5,
                "planned_start_at": START.isoformat(),
                "planned_end_at": START.isoformat(),
            },
        ),
        (
            CreateTaskInput,
            {
                "title": "Reversed",
                "confidence": 0.5,
                "planned_start_at": END.isoformat(),
                "planned_end_at": START.isoformat(),
            },
        ),
        (UpdateTaskInput, {"object_id": str(uuid.uuid4()), "planned_end_at": END.isoformat()}),
        (
            UpdateTaskInput,
            {
                "object_id": str(uuid.uuid4()),
                "planned_start_at": START.isoformat(),
                "planned_end_at": None,
            },
        ),
        (
            UpdateTaskInput,
            {
                "object_id": str(uuid.uuid4()),
                "planned_start_at": START.isoformat(),
                "planned_end_at": START.isoformat(),
            },
        ),
        (
            UpdateTaskInput,
            {
                "object_id": str(uuid.uuid4()),
                "planned_start_at": END.isoformat(),
                "planned_end_at": START.isoformat(),
            },
        ),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_create_task_persists_a_normalized_interval_and_rejects_a_bad_pair(
    db_session, fake_embedding_service
) -> None:
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    before = _counts(db_session)
    with pytest.raises(ValidationError):
        CreateTaskInput(
            title="Bad",
            confidence=0.4,
            planned_start_at=END,
            planned_end_at=START,
        )
    assert _counts(db_session) == before
    naive_start = datetime(2026, 10, 2, 9, 0)  # noqa: DTZ001
    naive_end = datetime(2026, 10, 2, 11, 0)  # noqa: DTZ001
    created = tools.create_task(
        CreateTaskInput(
            title="Planned work",
            confidence=0.6,
            planned_start_at=naive_start,
            planned_end_at=naive_end,
        )
    )
    assert created.object.origin == AGENT_ORIGIN
    assert created.object.state == PROPOSED_STATE
    assert created.object.status == "open"
    assert created.object.due_at is None
    assert created.object.planned_start_at is not None
    assert created.object.planned_end_at is not None
    assert created.object.planned_start_at.tzinfo is not None
    assert created.object.planned_end_at > created.object.planned_start_at


def test_patch_service_sets_replaces_clears_and_keeps_other_fields(db_session) -> None:
    task = _user_task(db_session, "Keep title")
    service = TaskMutationService(db_session, BOOTSTRAP_USER_ID)
    set_pair = service.patch_task_fields(
        task.id,
        planned_start_at=START,
        planned_end_at=END,
        fields_set={"planned_start_at", "planned_end_at"},
    )
    assert set_pair.changed is True
    assert set_pair.object.planned_start_at == START
    assert set_pair.object.planned_end_at == END
    assert set_pair.object.title == "Keep title"
    assert set_pair.object.due_at is None
    replaced = service.patch_task_fields(
        task.id,
        planned_start_at=START,
        planned_end_at=LATER_END,
        fields_set={"planned_start_at", "planned_end_at"},
    )
    assert replaced.changed is True
    assert replaced.object.planned_end_at == LATER_END
    same = service.patch_task_fields(
        task.id,
        planned_start_at=START,
        planned_end_at=LATER_END,
        fields_set={"planned_start_at", "planned_end_at"},
    )
    assert same.changed is False
    cleared = service.patch_task_fields(
        task.id,
        planned_start_at=None,
        planned_end_at=None,
        fields_set={"planned_start_at", "planned_end_at"},
    )
    assert cleared.changed is True
    assert cleared.object.planned_start_at is None
    assert cleared.object.planned_end_at is None
    empty = service.patch_task_fields(
        task.id,
        planned_start_at=None,
        planned_end_at=None,
        fields_set={"planned_start_at", "planned_end_at"},
    )
    assert empty.changed is False
    with pytest.raises(Exception, match="both be set or both be empty"):
        service.patch_task_fields(
            task.id,
            planned_start_at=START,
            fields_set={"planned_start_at"},
        )
    due = service.patch_task_fields(
        task.id,
        due_at=END + timedelta(days=1),
        fields_set={"due_at"},
    )
    assert due.changed is True
    assert due.object.planned_start_at is None
    assert due.object.due_at is not None


def test_update_task_reports_a_pure_interval_change(db_session, fake_embedding_service) -> None:
    task = _user_task(db_session)
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    updated = tools.update_task(
        UpdateTaskInput(
            object_id=task.id,
            planned_start_at=START,
            planned_end_at=END,
        )
    )
    assert updated.changed is True
    assert updated.evidence_edges_created == 0
    assert updated.relation_edges_created == 0
    assert updated.object.title == task.title
    again = tools.update_task(
        UpdateTaskInput(
            object_id=task.id,
            planned_start_at=START,
            planned_end_at=END,
        )
    )
    assert again.changed is False


def test_task_patch_route_sets_replaces_clears_and_rejects(db_session, auth_client) -> None:
    task = _user_task(db_session, "Route")
    original_body = task.body
    set_pair = auth_client.patch(
        f"/tasks/{task.id}",
        json={
            "planned_start_at": START.isoformat(),
            "planned_end_at": END.isoformat(),
        },
    )
    assert set_pair.status_code == 200
    body = set_pair.json()
    assert body["changed"] is True
    assert body["object"]["title"] == "Route"
    assert body["object"]["body"] == original_body
    assert body["object"]["planned_start_at"] is not None
    replaced = auth_client.patch(
        f"/tasks/{task.id}",
        json={
            "planned_start_at": START.isoformat(),
            "planned_end_at": LATER_END.isoformat(),
        },
    )
    assert replaced.status_code == 200
    assert replaced.json()["changed"] is True
    cleared = auth_client.patch(
        f"/tasks/{task.id}",
        json={"planned_start_at": None, "planned_end_at": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["changed"] is True
    assert cleared.json()["object"]["planned_start_at"] is None
    assert cleared.json()["object"]["title"] == "Route"
    rejected = auth_client.patch(
        f"/tasks/{task.id}",
        json={"planned_start_at": START.isoformat()},
    )
    assert rejected.status_code == 422
    with pytest.raises(ValidationError):
        TaskPatchRequest.model_validate({"planned_end_at": END.isoformat()})


def test_assistant_and_mcp_expose_the_same_interval_fields() -> None:
    for tool_name, null_allowed in (("create_task", False), ("update_task", True)):
        properties = ASSISTANT_FUNCTION_SCHEMAS[tool_name]["parameters"]["properties"]
        assert "planned_start_at" in properties
        assert "planned_end_at" in properties
        assert "plannedStart" not in properties
        assert "planned_interval" not in properties
        for name in ("planned_start_at", "planned_end_at"):
            field_type = properties[name]["type"]
            if null_allowed:
                assert field_type == ["string", "null"]
            else:
                assert field_type == "string"
        text = properties["planned_start_at"]["description"]
        assert "planned execution interval" in text
        assert "due_at" in text
    assert (
        evaluate_policy(ToolPermission.INTERNAL_WRITE, ExecutionContext.MCP)
        == PolicyDecision.REQUIRE_APPROVAL
    )
    assert TOOL_REGISTRY["create_task"].permission == ToolPermission.INTERNAL_WRITE
    assert TOOL_REGISTRY["update_task"].permission == ToolPermission.INTERNAL_WRITE
    assert TOOL_REGISTRY["resolve_person"].mcp_exposed is False


def test_malformed_interval_fails_before_approval_and_a_valid_pair_stages(db_session) -> None:
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID)
    gateway = ToolExecutionGateway()
    before = _counts(db_session)
    rejected = gateway.execute(
        tools,
        "create_task",
        {
            "title": "Half",
            "confidence": 0.5,
            "planned_start_at": START.isoformat(),
        },
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert rejected.status == ToolExecutionStatus.TOOL_ERROR
    assert rejected.approval_required is False
    assert _counts(db_session) == before
    staged = gateway.execute(
        tools,
        "update_task",
        {
            "object_id": str(uuid.uuid4()),
            "planned_start_at": START.isoformat(),
            "planned_end_at": END.isoformat(),
        },
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert staged.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert staged.staged_action["permission"] == "INTERNAL_WRITE"
    assert staged.staged_action["arguments"]["planned_start_at"] is not None
    assert staged.staged_action["arguments"]["planned_end_at"] is not None
    assert _counts(db_session) == before


@pytest.mark.asyncio
async def test_mcp_forwards_planned_interval_arguments(
    db_session, patched_mcp_tool_session, monkeypatch
) -> None:
    forwarded: list[tuple[str, dict]] = []
    real_execute = mcp_server.execute_mcp_tool

    def spy(tool_name: str, arguments: dict):
        forwarded.append((tool_name, dict(arguments)))
        return real_execute(tool_name, arguments)

    monkeypatch.setattr(mcp_server, "execute_mcp_tool", spy)
    async with Client(create_mcp_server()) as client:
        listed = await client.list_tools()
        by_name = {tool.name: tool for tool in listed.tools}
        create_schema = by_name["create_task"].input_schema["properties"]
        update_schema = by_name["update_task"].input_schema["properties"]
        assert "planned_start_at" in create_schema
        assert "planned_end_at" in create_schema
        assert "planned_start_at" in update_schema
        assert "planned_end_at" in update_schema
        await client.call_tool(
            "create_task",
            {
                "title": "MCP interval",
                "confidence": 0.4,
                "planned_start_at": START.isoformat(),
                "planned_end_at": END.isoformat(),
            },
        )
    assert forwarded
    arguments = forwarded[0][1]
    assert arguments["planned_start_at"] is not None
    assert arguments["planned_end_at"] is not None
    assert "plannedStart" not in arguments
