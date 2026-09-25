"""Tests for canonical tool registry, policy, and execution gateway."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.assistant.tool_definitions import TOOL_DEFINITIONS
from app.assistant.tool_runner import PerTurnToolBudget
from app.llm.openai_assistant_provider import OpenAIAssistantProvider
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.policy import PolicyDecision, ToolPermission, evaluate_policy
from app.tools.registry import (
    ASSISTANT_TOOL_DEFINITIONS,
    MCP_TOOL_NAMES,
    TOOL_REGISTRY,
    TOOL_SPECS,
    registered_tool_names,
)
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import ToolError

_EXPECTED_ASSISTANT_TOOL_NAMES = frozenset(
    {
        "retrieve",
        "query_objects",
        "get_object",
        "get_context",
        "list_neighbors",
        "list_notifications",
        "list_labels",
        "list_inbox_since_review_marker",
        "list_conversation_members",
        "resolve_person",
        "find_person_communications",
        "find_person_identity_candidates",
        "confirm_person_identity",
        "reject_person_identity",
        "retract_person_identity_feedback",
        "set_inbox_review_marker",
        "clear_inbox_review_marker",
        "create_label",
        "rename_label",
        "assign_label",
        "remove_label",
        "delete_label",
        "create_task",
        "update_task",
        "set_task_status",
        "delete_task",
        "link_objects",
        "remove_relation",
        "get_today",
        "create_scheduled_activity",
        "create_recurring_scheduled_activity",
        "cancel_scheduled_activity",
        "create_calendar_event",
        "send_email",
        "send_message",
        "edit_message",
        "delete_message",
        "mark_message_read",
    }
)


def test_tool_specs_names_are_unique_before_registry_dict():
    names = [spec.name for spec in TOOL_SPECS]
    assert len(names) == len(set(names))


def test_tool_registry_size_matches_tool_specs():
    assert len(TOOL_SPECS) == len(TOOL_REGISTRY)


def test_registry_tool_names_are_unique():
    names = [spec.name for spec in TOOL_REGISTRY.values()]
    assert len(names) == len(set(names))


def test_registry_covers_executor_dispatch_tools():
    expected = {
        "search_objects",
        "retrieve",
        "query_objects",
        "get_object",
        "get_context",
        "list_neighbors",
        "list_notifications",
        "list_labels",
        "list_inbox_since_review_marker",
        "list_conversation_members",
        "resolve_person",
        "find_person_communications",
        "find_person_identity_candidates",
        "confirm_person_identity",
        "reject_person_identity",
        "retract_person_identity_feedback",
        "set_inbox_review_marker",
        "clear_inbox_review_marker",
        "create_label",
        "rename_label",
        "assign_label",
        "remove_label",
        "delete_label",
        "create_task",
        "update_task",
        "set_task_status",
        "delete_task",
        "link_objects",
        "remove_relation",
        "get_today",
        "create_scheduled_activity",
        "create_recurring_scheduled_activity",
        "cancel_scheduled_activity",
        "create_calendar_event",
        "send_email",
        "send_message",
        "edit_message",
        "delete_message",
        "mark_message_read",
    }
    assert registered_tool_names() == expected


def test_assistant_tool_definitions_derived_from_registry_exposure():
    registry_assistant = {
        name for name, spec in TOOL_REGISTRY.items() if spec.assistant_exposed
    }
    assert registry_assistant == _EXPECTED_ASSISTANT_TOOL_NAMES
    assert {item["name"] for item in ASSISTANT_TOOL_DEFINITIONS} == _EXPECTED_ASSISTANT_TOOL_NAMES
    assert TOOL_DEFINITIONS is ASSISTANT_TOOL_DEFINITIONS
    assert "search_objects" not in registry_assistant
    assert "retrieve" in registry_assistant


def test_openai_provider_uses_registry_assistant_definitions():
    import inspect

    source = inspect.getsource(OpenAIAssistantProvider.run)
    assert "ASSISTANT_TOOL_DEFINITIONS" in source
    assert "tool_definitions is None" in source


def test_mcp_exposed_tools_match_registry():
    assert MCP_TOOL_NAMES == frozenset(
        name for name, spec in TOOL_REGISTRY.items() if spec.mcp_exposed
    )
    assert "search_objects" in MCP_TOOL_NAMES
    assert "retrieve" not in MCP_TOOL_NAMES


def test_permission_classifications():
    read_tools = {
        "retrieve",
        "query_objects",
        "search_objects",
        "get_object",
        "get_context",
        "list_neighbors",
        "list_notifications",
        "list_labels",
        "list_inbox_since_review_marker",
        "list_conversation_members",
        "resolve_person",
        "find_person_communications",
        "find_person_identity_candidates",
        "get_today",
    }
    internal_write = {
        "create_task",
        "update_task",
        "link_objects",
        "create_scheduled_activity",
        "create_recurring_scheduled_activity",
        "cancel_scheduled_activity",
        "create_label",
        "rename_label",
    }
    destructive = {"delete_task", "remove_relation", "delete_label"}
    annotate = {
        "assign_label",
        "remove_label",
        "set_inbox_review_marker",
        "clear_inbox_review_marker",
        "confirm_person_identity",
        "reject_person_identity",
        "retract_person_identity_feedback",
    }
    for name in read_tools:
        assert TOOL_REGISTRY[name].permission == ToolPermission.READ
    for name in internal_write:
        assert TOOL_REGISTRY[name].permission == ToolPermission.INTERNAL_WRITE
    for name in destructive:
        assert TOOL_REGISTRY[name].permission == ToolPermission.DESTRUCTIVE_INTERNAL_WRITE
    for name in annotate:
        assert TOOL_REGISTRY[name].permission == ToolPermission.ANNOTATE
    assert TOOL_REGISTRY["create_calendar_event"].permission == ToolPermission.EXTERNAL_WRITE
    assert TOOL_REGISTRY["create_calendar_event"].assistant_exposed is True
    assert TOOL_REGISTRY["create_calendar_event"].mcp_exposed is True
    assert TOOL_REGISTRY["create_calendar_event"].prepare_method == "prepare_create_calendar_event"
    assert TOOL_REGISTRY["send_email"].permission == ToolPermission.COMMUNICATE
    assert TOOL_REGISTRY["send_email"].assistant_exposed is True
    assert TOOL_REGISTRY["send_email"].mcp_exposed is True
    assert TOOL_REGISTRY["send_email"].prepare_method == "prepare_send_email"
    assert TOOL_REGISTRY["send_message"].permission == ToolPermission.COMMUNICATE
    assert TOOL_REGISTRY["send_message"].assistant_exposed is True
    assert TOOL_REGISTRY["send_message"].mcp_exposed is True
    assert TOOL_REGISTRY["send_message"].prepare_method == "prepare_send_message"
    assert TOOL_REGISTRY["send_message"].execution_input_model is not None


def test_baseline_policy_allows_read_and_internal_write():
    assert evaluate_policy(ToolPermission.READ) == PolicyDecision.ALLOW
    assert evaluate_policy(ToolPermission.INTERNAL_WRITE) == PolicyDecision.ALLOW
    assert evaluate_policy(ToolPermission.EXTERNAL_PROPOSE) == PolicyDecision.ALLOW


def test_baseline_policy_requires_approval_for_external_classes():
    assert evaluate_policy(ToolPermission.EXTERNAL_WRITE) == PolicyDecision.REQUIRE_APPROVAL
    assert evaluate_policy(ToolPermission.COMMUNICATE) == PolicyDecision.REQUIRE_APPROVAL


def test_approved_action_plan_allows_external_write_and_communicate():
    assert (
        evaluate_policy(ToolPermission.EXTERNAL_WRITE, ExecutionContext.APPROVED_ACTION_PLAN)
        == PolicyDecision.ALLOW
    )
    assert (
        evaluate_policy(ToolPermission.COMMUNICATE, ExecutionContext.APPROVED_ACTION_PLAN)
        == PolicyDecision.ALLOW
    )


def test_interactive_and_mcp_external_write_require_approval():
    assert (
        evaluate_policy(ToolPermission.EXTERNAL_WRITE, ExecutionContext.INTERACTIVE_ASSISTANT)
        == PolicyDecision.REQUIRE_APPROVAL
    )
    assert (
        evaluate_policy(ToolPermission.EXTERNAL_WRITE, ExecutionContext.MCP)
        == PolicyDecision.REQUIRE_APPROVAL
    )


def test_gateway_executes_read_tool():
    tools = MagicMock()
    tools.get_today.return_value = MagicMock(model_dump=lambda mode: {"now": "2026-01-01"})
    gateway = ToolExecutionGateway()
    result = gateway.execute(tools, "get_today", {})
    assert result.success is True
    assert result.status == ToolExecutionStatus.SUCCESS
    tools.get_today.assert_called_once()


def test_gateway_executes_internal_write_tool():
    tools = MagicMock()
    output = MagicMock()
    output.model_dump = lambda mode: {"object": {"id": "task-1", "title": "Task"}}
    tools.create_task.return_value = output
    gateway = ToolExecutionGateway()
    result = gateway.execute(
        tools,
        "create_task",
        {
            "title": "Task",
            "confidence": 0.9,
            "evidence_object_ids": [],
        },
    )
    assert result.success is True
    assert result.status == ToolExecutionStatus.SUCCESS
    tools.create_task.assert_called_once()


def test_gateway_require_approval_does_not_call_handler():
    tools = MagicMock()
    gateway = ToolExecutionGateway()
    original = TOOL_REGISTRY["create_task"]

    class _BlockedSpec:
        name = "blocked_write"
        permission = ToolPermission.EXTERNAL_WRITE
        input_model = original.input_model
        service_method = "create_task"

    TOOL_REGISTRY["blocked_write"] = _BlockedSpec()
    try:
        result = gateway.execute(
            tools,
            "blocked_write",
            {
                "title": "Task",
                "confidence": 0.9,
                "evidence_object_ids": [],
            },
        )
    finally:
        del TOOL_REGISTRY["blocked_write"]

    assert result.success is False
    assert result.approval_required is True
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    tools.create_task.assert_not_called()


def test_gateway_policy_deny_does_not_call_handler(monkeypatch):
    tools = MagicMock()
    gateway = ToolExecutionGateway()

    monkeypatch.setattr(
        "app.tools.gateway.evaluate_policy",
        lambda permission, context=None: PolicyDecision.DENY,
    )

    result = gateway.execute(
        tools,
        "create_task",
        {
            "title": "Task",
            "confidence": 0.9,
            "evidence_object_ids": [],
        },
    )

    assert result.success is False
    assert result.policy_denied is True
    assert result.status == ToolExecutionStatus.POLICY_DENIED
    tools.create_task.assert_not_called()


def test_gateway_unknown_tool_is_safe():
    tools = MagicMock()
    gateway = ToolExecutionGateway()
    result = gateway.execute(tools, "not_a_real_tool", {})
    assert result.success is False
    assert result.status == ToolExecutionStatus.UNKNOWN_TOOL
    assert "unknown tool" in (result.error or "")


def test_dispatch_raises_tool_error_for_unknown_tool():
    from app.tools.executor import _dispatch

    tools = MagicMock()
    with pytest.raises(ToolError, match="unknown tool"):
        _dispatch(tools, "missing_tool", {})


def test_per_turn_budget_limit_result_status():
    budget = PerTurnToolBudget(max_calls=0)
    result = budget.run(uuid4(), "get_today", {})
    assert result.success is False
    assert result.status == ToolExecutionStatus.LIMIT_REACHED


def test_per_turn_budget_invalid_evidence_result_status():
    budget = PerTurnToolBudget()
    result = budget.run(
        uuid4(),
        "create_task",
        {
            "title": "Task",
            "confidence": 0.9,
            "evidence_object_ids": ["not-a-uuid"],
        },
    )
    assert result.success is False
    assert result.status == ToolExecutionStatus.TOOL_ERROR


def test_per_turn_budget_unseen_evidence_result_status():
    budget = PerTurnToolBudget()
    unseen_id = uuid4()
    result = budget.run(
        uuid4(),
        "create_task",
        {
            "title": "Task",
            "confidence": 0.9,
            "evidence_object_ids": [str(unseen_id)],
        },
    )
    assert result.success is False
    assert result.status == ToolExecutionStatus.TOOL_ERROR


def test_per_turn_budget_success_preserves_gateway_status(monkeypatch):
    from app.tools.results import ToolExecutionResult

    gateway_result = ToolExecutionResult(
        success=True,
        tool_name="get_today",
        output={"now": "2026-01-01"},
        status=ToolExecutionStatus.SUCCESS,
        raw_output=MagicMock(),
    )
    monkeypatch.setattr(
        "app.assistant.session.run_assistant_tool",
        lambda *_: gateway_result,
    )
    budget = PerTurnToolBudget()
    result = budget.run(uuid4(), "get_today", {})
    assert result.success is True
    assert result.status == ToolExecutionStatus.SUCCESS
    assert result.model_output_json is not None


def test_validate_update_task_title_only_excludes_unset_fields():
    from app.tools.registry import get_tool_spec, validate_tool_arguments

    spec = get_tool_spec("update_task")
    assert spec is not None
    task_id = uuid4()
    validated = validate_tool_arguments(
        spec,
        {"object_id": str(task_id), "title": "New title"},
    )
    assert validated == {"object_id": str(task_id), "title": "New title"}
    assert "body" not in validated
    assert "due_at" not in validated
    assert "evidence_object_ids" not in validated


def test_validate_update_task_explicit_null_body():
    from app.tools.registry import get_tool_spec, validate_tool_arguments

    spec = get_tool_spec("update_task")
    task_id = uuid4()
    validated = validate_tool_arguments(
        spec,
        {"object_id": str(task_id), "body": None},
    )
    assert validated == {"object_id": str(task_id), "body": None}
    assert "title" not in validated
    assert "due_at" not in validated


def test_validate_update_task_explicit_null_due_at():
    from app.tools.registry import get_tool_spec, validate_tool_arguments

    spec = get_tool_spec("update_task")
    task_id = uuid4()
    validated = validate_tool_arguments(
        spec,
        {"object_id": str(task_id), "due_at": None},
    )
    assert validated == {"object_id": str(task_id), "due_at": None}
    assert "title" not in validated
    assert "body" not in validated


def test_gateway_rejects_null_title_before_approval():
    tools = MagicMock()
    gateway = ToolExecutionGateway()
    task_id = uuid4()
    result = gateway.execute(
        tools,
        "update_task",
        {"object_id": str(task_id), "title": None},
    )
    assert result.success is False
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    tools.update_task.assert_not_called()


def test_gateway_rejects_empty_title_before_approval():
    tools = MagicMock()
    gateway = ToolExecutionGateway()
    task_id = uuid4()
    result = gateway.execute(
        tools,
        "update_task",
        {"object_id": str(task_id), "title": ""},
    )
    assert result.success is False
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    tools.update_task.assert_not_called()


def test_gateway_staged_update_task_preserves_field_presence():
    tools = MagicMock()
    gateway = ToolExecutionGateway()
    task_id = uuid4()
    result = gateway.execute(
        tools,
        "update_task",
        {"object_id": str(task_id), "title": "Renamed"},
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    args = result.staged_action["arguments"]
    assert args == {"object_id": str(task_id), "title": "Renamed"}
    assert "body" not in args
    assert "due_at" not in args
    tools.update_task.assert_not_called()
