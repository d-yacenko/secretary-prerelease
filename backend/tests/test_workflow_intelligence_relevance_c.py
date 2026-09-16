"""Workflow Intelligence Pass C — ANNOTATE permission class and label relevance contract."""

from __future__ import annotations

import inspect
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.ai_audit.context as ai_audit_context
import app.api.assistant as assistant_api_module
import app.assistant.session as assistant_session_module
import app.services.assistant_service as assistant_service_module
from app.ai_audit.constants import EVENT_TOOL_CALL, WORKLOAD_ASSISTANT_INTERACTIVE
from app.ai_audit.context import ai_trace_session
from app.api.deps import get_db
from app.api.schemas import ObjectCreate
from app.assistant.action_plan_constants import (
    PENDING_ACTION_PLAN_STATUS_EXECUTED,
    PENDING_ACTION_PLAN_STATUS_PENDING,
)
from app.assistant.reference_ids import collect_object_ids_from_bounded_tool
from app.assistant.session import run_assistant_tool
from app.assistant.tool_runner import (
    _MUTATION_TOOLS,
    _READ_TOOLS,
    BoundAssistantToolRunner,
    PerTurnToolBudget,
)
from app.assistant.turn_telemetry import AssistantTurnTelemetry
from app.db.models import (
    AITrace,
    AITraceEvent,
    Edge,
    ExternalActionAttempt,
    Job,
    Object,
    PendingActionPlan,
    User,
)
from app.domain.labels import EDGE_TYPE_LABELED_WITH, KIND_LABEL
from app.jobs.handlers import HANDLERS
from app.llm.assistant_models import AssistantHistoryMessage, AssistantProviderResult
from app.llm.openai_assistant_provider import SYSTEM_INSTRUCTIONS, OpenAIAssistantProvider
from app.main import app
from app.mcp.gateway_runner import execute_mcp_tool
from app.proactive.constants import PROACTIVE_READ_TOOL_NAMES
from app.proactive.tool_runner import ProactiveToolRunner
from app.services.action_plan_service import ActionPlanService, validate_action_plan_actions
from app.services.domain_tool_service import DomainToolService
from app.services.graph_service import GraphService
from app.services.label_service import LabelService
from app.services.proactive_review_service import ProactiveReviewService
from app.services.provenance import AGENT_ORIGIN, CONFIRMED_STATE, REJECTED_STATE
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.policy import PolicyDecision, ToolPermission, evaluate_policy
from app.tools.registry import PROACTIVE_TOOL_DEFINITIONS, TOOL_REGISTRY
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import ToolError
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides

BACKEND_APP = Path(__file__).resolve().parents[1] / "app"

EXPECTED_POLICY_MATRIX: dict[tuple[ToolPermission, ExecutionContext], PolicyDecision] = {
    # APPROVED_ACTION_PLAN
    (ToolPermission.READ, ExecutionContext.APPROVED_ACTION_PLAN): PolicyDecision.ALLOW,
    (ToolPermission.ANNOTATE, ExecutionContext.APPROVED_ACTION_PLAN): PolicyDecision.ALLOW,
    (ToolPermission.INTERNAL_WRITE, ExecutionContext.APPROVED_ACTION_PLAN): PolicyDecision.ALLOW,
    (ToolPermission.DESTRUCTIVE_INTERNAL_WRITE, ExecutionContext.APPROVED_ACTION_PLAN): PolicyDecision.ALLOW,
    (ToolPermission.EXTERNAL_PROPOSE, ExecutionContext.APPROVED_ACTION_PLAN): PolicyDecision.ALLOW,
    (ToolPermission.EXTERNAL_WRITE, ExecutionContext.APPROVED_ACTION_PLAN): PolicyDecision.ALLOW,
    (ToolPermission.COMMUNICATE, ExecutionContext.APPROVED_ACTION_PLAN): PolicyDecision.ALLOW,
    # INTERACTIVE_ASSISTANT
    (ToolPermission.READ, ExecutionContext.INTERACTIVE_ASSISTANT): PolicyDecision.ALLOW,
    (ToolPermission.ANNOTATE, ExecutionContext.INTERACTIVE_ASSISTANT): PolicyDecision.ALLOW,
    (ToolPermission.INTERNAL_WRITE, ExecutionContext.INTERACTIVE_ASSISTANT): PolicyDecision.REQUIRE_APPROVAL,
    (ToolPermission.DESTRUCTIVE_INTERNAL_WRITE, ExecutionContext.INTERACTIVE_ASSISTANT): PolicyDecision.REQUIRE_APPROVAL,
    (ToolPermission.EXTERNAL_PROPOSE, ExecutionContext.INTERACTIVE_ASSISTANT): PolicyDecision.ALLOW,
    (ToolPermission.EXTERNAL_WRITE, ExecutionContext.INTERACTIVE_ASSISTANT): PolicyDecision.REQUIRE_APPROVAL,
    (ToolPermission.COMMUNICATE, ExecutionContext.INTERACTIVE_ASSISTANT): PolicyDecision.REQUIRE_APPROVAL,
    # MCP
    (ToolPermission.READ, ExecutionContext.MCP): PolicyDecision.ALLOW,
    (ToolPermission.ANNOTATE, ExecutionContext.MCP): PolicyDecision.REQUIRE_APPROVAL,
    (ToolPermission.INTERNAL_WRITE, ExecutionContext.MCP): PolicyDecision.REQUIRE_APPROVAL,
    (ToolPermission.DESTRUCTIVE_INTERNAL_WRITE, ExecutionContext.MCP): PolicyDecision.REQUIRE_APPROVAL,
    (ToolPermission.EXTERNAL_PROPOSE, ExecutionContext.MCP): PolicyDecision.ALLOW,
    (ToolPermission.EXTERNAL_WRITE, ExecutionContext.MCP): PolicyDecision.REQUIRE_APPROVAL,
    (ToolPermission.COMMUNICATE, ExecutionContext.MCP): PolicyDecision.REQUIRE_APPROVAL,
    # BASELINE / SYSTEM
    (ToolPermission.READ, ExecutionContext.BASELINE): PolicyDecision.ALLOW,
    (ToolPermission.ANNOTATE, ExecutionContext.BASELINE): PolicyDecision.ALLOW,
    (ToolPermission.INTERNAL_WRITE, ExecutionContext.BASELINE): PolicyDecision.ALLOW,
    (ToolPermission.DESTRUCTIVE_INTERNAL_WRITE, ExecutionContext.BASELINE): PolicyDecision.REQUIRE_APPROVAL,
    (ToolPermission.EXTERNAL_PROPOSE, ExecutionContext.BASELINE): PolicyDecision.ALLOW,
    (ToolPermission.EXTERNAL_WRITE, ExecutionContext.BASELINE): PolicyDecision.REQUIRE_APPROVAL,
    (ToolPermission.COMMUNICATE, ExecutionContext.BASELINE): PolicyDecision.REQUIRE_APPROVAL,
}

EXPECTED_REGISTRY_PERMISSIONS = {
    "retrieve": ToolPermission.READ,
    "query_objects": ToolPermission.READ,
    "search_objects": ToolPermission.READ,
    "get_object": ToolPermission.READ,
    "get_context": ToolPermission.READ,
    "list_neighbors": ToolPermission.READ,
    "list_notifications": ToolPermission.READ,
    "list_labels": ToolPermission.READ,
    "list_inbox_since_review_marker": ToolPermission.READ,
    "list_conversation_members": ToolPermission.READ,
    "get_today": ToolPermission.READ,
    "assign_label": ToolPermission.ANNOTATE,
    "remove_label": ToolPermission.ANNOTATE,
    "set_inbox_review_marker": ToolPermission.ANNOTATE,
    "clear_inbox_review_marker": ToolPermission.ANNOTATE,
    "create_label": ToolPermission.INTERNAL_WRITE,
    "rename_label": ToolPermission.INTERNAL_WRITE,
    "delete_label": ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
    "create_task": ToolPermission.INTERNAL_WRITE,
    "update_task": ToolPermission.INTERNAL_WRITE,
    "set_task_status": ToolPermission.INTERNAL_WRITE,
    "delete_task": ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
    "link_objects": ToolPermission.INTERNAL_WRITE,
    "remove_relation": ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
    "create_scheduled_activity": ToolPermission.INTERNAL_WRITE,
    "create_recurring_scheduled_activity": ToolPermission.INTERNAL_WRITE,
    "cancel_scheduled_activity": ToolPermission.INTERNAL_WRITE,
    "create_calendar_event": ToolPermission.EXTERNAL_WRITE,
    "send_email": ToolPermission.COMMUNICATE,
    "send_message": ToolPermission.COMMUNICATE,
}

HARDCODED_TAXONOMY_PREFIXES = ("Сфера ·", "Проект ·", "Роль ·", "Внимание ·", "Работа ·")


# --------------------------------------------------------------------------- helpers


class _SessionProxy:
    """Route SessionLocal() calls to the test transaction without closing it."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._session, name)


@pytest.fixture
def pass_c_user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="pass-c-user"))
    db_session.flush()
    return user_id


@pytest.fixture
def interactive_session(db_session, fake_embedding_service, monkeypatch):
    """Interactive Assistant tool executions run inside the test transaction."""
    monkeypatch.setattr(assistant_session_module, "SessionLocal", lambda: _SessionProxy(db_session))
    monkeypatch.setattr(assistant_service_module, "SessionLocal", lambda: _SessionProxy(db_session))
    monkeypatch.setattr(ai_audit_context, "SessionLocal", lambda: _SessionProxy(db_session))
    monkeypatch.setattr(
        "app.assistant.session.resolve_embedding_service_for_user",
        lambda session, user_id: fake_embedding_service,
    )
    return db_session


@pytest.fixture
def assistant_client(db_session, fake_embedding_service, pass_c_user, issue_bearer, interactive_session):
    headers = {"Authorization": f"Bearer {issue_bearer(pass_c_user)}"}

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    original_build = assistant_api_module.build_assistant_runtime
    with TestClient(app) as raw:
        yield AuthTestClient(raw, headers)
    app.dependency_overrides.clear()
    assistant_api_module.build_assistant_runtime = original_build


def _install_provider(provider) -> None:
    from app.api.assistant import AssistantRuntime, get_assistant_runtime
    from app.services.effective_user_settings_service import EffectiveUserSettings

    effective = EffectiveUserSettings(
        timezone="Europe/Amsterdam",
        assistant_model="gpt-5.6-luna",
        assistant_reasoning_effort="low",
        assistant_verbosity="low",
        assistant_max_rounds=6,
        assistant_max_rounds_override=None,
        openai_api_key=None,
        openai_key_configured=False,
        allowed_assistant_models=["gpt-5.6-luna"],
    )
    runtime = AssistantRuntime(provider=provider, effective=effective)
    app.dependency_overrides[get_assistant_runtime] = lambda: runtime
    assistant_api_module.build_assistant_runtime = lambda session, user_id: runtime


class _ScriptedProvider:
    """Calls tools in order, remembering each result; then answers."""

    def __init__(self, calls: list[tuple[str, dict]], answer: str = "Готово.") -> None:
        self._calls = calls
        self._answer = answer
        self.results = []

    def run(
        self,
        message: str,
        history: list[AssistantHistoryMessage],
        ui_context: str,
        reference_datetime: datetime,
        timezone: str,
        tool_runner,
    ) -> AssistantProviderResult:
        affected: list[uuid.UUID] = []
        for tool_name, arguments in self._calls:
            result = tool_runner(tool_name, arguments)
            self.results.append(result)
            if result.success and result.output:
                collect_object_ids_from_bounded_tool(tool_name, result.output, [], affected)
            if hasattr(tool_runner, "commit_model_visible_outputs"):
                tool_runner.commit_model_visible_outputs()
        return AssistantProviderResult(
            answer=self._answer,
            candidate_object_ids=[],
            affected_object_ids=affected,
            store_false_used=True,
        )


def _label_service(session: Session, user_id: uuid.UUID) -> LabelService:
    return LabelService(session, user_id)


def _note(session: Session, user_id: uuid.UUID, title: str = "Note") -> Object:
    return GraphService(session, user_id).create_object(
        ObjectCreate(kind="note", title=title, origin="user")
    )


def _email(session: Session, user_id: uuid.UUID, title: str = "Mail") -> Object:
    email = GraphService(session, user_id).create_object(
        ObjectCreate(kind="email", title=title, origin="source", provider="gmail", state="observed")
    )
    email.external_id = "gmail-msg-pass-c"
    email.metadata_ = {"gmail_labels": ["INBOX"]}
    session.flush()
    return email


def _pap_count(session: Session, user_id: uuid.UUID) -> int:
    return session.scalar(
        select(func.count()).select_from(PendingActionPlan).where(PendingActionPlan.user_id == user_id)
    )


def _label_count(session: Session, user_id: uuid.UUID) -> int:
    return session.scalar(
        select(func.count()).select_from(Object).where(Object.user_id == user_id, Object.kind == KIND_LABEL)
    )


def _assignment_edges(session: Session, object_id: uuid.UUID, label_id: uuid.UUID) -> list[Edge]:
    return list(
        session.scalars(
            select(Edge).where(
                Edge.source_id == object_id,
                Edge.target_id == label_id,
                Edge.type == EDGE_TYPE_LABELED_WITH,
            )
        )
    )


def _seeded_budget(seen: list[uuid.UUID], telemetry: AssistantTurnTelemetry | None = None) -> PerTurnToolBudget:
    return PerTurnToolBudget(telemetry=telemetry, initial_seen_object_ids=seen)


# --------------------------------------------------------------------------- policy / registry


def test_annotate_permission_definition() -> None:
    assert ToolPermission.ANNOTATE.value == "ANNOTATE"
    assert ToolPermission("ANNOTATE") is ToolPermission.ANNOTATE
    assert ToolPermission.ANNOTATE is not ToolPermission.READ
    assert {member.value for member in ToolPermission} == {
        "READ",
        "ANNOTATE",
        "INTERNAL_WRITE",
        "DESTRUCTIVE_INTERNAL_WRITE",
        "EXTERNAL_PROPOSE",
        "EXTERNAL_WRITE",
        "COMMUNICATE",
    }


def test_annotate_policy_matrix() -> None:
    assert evaluate_policy(ToolPermission.ANNOTATE, ExecutionContext.APPROVED_ACTION_PLAN) == PolicyDecision.ALLOW
    assert evaluate_policy(ToolPermission.ANNOTATE, ExecutionContext.INTERACTIVE_ASSISTANT) == PolicyDecision.ALLOW
    assert evaluate_policy(ToolPermission.ANNOTATE, ExecutionContext.MCP) == PolicyDecision.REQUIRE_APPROVAL
    assert evaluate_policy(ToolPermission.ANNOTATE, ExecutionContext.BASELINE) == PolicyDecision.ALLOW
    assert evaluate_policy(ToolPermission.ANNOTATE) == PolicyDecision.ALLOW


def test_full_policy_matrix_is_exactly_as_expected() -> None:
    for permission in ToolPermission:
        for context in ExecutionContext:
            assert evaluate_policy(permission, context) == EXPECTED_POLICY_MATRIX[(permission, context)], (
                permission,
                context,
            )


def test_registry_permissions_frozen_except_two_annotations() -> None:
    assert {name: spec.permission for name, spec in TOOL_REGISTRY.items()} == EXPECTED_REGISTRY_PERMISSIONS
    assert TOOL_REGISTRY["assign_label"].permission == ToolPermission.ANNOTATE
    assert TOOL_REGISTRY["remove_label"].permission == ToolPermission.ANNOTATE
    assert TOOL_REGISTRY["create_label"].permission == ToolPermission.INTERNAL_WRITE
    assert TOOL_REGISTRY["rename_label"].permission == ToolPermission.INTERNAL_WRITE
    assert TOOL_REGISTRY["delete_label"].permission == ToolPermission.DESTRUCTIVE_INTERNAL_WRITE
    assert TOOL_REGISTRY["assign_label"].prepare_method is None
    assert TOOL_REGISTRY["remove_label"].prepare_method is None


def test_annotate_is_a_mutation_not_a_read() -> None:
    assert "assign_label" in _MUTATION_TOOLS
    assert "remove_label" in _MUTATION_TOOLS
    assert "assign_label" not in _READ_TOOLS
    assert "remove_label" not in _READ_TOOLS
    assert "list_labels" in _READ_TOOLS
    assert "list_inbox_since_review_marker" in _READ_TOOLS
    assert "list_conversation_members" in _READ_TOOLS
    assert "set_inbox_review_marker" in _MUTATION_TOOLS
    assert "clear_inbox_review_marker" in _MUTATION_TOOLS
    assert "set_inbox_review_marker" not in _READ_TOOLS
    assert "clear_inbox_review_marker" not in _READ_TOOLS


def test_no_llm_call_in_policy_module() -> None:
    import app.tools.policy as policy_module

    source = inspect.getsource(policy_module)
    imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
    assert imports == ["from enum import Enum", "from app.tools.execution_context import ExecutionContext"]
    assert "openai" not in source.lower()
    assert "llm" not in source.lower()


# --------------------------------------------------------------------------- interactive direct execution


def test_interactive_assign_existing_label_executes_without_plan(interactive_session, pass_c_user) -> None:
    session = interactive_session
    label = _label_service(session, pass_c_user).create_label("Наука").label
    note = _note(session, pass_c_user)
    before_paps = _pap_count(session, pass_c_user)
    before_labels = _label_count(session, pass_c_user)

    result = run_assistant_tool(
        pass_c_user, "assign_label", {"object_id": str(note.id), "label_id": str(label.id)}
    )
    assert result.success is True
    assert result.status == ToolExecutionStatus.SUCCESS
    assert result.approval_required is False
    assert result.staged_action is None
    assert result.output == {"object_id": str(note.id), "label_id": str(label.id), "created": True}
    assert result.validated_arguments == {"object_id": str(note.id), "label_id": str(label.id)}

    again = run_assistant_tool(
        pass_c_user, "assign_label", {"object_id": str(note.id), "label_id": str(label.id)}
    )
    assert again.success is True
    assert again.output["created"] is False

    edges = _assignment_edges(session, note.id, label.id)
    assert len(edges) == 1
    assert edges[0].state == CONFIRMED_STATE
    assert edges[0].origin == AGENT_ORIGIN
    assert _pap_count(session, pass_c_user) == before_paps
    assert _label_count(session, pass_c_user) == before_labels
    assert [item.title for item in _label_service(session, pass_c_user).get_object_labels(note.id)] == ["Наука"]


def test_interactive_remove_assignment_executes_without_plan(interactive_session, pass_c_user) -> None:
    session = interactive_session
    service = _label_service(session, pass_c_user)
    label = service.create_label("Внимание · Важно").label
    email = _email(session, pass_c_user)
    service.assign_label(email.id, label.id)
    before_paps = _pap_count(session, pass_c_user)

    result = run_assistant_tool(
        pass_c_user, "remove_label", {"object_id": str(email.id), "label_id": str(label.id)}
    )
    assert result.success is True
    assert result.status == ToolExecutionStatus.SUCCESS
    assert result.output == {"object_id": str(email.id), "label_id": str(label.id), "changed": True}

    again = run_assistant_tool(
        pass_c_user, "remove_label", {"object_id": str(email.id), "label_id": str(label.id)}
    )
    assert again.success is True
    assert again.output["changed"] is False
    assert _pap_count(session, pass_c_user) == before_paps

    # remove != delete: content object and Label object survive; assignment is rejected.
    session.refresh(email)
    assert email.deleted_at is None
    assert email.state == "observed"
    label_obj = session.get(Object, label.id)
    assert label_obj.deleted_at is None
    assert label_obj.state != REJECTED_STATE
    assert [item.id for item in service.list_labels()] == [label.id]
    edges = _assignment_edges(session, email.id, label.id)
    assert len(edges) == 1
    assert edges[0].state == REJECTED_STATE
    assert service.get_object_labels(email.id) == []


def test_interactive_taxonomy_and_task_mutations_still_require_approval(
    interactive_session, pass_c_user
) -> None:
    session = interactive_session
    label = _label_service(session, pass_c_user).create_label("Проект · ADH").label
    before_labels = _label_count(session, pass_c_user)
    before_paps = _pap_count(session, pass_c_user)
    for name, arguments in (
        ("create_label", {"name": "Совершенно новая"}),
        ("rename_label", {"label_id": str(label.id), "name": "ADH"}),
        ("delete_label", {"label_id": str(label.id)}),
        ("create_task", {"title": "Approval still required", "confidence": 0.9}),
        ("link_objects", {"source_id": str(uuid.uuid4()), "target_id": str(uuid.uuid4()), "relation_type": "related_to", "confidence": 0.5}),
    ):
        result = run_assistant_tool(pass_c_user, name, arguments)
        assert result.success is False, name
        assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED, name
        assert result.staged_action is not None, name
        assert result.staged_action["permission"] != ToolPermission.ANNOTATE.value, name
    assert _label_count(session, pass_c_user) == before_labels
    session.refresh(session.get(Object, label.id))
    assert session.get(Object, label.id).title == "Проект · ADH"
    assert session.get(Object, label.id).deleted_at is None
    assert _pap_count(session, pass_c_user) == before_paps
    tasks = session.scalar(
        select(func.count()).select_from(Object).where(Object.user_id == pass_c_user, Object.kind == "task")
    )
    assert tasks == 0


def test_assistant_message_assign_returns_no_pending_plan(
    assistant_client, interactive_session, pass_c_user
) -> None:
    session = interactive_session
    label = _label_service(session, pass_c_user).create_label("Наука").label
    note = _note(session, pass_c_user, "Статья про графы")
    provider = _ScriptedProvider(
        [
            ("get_object", {"object_id": str(note.id)}),
            ("list_labels", {"limit": 50}),
            ("assign_label", {"object_id": str(note.id), "label_id": str(label.id)}),
        ],
        answer="Пометил как Наука.",
    )
    _install_provider(provider)
    before_paps = _pap_count(session, pass_c_user)

    response = assistant_client.post(
        "/assistant/message",
        json={"message": "Пометь эту заметку как Наука", "context_object_id": str(note.id)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pending_action_plan"] is None
    assert body["answer"] == "Пометил как Наука."
    assert [result.status for result in provider.results] == [ToolExecutionStatus.SUCCESS] * 3
    assert provider.results[2].output["created"] is True
    assert str(note.id) in {item["object_id"] for item in body["affected_objects"]}
    assert _pap_count(session, pass_c_user) == before_paps
    assert len(_assignment_edges(session, note.id, label.id)) == 1
    traces = list(
        session.scalars(
            select(AITrace).where(
                AITrace.user_id == pass_c_user, AITrace.workload == WORKLOAD_ASSISTANT_INTERACTIVE
            )
        )
    )
    assert len(traces) == 1
    assert traces[0].success is True


def test_provider_loop_audits_direct_assign_label(interactive_session, pass_c_user, monkeypatch) -> None:
    """Real provider loop with a fake OpenAI client: tool_call trace event, no plan."""
    session = interactive_session
    label = _label_service(session, pass_c_user).create_label("Наука").label
    note = _note(session, pass_c_user)
    rounds: list[dict] = []

    class FakeResponses:
        def create(self, **kwargs):
            rounds.append(kwargs)
            response = MagicMock()
            response.status = "completed"
            response.usage = MagicMock(input_tokens=1, output_tokens=1)
            if len(rounds) == 1:
                call = MagicMock()
                call.type = "function_call"
                call.name = "assign_label"
                call.call_id = "call-1"
                call.arguments = f'{{"object_id": "{note.id}", "label_id": "{label.id}"}}'
                response.output = [call]
                response.output_text = ""
            else:
                response.output = []
                response.output_text = "Пометил как Наука."
            return response

    class FakeClient:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))
    provider = OpenAIAssistantProvider(api_key="test", model="gpt-test", max_rounds=4)
    budget = _seeded_budget([note.id, label.id])
    runner = BoundAssistantToolRunner(budget, pass_c_user)
    with ai_trace_session(
        pass_c_user, WORKLOAD_ASSISTANT_INTERACTIVE, session=session, commit_on_exit=False
    ) as trace:
        result = provider.run(
            message="Пометь это как Наука",
            history=[],
            ui_context="",
            reference_datetime=datetime.now(UTC),
            timezone="Europe/Amsterdam",
            tool_runner=runner,
        )
    assert result.answer == "Пометил как Наука."
    assert result.affected_object_ids == [note.id]
    assert budget.staged_actions == []
    assert _pap_count(session, pass_c_user) == 0
    assert len(rounds) == 2
    replayed = rounds[1]["input"][-1]
    assert replayed["type"] == "function_call_output"
    assert replayed["call_id"] == "call-1"
    assert json.loads(replayed["output"]) == {
        "object_id": str(note.id),
        "label_id": str(label.id),
        "created": True,
    }
    events = list(
        session.scalars(
            select(AITraceEvent)
            .where(AITraceEvent.trace_id == trace.trace_id, AITraceEvent.event_type == EVENT_TOOL_CALL)
            .order_by(AITraceEvent.sequence)
        )
    )
    assert len(events) == 1
    meta = events[0].metadata_
    assert meta["tool_name"] == "assign_label"
    assert meta["success"] is True
    assert meta["argument_keys"] == ["label_id", "object_id"]
    edges = _assignment_edges(session, note.id, label.id)
    assert len(edges) == 1
    assert edges[0].state == CONFIRMED_STATE


def test_assistant_message_remove_returns_no_pending_plan(
    assistant_client, interactive_session, pass_c_user
) -> None:
    session = interactive_session
    service = _label_service(session, pass_c_user)
    label = service.create_label("Внимание · Важно").label
    email = _email(session, pass_c_user)
    service.assign_label(email.id, label.id)
    provider = _ScriptedProvider(
        [
            ("list_neighbors", {"object_id": str(email.id)}),
            ("remove_label", {"object_id": str(email.id), "label_id": str(label.id)}),
        ],
        answer="Снял метку.",
    )
    _install_provider(provider)
    before_paps = _pap_count(session, pass_c_user)

    response = assistant_client.post(
        "/assistant/message",
        json={"message": "Сними с этого письма метку Внимание · Важно", "context_object_id": str(email.id)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pending_action_plan"] is None
    assert provider.results[1].status == ToolExecutionStatus.SUCCESS
    assert provider.results[1].output["changed"] is True
    assert str(email.id) in {item["object_id"] for item in body["affected_objects"]}
    assert _pap_count(session, pass_c_user) == before_paps
    assert service.get_object_labels(email.id) == []
    assert session.get(Object, label.id).deleted_at is None


def test_assistant_message_create_label_still_produces_plan(
    assistant_client, interactive_session, pass_c_user
) -> None:
    session = interactive_session
    note = _note(session, pass_c_user)
    provider = _ScriptedProvider(
        [
            ("list_labels", {"limit": 50}),
            ("create_label", {"name": "Совершенно новая категория"}),
        ],
        answer="Такой метки нет — создать?",
    )
    _install_provider(provider)
    before_labels = _label_count(session, pass_c_user)

    response = assistant_client.post(
        "/assistant/message",
        json={"message": "Пометь как Совершенно новая категория", "context_object_id": str(note.id)},
    )
    assert response.status_code == 200, response.text
    plan = response.json()["pending_action_plan"]
    assert plan is not None
    assert plan["status"] == PENDING_ACTION_PLAN_STATUS_PENDING
    assert plan["actions"] == [
        {"tool_name": "create_label", "arguments": {"name": "Совершенно новая категория"}}
    ]
    assert _label_count(session, pass_c_user) == before_labels


# --------------------------------------------------------------------------- per-turn budget guards


def test_budget_requires_exposed_object_and_label_ids(interactive_session, pass_c_user) -> None:
    session = interactive_session
    label = _label_service(session, pass_c_user).create_label("Наука").label
    note = _note(session, pass_c_user)
    telemetry = AssistantTurnTelemetry()
    budget = _seeded_budget([], telemetry)
    runner = BoundAssistantToolRunner(budget, pass_c_user)

    unseen_object = runner("assign_label", {"object_id": str(note.id), "label_id": str(label.id)})
    assert unseen_object.success is False
    assert unseen_object.status == ToolExecutionStatus.TOOL_ERROR
    assert "object was not exposed" in unseen_object.error
    assert telemetry.tool_calls == 1

    runner("get_object", {"object_id": str(note.id)})
    runner.commit_model_visible_outputs()
    unseen_label = runner("assign_label", {"object_id": str(note.id), "label_id": str(label.id)})
    assert unseen_label.success is False
    assert "label was not exposed" in unseen_label.error
    assert "list_labels" in unseen_label.error

    runner("list_labels", {"limit": 20})
    runner.commit_model_visible_outputs()
    assigned = runner("assign_label", {"object_id": str(note.id), "label_id": str(label.id)})
    assert assigned.success is True
    assert assigned.output["created"] is True
    assert assigned.model_output_json is not None
    assert budget.staged_actions == []
    assert telemetry.tool_calls == 5
    assert len(_assignment_edges(session, note.id, label.id)) == 1

    missing = runner("remove_label", {"object_id": str(note.id)})
    assert missing.status == ToolExecutionStatus.TOOL_ERROR
    assert "label_id is required" in missing.error
    bad = runner("remove_label", {"object_id": str(note.id), "label_id": "not-a-uuid"})
    assert bad.status == ToolExecutionStatus.TOOL_ERROR
    assert "invalid label id" in bad.error


def test_budget_blocks_annotation_after_plan_sealed(interactive_session, pass_c_user) -> None:
    session = interactive_session
    label = _label_service(session, pass_c_user).create_label("Наука").label
    note = _note(session, pass_c_user)
    budget = _seeded_budget([note.id, label.id])
    runner = BoundAssistantToolRunner(budget, pass_c_user)
    staged = runner("create_task", {"title": "Sealed", "confidence": 0.8})
    assert staged.status == ToolExecutionStatus.APPROVAL_REQUIRED
    runner.commit_model_visible_outputs()
    blocked = runner("assign_label", {"object_id": str(note.id), "label_id": str(label.id)})
    assert blocked.status == ToolExecutionStatus.TOOL_ERROR
    assert "already staged" in blocked.error
    assert _assignment_edges(session, note.id, label.id) == []


def test_affected_object_ids_reflect_created_and_changed() -> None:
    object_id = uuid.uuid4()
    label_id = uuid.uuid4()
    affected: list[uuid.UUID] = []
    collect_object_ids_from_bounded_tool(
        "assign_label", {"object_id": str(object_id), "label_id": str(label_id), "created": False}, [], affected
    )
    assert affected == []
    collect_object_ids_from_bounded_tool(
        "assign_label", {"object_id": str(object_id), "label_id": str(label_id), "created": True}, [], affected
    )
    assert affected == [object_id]
    changed: list[uuid.UUID] = []
    collect_object_ids_from_bounded_tool(
        "remove_label", {"object_id": str(object_id), "label_id": str(label_id), "changed": False}, [], changed
    )
    assert changed == []
    collect_object_ids_from_bounded_tool(
        "remove_label", {"object_id": str(object_id), "label_id": str(label_id), "changed": True}, [], changed
    )
    assert changed == [object_id]


# --------------------------------------------------------------------------- exact args / fail-closed


def test_exact_object_and_label_ids_reach_label_service(db_session, pass_c_user, monkeypatch) -> None:
    label = _label_service(db_session, pass_c_user).create_label("Наука").label
    note = _note(db_session, pass_c_user)
    captured: list[tuple[uuid.UUID, uuid.UUID]] = []
    original = LabelService.assign_label

    def spy(self, object_id, label_id):
        captured.append((object_id, label_id))
        return original(self, object_id, label_id)

    monkeypatch.setattr(LabelService, "assign_label", spy)
    tools = DomainToolService(db_session, pass_c_user, None)
    result = ToolExecutionGateway().execute(
        tools,
        "assign_label",
        {"object_id": str(note.id), "label_id": str(label.id), "title": "Наука"},
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert result.success is False
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert captured == []

    result = ToolExecutionGateway().execute(
        tools,
        "assign_label",
        {"object_id": str(note.id), "label_id": str(label.id)},
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert result.success is True
    assert captured == [(note.id, label.id)]
    assert isinstance(captured[0][0], uuid.UUID)
    assert isinstance(captured[0][1], uuid.UUID)


def test_unknown_foreign_or_deleted_label_fails_closed(db_session, pass_c_user) -> None:
    service = _label_service(db_session, pass_c_user)
    note = _note(db_session, pass_c_user)
    other_user = uuid.uuid4()
    db_session.add(User(id=other_user, display_name="foreign"))
    db_session.flush()
    foreign = LabelService(db_session, other_user).create_label("Наука").label
    deleted = service.create_label("Старая").label
    service.delete_label(deleted.id)
    not_a_label = _note(db_session, pass_c_user, "Not a label")
    before_labels = _label_count(db_session, pass_c_user)
    before_edges = db_session.scalar(
        select(func.count()).select_from(Edge).where(Edge.user_id == pass_c_user, Edge.type == EDGE_TYPE_LABELED_WITH)
    )
    tools = DomainToolService(db_session, pass_c_user, None)
    gateway = ToolExecutionGateway()
    for label_id in (uuid.uuid4(), foreign.id, deleted.id, not_a_label.id):
        result = gateway.execute(
            tools,
            "assign_label",
            {"object_id": str(note.id), "label_id": str(label_id)},
            context=ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        assert result.success is False, label_id
        assert result.status == ToolExecutionStatus.TOOL_ERROR, label_id
        assert result.approval_required is False
    assert _label_count(db_session, pass_c_user) == before_labels
    after_edges = db_session.scalar(
        select(func.count()).select_from(Edge).where(Edge.user_id == pass_c_user, Edge.type == EDGE_TYPE_LABELED_WITH)
    )
    assert after_edges == before_edges
    # Neither the deleted label's key nor the foreign label leaked into this user's vocabulary.
    assert [item.title for item in service.list_labels()] == []
    # Foreign content object is equally rejected (ownership validation).
    foreign_note = _note(db_session, other_user, "Foreign note")
    own_label = service.create_label("Своя").label
    foreign_target = gateway.execute(
        tools,
        "assign_label",
        {"object_id": str(foreign_note.id), "label_id": str(own_label.id)},
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert foreign_target.status == ToolExecutionStatus.TOOL_ERROR
    assert _assignment_edges(db_session, foreign_note.id, own_label.id) == []


def test_domain_tool_service_never_resolves_labels_by_title() -> None:
    source = inspect.getsource(DomainToolService.assign_label) + inspect.getsource(DomainToolService.remove_label)
    assert "title" not in source
    assert "normalize_label_name" not in source
    assert "input.object_id, input.label_id" in source


# --------------------------------------------------------------------------- provider safety


def test_annotation_leaves_provider_fields_and_queues_untouched(db_session, pass_c_user, monkeypatch) -> None:
    monkeypatch.setattr(assistant_session_module, "SessionLocal", lambda: _SessionProxy(db_session))
    monkeypatch.setattr(
        "app.assistant.session.resolve_embedding_service_for_user", lambda session, user_id: None
    )
    label = _label_service(db_session, pass_c_user).create_label("Внимание · Важно").label
    email = _email(db_session, pass_c_user)
    before_attempts = db_session.scalar(select(func.count()).select_from(ExternalActionAttempt))
    before_jobs = db_session.scalar(select(func.count()).select_from(Job))
    snapshot = (email.provider, email.external_id, dict(email.metadata_), email.canonical_uri, email.status)

    assigned = run_assistant_tool(
        pass_c_user, "assign_label", {"object_id": str(email.id), "label_id": str(label.id)}
    )
    removed = run_assistant_tool(
        pass_c_user, "remove_label", {"object_id": str(email.id), "label_id": str(label.id)}
    )
    assert assigned.success and removed.success
    db_session.refresh(email)
    assert (email.provider, email.external_id, dict(email.metadata_), email.canonical_uri, email.status) == snapshot
    assert db_session.scalar(select(func.count()).select_from(ExternalActionAttempt)) == before_attempts
    assert db_session.scalar(select(func.count()).select_from(Job)) == before_jobs


# --------------------------------------------------------------------------- MCP fail-closed


def test_mcp_list_labels_reads_but_annotations_fail_closed(db_session, patched_mcp_tool_session) -> None:
    service = _label_service(db_session, BOOTSTRAP_USER_ID)
    label = service.create_label("Наука").label
    note = _note(db_session, BOOTSTRAP_USER_ID)
    listed = execute_mcp_tool("list_labels", {"limit": 20})
    assert [item.id for item in listed.labels] == [label.id]

    with pytest.raises(ToolError, match="requires approval"):
        execute_mcp_tool("assign_label", {"object_id": str(note.id), "label_id": str(label.id)})
    assert _assignment_edges(db_session, note.id, label.id) == []

    service.assign_label(note.id, label.id)
    with pytest.raises(ToolError, match="requires approval"):
        execute_mcp_tool("remove_label", {"object_id": str(note.id), "label_id": str(label.id)})
    edges = _assignment_edges(db_session, note.id, label.id)
    assert len(edges) == 1
    assert edges[0].state != REJECTED_STATE

    before_labels = _label_count(db_session, BOOTSTRAP_USER_ID)
    with pytest.raises(ToolError, match="requires approval"):
        execute_mcp_tool("create_label", {"name": "Новая"})
    with pytest.raises(ToolError, match="requires approval"):
        execute_mcp_tool("rename_label", {"label_id": str(label.id), "name": "Science"})
    with pytest.raises(ToolError, match="requires approval"):
        execute_mcp_tool("delete_label", {"label_id": str(label.id)})
    assert _label_count(db_session, BOOTSTRAP_USER_ID) == before_labels
    label_obj = db_session.get(Object, label.id)
    db_session.refresh(label_obj)
    assert label_obj.title == "Наука"
    assert label_obj.deleted_at is None


@pytest.mark.asyncio
async def test_mcp_client_assign_label_is_error_without_mutation(db_session, patched_mcp_tool_session) -> None:
    from mcp.client import Client

    from app.mcp.server import create_mcp_server

    label = _label_service(db_session, BOOTSTRAP_USER_ID).create_label("Наука").label
    note = _note(db_session, BOOTSTRAP_USER_ID)
    async with Client(create_mcp_server()) as client:
        result = await client.call_tool(
            "assign_label", {"object_id": str(note.id), "label_id": str(label.id)}
        )
    assert result.is_error
    assert "approval" in result.content[0].text.lower()
    assert _assignment_edges(db_session, note.id, label.id) == []


# --------------------------------------------------------------------------- action plan compatibility


def test_legacy_action_plan_with_label_assignment_still_executes_exact_args(db_session, pass_c_user) -> None:
    label = _label_service(db_session, pass_c_user).create_label("Наука").label
    note = _note(db_session, pass_c_user)
    legacy_actions = [
        {
            "tool_name": "assign_label",
            "permission": "INTERNAL_WRITE",  # previous policy era
            "arguments": {"object_id": str(note.id), "label_id": str(label.id)},
        }
    ]
    validate_action_plan_actions(legacy_actions)
    plan = PendingActionPlan(
        user_id=pass_c_user,
        status=PENDING_ACTION_PLAN_STATUS_PENDING,
        actions=legacy_actions,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db_session.add(plan)
    db_session.flush()
    # A permission-class change alone never executes a pending plan.
    assert _assignment_edges(db_session, note.id, label.id) == []
    assert db_session.get(PendingActionPlan, plan.id).status == PENDING_ACTION_PLAN_STATUS_PENDING

    view = ActionPlanService(db_session, pass_c_user).approve(plan.id)
    assert view.status == PENDING_ACTION_PLAN_STATUS_EXECUTED
    assert view.result["actions"][0]["output"] == {
        "object_id": str(note.id),
        "label_id": str(label.id),
        "created": True,
    }
    edges = _assignment_edges(db_session, note.id, label.id)
    assert len(edges) == 1
    assert edges[0].state == CONFIRMED_STATE
    assert view.actions == [
        {"tool_name": "assign_label", "arguments": {"object_id": str(note.id), "label_id": str(label.id)}}
    ]


def test_approved_context_allows_annotate_via_gateway(db_session, pass_c_user) -> None:
    label = _label_service(db_session, pass_c_user).create_label("Наука").label
    note = _note(db_session, pass_c_user)
    tools = DomainToolService(db_session, pass_c_user, None)
    result = ToolExecutionGateway().execute(
        tools,
        "remove_label",
        {"object_id": str(note.id), "label_id": str(label.id)},
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert result.success is True
    assert result.output["changed"] is False


# --------------------------------------------------------------------------- proactive frozen


def test_proactive_allowlist_exact_and_annotations_rejected_before_gateway() -> None:
    assert PROACTIVE_READ_TOOL_NAMES == (
        "retrieve",
        "query_objects",
        "get_object",
        "get_context",
        "list_neighbors",
        "list_notifications",
    )
    assert tuple(item["name"] for item in PROACTIVE_TOOL_DEFINITIONS) == PROACTIVE_READ_TOOL_NAMES
    for forbidden in ("list_labels", "assign_label", "remove_label", "create_label"):
        assert forbidden not in PROACTIVE_READ_TOOL_NAMES

    gateway = MagicMock()
    runner = ProactiveToolRunner(MagicMock(), gateway=gateway)
    for tool_name in ("assign_label", "remove_label"):
        result = runner(tool_name, {"object_id": str(uuid.uuid4()), "label_id": str(uuid.uuid4())})
        assert result.success is False
        assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert runner.rejected_tool_names == ["assign_label", "remove_label"]
    assert runner.security_violation
    gateway.execute.assert_not_called()


def test_label_annotation_does_not_trip_proactive_gate(db_session, monkeypatch) -> None:
    import tests.test_proactive_secretary_c as proactive_c

    proactive_c._enable(db_session)
    service = _label_service(db_session, BOOTSTRAP_USER_ID)
    label = service.create_label("Наука").label
    note = _note(db_session, BOOTSTRAP_USER_ID)
    # The content object itself predates the review window; only label bookkeeping is recent.
    stale = datetime.now(UTC) - timedelta(days=3)
    note.created_at = stale
    note.updated_at = stale
    db_session.flush()
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, None)
    gateway = ToolExecutionGateway()
    args = {"object_id": str(note.id), "label_id": str(label.id)}
    assert gateway.execute(tools, "assign_label", args, context=ExecutionContext.INTERACTIVE_ASSISTANT).success
    assert gateway.execute(tools, "remove_label", args, context=ExecutionContext.INTERACTIVE_ASSISTANT).success
    provider = proactive_c._install_provider(
        monkeypatch, proactive_c.ScriptedProactiveProvider(proactive_c._none_answer())
    )
    monkeypatch.setattr(
        "app.services.proactive_review_service.ai_trace_session",
        lambda *args, **kwargs: __import__("contextlib").nullcontext(),
    )
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(
        {"window_start": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}
    )
    assert provider.calls == 0


# --------------------------------------------------------------------------- instructions / no hardcoded taxonomy


def test_assistant_instructions_carry_relevance_evidence_contract() -> None:
    text = SYSTEM_INSTRUCTIONS
    lowered = text.lower()
    assert "optional evidence" in lowered
    assert "not an authoritative user profile" in lowered
    assert "absence of a label does not mean absence of the concept" in lowered
    assert "never authorizes a mutation or external action" in lowered
    assert "never replaces approval" in lowered
    # User-directed annotation only; no auto-labeling instruction.
    assert "only when the current user request asks" in lowered
    assert "do not assign or remove labels while answering ordinary questions" in lowered
    assert "do not create one silently" in lowered
    assert "create_label, rename_label, and delete_label" in lowered
    assert "require approval" in lowered
    for prefix in HARDCODED_TAXONOMY_PREFIXES:
        assert prefix not in text
    for role in ("Отвечаю", "Участвую", "Наблюдаю", "Жду от других"):
        assert role not in text


def test_no_hardcoded_taxonomy_parser_or_auto_label_job_in_backend() -> None:
    python_files = list(BACKEND_APP.rglob("*.py"))
    assert python_files
    scoring_pattern = re.compile(
        r"responsibility_score|relevance_score\s*[-+]=\s*|\buser_role\b",
        re.IGNORECASE,
    )
    for path in python_files:
        source = path.read_text(encoding="utf-8")
        for prefix in HARDCODED_TAXONOMY_PREFIXES:
            assert prefix not in source, f"{path} hardcodes label taxonomy prefix {prefix!r}"
        for role in ("Отвечаю", "Участвую", "Наблюдаю", "Жду от других"):
            assert role not in source, f"{path} hardcodes role label {role!r}"
        assert not scoring_pattern.search(source), f"{path} introduces relevance/role scoring"
    for job_type in HANDLERS:
        if job_type == "auto_label_object":
            continue
        assert "label" not in job_type
        assert "classif" not in job_type
    job_constants = (BACKEND_APP / "jobs" / "constants.py").read_text(encoding="utf-8")
    assert "auto_label_object" in job_constants
    for line in job_constants.splitlines():
        lowered = line.lower()
        if "auto_label_object" in lowered:
            continue
        assert "label" not in lowered
    proactive_service = (BACKEND_APP / "services" / "proactive_review_service.py").read_text(encoding="utf-8")
    assert "assign_label" not in proactive_service
    assert "remove_label" not in proactive_service


def test_pass_c_did_not_add_label_migration() -> None:
    versions = sorted(
        path.name for path in (BACKEND_APP.parent / "alembic" / "versions").glob("*.py") if path.name[0].isdigit()
    )
    assert any(name.startswith("0032") for name in versions)
    assert any(name.startswith("0033") for name in versions)
    assert any(name.startswith("0034") for name in versions)
    assert versions[-1].startswith("0042")
