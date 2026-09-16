"""PHASE 23D-A — frozen pending action plans and exact approval execution."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.assistant import get_assistant_runtime
import app.api.assistant as assistant_api_module
from app.api.deps import get_db, get_embedding_service
from app.api.schemas import ObjectCreate, EdgeCreate
from app.assistant.action_plan_constants import (
    PENDING_ACTION_PLAN_STATUS_EXECUTED,
    PENDING_ACTION_PLAN_STATUS_EXPIRED,
    PENDING_ACTION_PLAN_STATUS_FAILED,
    PENDING_ACTION_PLAN_STATUS_PENDING,
    PENDING_ACTION_PLAN_STATUS_REJECTED,
)
from app.assistant.session import run_assistant_tool
from app.assistant.tool_runner import BoundAssistantToolRunner, PerTurnToolBudget
from app.db.models import Edge, Object, PendingActionPlan, User
from app.llm.assistant_models import AssistantHistoryMessage, AssistantProviderResult
from app.main import app
from app.services.domain_tool_service import DomainToolService
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE, PROPOSED_STATE
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.policy import PolicyDecision, ToolPermission, evaluate_policy
from app.tools.results import ToolExecutionStatus
from tests.conftest import apply_embedding_service_overrides, AuthTestClient

ORIGINAL_BUILD_ASSISTANT_RUNTIME = assistant_api_module.build_assistant_runtime


class _MutationOnlyProvider:
    def __init__(self, tool_name: str, arguments: dict, answer: str = "Proposed action.") -> None:
        self._tool_name = tool_name
        self._arguments = arguments
        self._answer = answer

    def run(
        self,
        message: str,
        history: list[AssistantHistoryMessage],
        ui_context: str,
        reference_datetime: datetime,
        timezone: str,
        tool_runner,
    ) -> AssistantProviderResult:
        tool_runner(self._tool_name, self._arguments)
        return AssistantProviderResult(
            answer=self._answer,
            candidate_object_ids=[],
            affected_object_ids=[],
            store_false_used=True,
        )


class _ReadThenMutateProvider:
    def run(
        self,
        message: str,
        history: list[AssistantHistoryMessage],
        ui_context: str,
        reference_datetime: datetime,
        timezone: str,
        tool_runner,
    ) -> AssistantProviderResult:
        tool_runner("get_today", {})
        tool_runner(
            "create_task",
            {
                "title": "Staged task",
                "confidence": 0.85,
            },
        )
        return AssistantProviderResult(
            answer="I propose creating a task.",
            candidate_object_ids=[],
            affected_object_ids=[],
            store_false_used=True,
        )


class _MultiMutationProvider:
    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        self._calls = calls

    def run(
        self,
        message: str,
        history: list[AssistantHistoryMessage],
        ui_context: str,
        reference_datetime: datetime,
        timezone: str,
        tool_runner,
    ) -> AssistantProviderResult:
        for tool_name, arguments in self._calls:
            tool_runner(tool_name, arguments)
        return AssistantProviderResult(
            answer="Proposed multiple actions.",
            candidate_object_ids=[],
            affected_object_ids=[],
            store_false_used=True,
        )


class _FailingProvider:
    def run(self, *args, **kwargs):
        from app.llm.openai_assistant_provider import AssistantProviderError

        raise AssistantProviderError("provider failed")


class _ResumeTextOnlyProvider:
    def __init__(self, answer: str = "Готово. Я создал задачу.") -> None:
        self._answer = answer
        self.text_only_calls = 0
        self.run_calls = 0
        self.last_finalize_context: str | None = None

    def run(
        self,
        message: str,
        history: list[AssistantHistoryMessage],
        ui_context: str,
        reference_datetime: datetime,
        timezone: str,
        tool_runner,
    ) -> AssistantProviderResult:
        self.run_calls += 1
        tool_runner(
            "create_task",
            {"title": "Resume flow task", "confidence": 0.8},
        )
        return AssistantProviderResult(
            answer="Proposed.",
            candidate_object_ids=[],
            affected_object_ids=[],
            store_false_used=True,
        )

    def run_text_only(self, message: str, context: str) -> AssistantProviderResult:
        self.text_only_calls += 1
        self.last_finalize_context = context
        return AssistantProviderResult(
            answer=self._answer,
            candidate_object_ids=[],
            affected_object_ids=[],
            store_false_used=True,
            openai_model="test-model",
            openai_input_tokens=10,
            openai_output_tokens=5,
            openai_responses_rounds=1,
        )


class _FailingTextOnlyProvider(_ResumeTextOnlyProvider):
    def run_text_only(self, message: str, context: str) -> AssistantProviderResult:
        from app.llm.openai_assistant_provider import AssistantProviderError

        self.text_only_calls += 1
        raise AssistantProviderError("finalize failed")


@pytest.fixture(autouse=True)
def _restore_session_local_after_action_plan_test() -> None:
    yield
    import app.assistant.session as assistant_session_module
    import app.services.assistant_service as assistant_service_module
    from app.db.session import SessionLocal

    assistant_service_module.SessionLocal = SessionLocal
    assistant_session_module.SessionLocal = SessionLocal


@pytest.fixture
def action_plan_user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="action plan user"))
    db_session.flush()
    return user_id


@pytest.fixture
def action_plan_client(db_session, fake_embedding_service, action_plan_user, issue_bearer):
    bearer = issue_bearer(action_plan_user)
    headers = {"Authorization": f"Bearer {bearer}"}

    def override_get_db():
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)

    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, headers), action_plan_user
    app.dependency_overrides.clear()
    assistant_api_module.build_assistant_runtime = ORIGINAL_BUILD_ASSISTANT_RUNTIME


def _override_assistant_provider(provider, monkeypatch=None) -> None:
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
    if monkeypatch is not None:
        monkeypatch.setattr(
            assistant_api_module,
            "build_assistant_runtime",
            lambda session, user_id: runtime,
        )


def _set_assistant_runtime_override(provider) -> None:
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
    app.dependency_overrides[get_assistant_runtime] = lambda: AssistantRuntime(
        provider=provider,
        effective=effective,
    )
    assistant_api_module.build_assistant_runtime = lambda session, user_id: AssistantRuntime(
        provider=provider,
        effective=effective,
    )


def _reload_plan(db_session, plan_id: uuid.UUID) -> PendingActionPlan:
    db_session.expire_all()
    plan = db_session.get(PendingActionPlan, plan_id)
    assert plan is not None
    return plan


def _task_count(db_session, user_id: uuid.UUID) -> int:
    return db_session.scalar(
        select(func.count()).select_from(Object).where(
            Object.user_id == user_id,
            Object.kind == "task",
        )
    )


def test_interactive_policy_requires_approval_for_internal_write():
    assert (
        evaluate_policy(ToolPermission.INTERNAL_WRITE, ExecutionContext.INTERACTIVE_ASSISTANT)
        == PolicyDecision.REQUIRE_APPROVAL
    )
    assert evaluate_policy(ToolPermission.READ, ExecutionContext.INTERACTIVE_ASSISTANT) == (
        PolicyDecision.ALLOW
    )


def test_interactive_create_task_does_not_mutate(db_session, fake_embedding_service):
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="mutation gate"))
    db_session.flush()
    before = _task_count(db_session, user_id)
    result = run_assistant_tool(
        user_id,
        "create_task",
        {"title": "Blocked task", "confidence": 0.9},
    )
    assert result.success is False
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert result.staged_action is not None
    assert result.staged_action["arguments"]["title"] == "Blocked task"
    after = _task_count(db_session, user_id)
    assert after == before


def test_per_turn_budget_stages_validated_action(db_session, fake_embedding_service, action_plan_user):
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, action_plan_user)
    result = runner(
        "create_task",
        {"title": "Budget staged", "confidence": 0.8},
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert len(budget.staged_actions) == 1
    assert budget.staged_actions[0]["arguments"]["title"] == "Budget staged"


def test_invalid_evidence_not_staged(db_session, fake_embedding_service, action_plan_user):
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, action_plan_user)
    unseen = uuid.uuid4()
    result = runner(
        "create_task",
        {
            "title": "Bad evidence",
            "confidence": 0.8,
            "evidence_object_ids": [str(unseen)],
        },
    )
    assert result.success is False
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert budget.staged_actions == []


def test_assistant_message_returns_pending_plan(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    provider = _MutationOnlyProvider(
        "create_task",
        {"title": "Exact title", "confidence": 0.91},
    )

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    _set_assistant_runtime_override(provider)
    import app.services.assistant_service as assistant_service_module

    assistant_service_module.SessionLocal = lambda: _TestSession()

    before = _task_count(db_session, user_id)
    response = client.post(
        "/assistant/message",
        json={"message": "Создай задачу разобраться с этим"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pending_action_plan"] is not None
    plan = body["pending_action_plan"]
    assert plan["status"] == PENDING_ACTION_PLAN_STATUS_PENDING
    assert plan["actions"][0]["tool_name"] == "create_task"
    assert plan["actions"][0]["arguments"]["title"] == "Exact title"
    assert _task_count(db_session, user_id) == before


def test_approve_executes_exact_frozen_arguments(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    provider = _MutationOnlyProvider(
        "create_task",
        {"title": "Frozen exact", "confidence": 0.77, "body": "keep me"},
    )

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    _set_assistant_runtime_override(provider)
    import app.services.assistant_service as assistant_service_module

    assistant_service_module.SessionLocal = lambda: _TestSession()

    message_response = client.post("/assistant/message", json={"message": "create"})
    plan_id = message_response.json()["pending_action_plan"]["id"]

    approve_response = client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert approve_response.status_code == 200
    body = approve_response.json()
    assert body["status"] == PENDING_ACTION_PLAN_STATUS_EXECUTED
    tasks = db_session.scalars(
        select(Object).where(Object.user_id == user_id, Object.kind == "task")
    ).all()
    assert len(tasks) == 1
    assert tasks[0].title == "Frozen exact"
    assert tasks[0].body == "keep me"


def test_repeat_approve_is_idempotent(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    provider = _MutationOnlyProvider(
        "create_task",
        {"title": "Once only", "confidence": 0.7},
    )

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    _set_assistant_runtime_override(provider)
    import app.services.assistant_service as assistant_service_module

    assistant_service_module.SessionLocal = lambda: _TestSession()

    plan_id = client.post("/assistant/message", json={"message": "create"}).json()[
        "pending_action_plan"
    ]["id"]
    first = client.post(f"/assistant/action-plans/{plan_id}/approve")
    second = client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert first.status_code == 200
    assert second.status_code == 200
    assert _task_count(db_session, user_id) == 1


def test_reject_produces_zero_mutation(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    provider = _MutationOnlyProvider(
        "create_task",
        {"title": "Rejected task", "confidence": 0.7},
    )

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    _set_assistant_runtime_override(provider)
    import app.services.assistant_service as assistant_service_module

    assistant_service_module.SessionLocal = lambda: _TestSession()

    before = _task_count(db_session, user_id)
    plan_id = client.post("/assistant/message", json={"message": "create"}).json()[
        "pending_action_plan"
    ]["id"]
    response = client.post(f"/assistant/action-plans/{plan_id}/reject")
    assert response.status_code == 200
    assert response.json()["status"] == PENDING_ACTION_PLAN_STATUS_REJECTED
    assert _task_count(db_session, user_id) == before


def test_wrong_user_cannot_approve_plan(
    db_session, fake_embedding_service, action_plan_user, action_plan_client, issue_bearer
):
    client, _ = action_plan_client
    other_user = uuid.uuid4()
    db_session.add(User(id=other_user, display_name="other"))
    db_session.flush()
    other_bearer = issue_bearer(other_user)
    other_headers = {"Authorization": f"Bearer {other_bearer}"}

    provider = _MutationOnlyProvider(
        "create_task",
        {"title": "Private", "confidence": 0.7},
    )

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    _set_assistant_runtime_override(provider)
    import app.services.assistant_service as assistant_service_module

    assistant_service_module.SessionLocal = lambda: _TestSession()

    plan_id = client.post("/assistant/message", json={"message": "create"}).json()[
        "pending_action_plan"
    ]["id"]

    with TestClient(app) as test_client:
        other_client = AuthTestClient(test_client, other_headers)
        response = other_client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert response.status_code == 404


def test_expired_plan_does_not_execute(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    plan = PendingActionPlan(
        user_id=user_id,
        status=PENDING_ACTION_PLAN_STATUS_PENDING,
        actions=[
            {
                "tool_name": "create_task",
                "permission": "INTERNAL_WRITE",
                "arguments": {"title": "Expired", "confidence": 0.5},
            }
        ],
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(plan)
    db_session.flush()

    before = _task_count(db_session, user_id)
    response = client.post(f"/assistant/action-plans/{plan.id}/approve")
    assert response.status_code == 409
    assert response.json()["status"] == PENDING_ACTION_PLAN_STATUS_EXPIRED
    assert _task_count(db_session, user_id) == before
    reloaded = _reload_plan(db_session, plan.id)
    assert reloaded.status == PENDING_ACTION_PLAN_STATUS_EXPIRED


def test_read_tools_still_execute_during_interactive_turn(action_plan_user):
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, action_plan_user)
    result = runner("get_today", {})
    assert result.success is True
    assert result.status == ToolExecutionStatus.SUCCESS


def test_provider_failure_does_not_leave_pending_plan(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, _ = action_plan_client
    _set_assistant_runtime_override(_FailingProvider())

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    import app.services.assistant_service as assistant_service_module

    assistant_service_module.SessionLocal = lambda: _TestSession()

    response = client.post("/assistant/message", json={"message": "create"})
    assert response.status_code == 502
    count = db_session.scalar(select(func.count()).select_from(PendingActionPlan))
    assert count == 0


def test_multi_action_plan_commits_atomically(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    graph = GraphService(db_session, user_id)
    source = graph.create_object(
        ObjectCreate(kind="note", title="Source", origin="user")
    )
    target = graph.create_object(
        ObjectCreate(kind="note", title="Target", origin="user")
    )
    db_session.flush()

    provider = _MultiMutationProvider(
        [
            (
                "create_task",
                {"title": "Atomic A", "confidence": 0.8},
            ),
            (
                "link_objects",
                {
                    "source_id": str(source.id),
                    "target_id": str(target.id),
                    "relation_type": "references",
                    "confidence": 0.9,
                },
            ),
        ]
    )

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    _set_assistant_runtime_override(provider)
    import app.services.assistant_service as assistant_service_module

    assistant_service_module.SessionLocal = lambda: _TestSession()

    plan_id = client.post("/assistant/message", json={"message": "do two things"}).json()[
        "pending_action_plan"
    ]["id"]
    approve = client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert approve.status_code == 200
    assert _task_count(db_session, user_id) == 1
    edge_count = db_session.scalar(
        select(func.count()).select_from(Edge).where(Edge.user_id == user_id)
    )
    assert edge_count == 1


def test_failed_action_plan_rolls_back_internal_mutations(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    bogus_source = uuid.uuid4()
    bogus_target = uuid.uuid4()
    provider = _MultiMutationProvider(
        [
            ("create_task", {"title": "Should rollback", "confidence": 0.8}),
            (
                "link_objects",
                {
                    "source_id": str(bogus_source),
                    "target_id": str(bogus_target),
                    "relation_type": "references",
                    "confidence": 0.9,
                },
            ),
        ]
    )

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    _set_assistant_runtime_override(provider)
    import app.services.assistant_service as assistant_service_module

    assistant_service_module.SessionLocal = lambda: _TestSession()

    before = _task_count(db_session, user_id)
    plan_id = client.post("/assistant/message", json={"message": "fail mid plan"}).json()[
        "pending_action_plan"
    ]["id"]
    response = client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert response.status_code == 409
    assert response.json()["status"] == PENDING_ACTION_PLAN_STATUS_FAILED
    assert _task_count(db_session, user_id) == before
    reloaded = _reload_plan(db_session, uuid.UUID(plan_id))
    assert reloaded.status == PENDING_ACTION_PLAN_STATUS_FAILED


def test_http_approve_execution_failure_persists_failed_status(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    bogus_source = uuid.uuid4()
    bogus_target = uuid.uuid4()
    provider = _MultiMutationProvider(
        [
            ("create_task", {"title": "HTTP failed", "confidence": 0.8}),
            (
                "link_objects",
                {
                    "source_id": str(bogus_source),
                    "target_id": str(bogus_target),
                    "relation_type": "references",
                    "confidence": 0.9,
                },
            ),
        ]
    )

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    _set_assistant_runtime_override(provider)
    import app.services.assistant_service as assistant_service_module

    assistant_service_module.SessionLocal = lambda: _TestSession()

    plan_id = client.post("/assistant/message", json={"message": "stage fail"}).json()[
        "pending_action_plan"
    ]["id"]
    before = _task_count(db_session, user_id)
    response = client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert response.status_code == 409
    assert response.json()["status"] == PENDING_ACTION_PLAN_STATUS_FAILED
    assert _task_count(db_session, user_id) == before
    assert _reload_plan(db_session, uuid.UUID(plan_id)).status == PENDING_ACTION_PLAN_STATUS_FAILED


def test_second_approve_of_failed_plan_remains_failed(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    bogus_source = uuid.uuid4()
    bogus_target = uuid.uuid4()
    provider = _MultiMutationProvider(
        [
            ("create_task", {"title": "Stay failed", "confidence": 0.8}),
            (
                "link_objects",
                {
                    "source_id": str(bogus_source),
                    "target_id": str(bogus_target),
                    "relation_type": "references",
                    "confidence": 0.9,
                },
            ),
        ]
    )

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    _set_assistant_runtime_override(provider)
    import app.services.assistant_service as assistant_service_module

    assistant_service_module.SessionLocal = lambda: _TestSession()

    plan_id = client.post("/assistant/message", json={"message": "fail twice"}).json()[
        "pending_action_plan"
    ]["id"]
    first = client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert first.status_code == 409
    before = _task_count(db_session, user_id)
    second = client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert second.status_code == 409
    assert _task_count(db_session, user_id) == before
    assert _reload_plan(db_session, uuid.UUID(plan_id)).status == PENDING_ACTION_PLAN_STATUS_FAILED


def test_http_reject_expired_persists_expired_status(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    plan = PendingActionPlan(
        user_id=user_id,
        status=PENDING_ACTION_PLAN_STATUS_PENDING,
        actions=[
            {
                "tool_name": "create_task",
                "permission": "INTERNAL_WRITE",
                "arguments": {"title": "Expired reject", "confidence": 0.5},
            }
        ],
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(plan)
    db_session.flush()

    before = _task_count(db_session, user_id)
    response = client.post(f"/assistant/action-plans/{plan.id}/reject")
    assert response.status_code == 409
    assert response.json()["status"] == PENDING_ACTION_PLAN_STATUS_EXPIRED
    assert _task_count(db_session, user_id) == before
    assert _reload_plan(db_session, plan.id).status == PENDING_ACTION_PLAN_STATUS_EXPIRED


def test_approve_endpoint_ignores_replacement_arguments(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    provider = _MutationOnlyProvider(
        "create_task",
        {"title": "Frozen", "confidence": 0.77},
    )

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    _set_assistant_runtime_override(provider)
    import app.services.assistant_service as assistant_service_module

    assistant_service_module.SessionLocal = lambda: _TestSession()

    plan_id = client.post("/assistant/message", json={"message": "freeze title"}).json()[
        "pending_action_plan"
    ]["id"]
    response = client.post(
        f"/assistant/action-plans/{plan_id}/approve",
        json={"title": "Changed", "arguments": {"title": "Changed"}},
    )
    assert response.status_code == 200
    tasks = db_session.scalars(
        select(Object).where(Object.user_id == user_id, Object.kind == "task")
    ).all()
    assert len(tasks) == 1
    assert tasks[0].title == "Frozen"


def _setup_test_session(db_session):
    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    import app.services.assistant_service as assistant_service_module

    assistant_service_module.SessionLocal = lambda: _TestSession()
    return _TestSession


def test_approved_create_task_creates_confirmed_task(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    provider = _MutationOnlyProvider(
        "create_task",
        {"title": "Confirmed task", "confidence": 0.77},
    )
    _setup_test_session(db_session)
    _set_assistant_runtime_override(provider)

    plan_id = client.post("/assistant/message", json={"message": "create"}).json()[
        "pending_action_plan"
    ]["id"]
    client.post(f"/assistant/action-plans/{plan_id}/approve")
    task = db_session.scalars(
        select(Object).where(Object.user_id == user_id, Object.kind == "task")
    ).one()
    assert task.state == CONFIRMED_STATE


def test_approved_link_objects_creates_confirmed_edge(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    graph = GraphService(db_session, user_id)
    source = graph.create_object(ObjectCreate(kind="note", title="Src", origin="user"))
    target = graph.create_object(ObjectCreate(kind="note", title="Dst", origin="user"))
    db_session.flush()

    provider = _MutationOnlyProvider(
        "link_objects",
        {
            "source_id": str(source.id),
            "target_id": str(target.id),
            "relation_type": "references",
            "confidence": 0.9,
        },
    )
    _setup_test_session(db_session)
    _set_assistant_runtime_override(provider)

    plan_id = client.post("/assistant/message", json={"message": "link"}).json()[
        "pending_action_plan"
    ]["id"]
    client.post(f"/assistant/action-plans/{plan_id}/approve")
    edge = db_session.scalars(select(Edge).where(Edge.user_id == user_id)).one()
    assert edge.state == CONFIRMED_STATE


def test_approved_task_evidence_edges_are_confirmed(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    graph = GraphService(db_session, user_id)
    evidence = graph.create_object(ObjectCreate(kind="note", title="Mail", origin="user"))
    db_session.flush()
    evidence_id = str(evidence.id)

    plan = PendingActionPlan(
        user_id=user_id,
        status=PENDING_ACTION_PLAN_STATUS_PENDING,
        actions=[
            {
                "tool_name": "create_task",
                "permission": "INTERNAL_WRITE",
                "arguments": {
                    "title": "With evidence",
                    "confidence": 0.8,
                    "evidence_object_ids": [evidence_id],
                },
            }
        ],
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db_session.add(plan)
    db_session.flush()

    client.post(f"/assistant/action-plans/{plan.id}/approve")
    edge = db_session.scalars(
        select(Edge).where(Edge.user_id == user_id, Edge.type == "references")
    ).one()
    assert edge.state == CONFIRMED_STATE


def test_baseline_agent_create_task_still_proposed(
    db_session, fake_embedding_service, action_plan_user
):
    tools = DomainToolService(db_session, action_plan_user, fake_embedding_service)
    gateway = ToolExecutionGateway()
    result = gateway.execute(
        tools,
        "create_task",
        {"title": "Baseline proposed", "confidence": 0.8},
        context=ExecutionContext.BASELINE,
    )
    assert result.success is True
    task = db_session.scalars(
        select(Object).where(
            Object.user_id == action_plan_user,
            Object.title == "Baseline proposed",
        )
    ).one()
    assert task.state == PROPOSED_STATE


def test_resume_pending_returns_409_without_provider(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, _ = action_plan_client
    provider = _ResumeTextOnlyProvider()
    _setup_test_session(db_session)
    _set_assistant_runtime_override(provider)

    plan_id = client.post("/assistant/message", json={"message": "create"}).json()[
        "pending_action_plan"
    ]["id"]
    response = client.post(f"/assistant/action-plans/{plan_id}/resume")
    assert response.status_code == 409
    assert provider.text_only_calls == 0


def test_resume_rejected_returns_409_without_provider(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, _ = action_plan_client
    provider = _ResumeTextOnlyProvider()
    _setup_test_session(db_session)
    _set_assistant_runtime_override(provider)

    plan_id = client.post("/assistant/message", json={"message": "create"}).json()[
        "pending_action_plan"
    ]["id"]
    client.post(f"/assistant/action-plans/{plan_id}/reject")
    response = client.post(f"/assistant/action-plans/{plan_id}/resume")
    assert response.status_code == 409
    assert provider.text_only_calls == 0


def test_resume_failed_returns_409_without_provider(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    bogus_source = uuid.uuid4()
    bogus_target = uuid.uuid4()
    provider = _MultiMutationProvider(
        [
            ("create_task", {"title": "Fail resume", "confidence": 0.8}),
            (
                "link_objects",
                {
                    "source_id": str(bogus_source),
                    "target_id": str(bogus_target),
                    "relation_type": "references",
                    "confidence": 0.9,
                },
            ),
        ]
    )
    _setup_test_session(db_session)
    _set_assistant_runtime_override(provider)

    plan_id = client.post("/assistant/message", json={"message": "fail"}).json()[
        "pending_action_plan"
    ]["id"]
    client.post(f"/assistant/action-plans/{plan_id}/approve")
    resume_provider = _ResumeTextOnlyProvider()
    _set_assistant_runtime_override(resume_provider)
    response = client.post(f"/assistant/action-plans/{plan_id}/resume")
    assert response.status_code == 409
    assert resume_provider.text_only_calls == 0


def test_resume_expired_returns_409_without_provider(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    plan = PendingActionPlan(
        user_id=user_id,
        status=PENDING_ACTION_PLAN_STATUS_EXPIRED,
        actions=[
            {
                "tool_name": "create_task",
                "permission": "INTERNAL_WRITE",
                "arguments": {"title": "Expired", "confidence": 0.5},
            }
        ],
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(plan)
    db_session.flush()

    resume_provider = _ResumeTextOnlyProvider()
    _set_assistant_runtime_override(resume_provider)
    response = client.post(f"/assistant/action-plans/{plan.id}/resume")
    assert response.status_code == 409
    assert resume_provider.text_only_calls == 0


def test_wrong_user_resume_returns_404(
    db_session, fake_embedding_service, action_plan_user, action_plan_client, issue_bearer
):
    client, _ = action_plan_client
    provider = _ResumeTextOnlyProvider()
    _setup_test_session(db_session)
    _set_assistant_runtime_override(provider)

    plan_id = client.post("/assistant/message", json={"message": "create"}).json()[
        "pending_action_plan"
    ]["id"]
    client.post(f"/assistant/action-plans/{plan_id}/approve")

    other_user = uuid.uuid4()
    db_session.add(User(id=other_user, display_name="other resume"))
    db_session.flush()
    other_bearer = issue_bearer(other_user)
    other_headers = {"Authorization": f"Bearer {other_bearer}"}

    resume_provider = _ResumeTextOnlyProvider()
    _set_assistant_runtime_override(resume_provider)
    with TestClient(app) as test_client:
        other_client = AuthTestClient(test_client, other_headers)
        response = other_client.post(f"/assistant/action-plans/{plan_id}/resume")
    assert response.status_code == 404
    assert resume_provider.text_only_calls == 0


def test_resume_executed_calls_text_only_provider_once(
    db_session, fake_embedding_service, action_plan_user, action_plan_client, monkeypatch
):
    client, _ = action_plan_client
    provider = _ResumeTextOnlyProvider()
    _setup_test_session(db_session)
    _override_assistant_provider(provider, monkeypatch)

    plan_id = client.post("/assistant/message", json={"message": "create"}).json()[
        "pending_action_plan"
    ]["id"]
    client.post(f"/assistant/action-plans/{plan_id}/approve")

    response = client.post(f"/assistant/action-plans/{plan_id}/resume")
    assert response.status_code == 200
    assert provider.text_only_calls == 1
    assert provider.run_calls == 1
    assert "Execution results" in (provider.last_finalize_context or "")


def test_resume_returns_deterministic_affected_objects(
    db_session, fake_embedding_service, action_plan_user, action_plan_client, monkeypatch
):
    client, user_id = action_plan_client
    provider = _ResumeTextOnlyProvider(answer="Done.")
    _setup_test_session(db_session)
    _override_assistant_provider(provider, monkeypatch)

    plan_id = client.post("/assistant/message", json={"message": "create"}).json()[
        "pending_action_plan"
    ]["id"]
    client.post(f"/assistant/action-plans/{plan_id}/approve")
    task = db_session.scalars(
        select(Object).where(Object.user_id == user_id, Object.kind == "task")
    ).one()

    response = client.post(f"/assistant/action-plans/{plan_id}/resume")
    body = response.json()
    assert body["answer"] == "Done."
    assert len(body["affected_objects"]) == 1
    assert body["affected_objects"][0]["object_id"] == str(task.id)
    assert body["affected_objects"][0]["state"] == CONFIRMED_STATE


def test_resume_provider_failure_returns_502_plan_stays_executed(
    db_session, fake_embedding_service, action_plan_user, action_plan_client, monkeypatch
):
    client, user_id = action_plan_client
    stage_provider = _ResumeTextOnlyProvider()
    _setup_test_session(db_session)
    _override_assistant_provider(stage_provider, monkeypatch)

    message_response = client.post("/assistant/message", json={"message": "create"})
    plan_id = message_response.json()["pending_action_plan"]["id"]
    approve_response = client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == PENDING_ACTION_PLAN_STATUS_EXECUTED

    fail_provider = _FailingTextOnlyProvider()
    _override_assistant_provider(fail_provider, monkeypatch)
    response = client.post(f"/assistant/action-plans/{plan_id}/resume")
    assert response.status_code == 502
    assert approve_response.json()["status"] == PENDING_ACTION_PLAN_STATUS_EXECUTED
    assert approve_response.json()["result"] is not None
    assert fail_provider.text_only_calls == 1


def test_resume_pending_without_openai_config_returns_409_provider_not_constructed(
    db_session,
    fake_embedding_service,
    action_plan_user,
    action_plan_client,
    monkeypatch,
):
    provider_constructed = False

    def track_create():
        nonlocal provider_constructed
        provider_constructed = True
        raise AssertionError("provider should not be constructed")

    monkeypatch.setattr("app.api.assistant.build_assistant_runtime", track_create)

    client, user_id = action_plan_client
    plan = PendingActionPlan(
        user_id=user_id,
        status=PENDING_ACTION_PLAN_STATUS_PENDING,
        actions=[
            {
                "tool_name": "create_task",
                "permission": "INTERNAL_WRITE",
                "arguments": {"title": "Pending resume", "confidence": 0.5},
            }
        ],
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db_session.add(plan)
    db_session.flush()

    response = client.post(f"/assistant/action-plans/{plan.id}/resume")
    assert response.status_code == 409
    assert provider_constructed is False


def test_resume_wrong_user_without_openai_config_returns_404_provider_not_constructed(
    db_session,
    fake_embedding_service,
    action_plan_user,
    action_plan_client,
    issue_bearer,
    monkeypatch,
):
    provider_constructed = False

    def track_create():
        nonlocal provider_constructed
        provider_constructed = True
        raise AssertionError("provider should not be constructed")

    monkeypatch.setattr("app.api.assistant.build_assistant_runtime", track_create)

    client, user_id = action_plan_client
    executed = PendingActionPlan(
        user_id=user_id,
        status=PENDING_ACTION_PLAN_STATUS_EXECUTED,
        actions=[
            {
                "tool_name": "create_task",
                "permission": "INTERNAL_WRITE",
                "arguments": {"title": "Done", "confidence": 0.5},
            }
        ],
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        result={"actions": []},
    )
    db_session.add(executed)
    db_session.flush()

    other_user = uuid.uuid4()
    db_session.add(User(id=other_user, display_name="other"))
    db_session.flush()
    other_headers = {"Authorization": f"Bearer {issue_bearer(other_user)}"}

    with TestClient(app) as test_client:
        other_client = AuthTestClient(test_client, other_headers)
        response = other_client.post(f"/assistant/action-plans/{executed.id}/resume")
    assert response.status_code == 404
    assert provider_constructed is False


def test_finalization_context_is_bounded():
    from app.assistant.constants import MAX_ACTION_PLAN_FINALIZATION_CONTEXT_CHARS
    from app.services.action_plan_service import PendingActionPlanView
    from app.services.assistant_service import _build_action_plan_finalization_context

    huge_title = "x" * (MAX_ACTION_PLAN_FINALIZATION_CONTEXT_CHARS + 500)
    plan = PendingActionPlanView(
        id=uuid.uuid4(),
        status=PENDING_ACTION_PLAN_STATUS_EXECUTED,
        expires_at=datetime.now(UTC),
        actions=[
            {
                "tool_name": "create_task",
                "arguments": {"title": huge_title, "confidence": 0.5},
            }
        ],
        result={"actions": [{"tool_name": "create_task", "success": True, "output": {}}]},
    )
    context = _build_action_plan_finalization_context(plan)
    assert len(context) <= MAX_ACTION_PLAN_FINALIZATION_CONTEXT_CHARS


def test_finalization_context_preserves_execution_results_under_truncation():
    from app.assistant.constants import MAX_ACTION_PLAN_FINALIZATION_CONTEXT_CHARS
    from app.services.action_plan_service import PendingActionPlanView
    from app.services.assistant_service import _build_action_plan_finalization_context

    task_id = str(uuid.uuid4())
    huge_title = "z" * (MAX_ACTION_PLAN_FINALIZATION_CONTEXT_CHARS + 500)
    plan = PendingActionPlanView(
        id=uuid.uuid4(),
        status=PENDING_ACTION_PLAN_STATUS_EXECUTED,
        expires_at=datetime.now(UTC),
        actions=[
            {
                "tool_name": "create_task",
                "arguments": {"title": huge_title, "body": huge_title, "confidence": 0.5},
            }
        ],
        result={
            "actions": [
                {
                    "tool_name": "create_task",
                    "success": True,
                    "output": {
                        "object": {
                            "id": task_id,
                            "title": "Surviving task",
                            "kind": "task",
                            "state": CONFIRMED_STATE,
                        }
                    },
                }
            ]
        },
    )
    context = _build_action_plan_finalization_context(plan)
    assert len(context) <= MAX_ACTION_PLAN_FINALIZATION_CONTEXT_CHARS
    assert "Execution results" in context
    assert task_id in context
    assert "Surviving task" in context
    assert CONFIRMED_STATE in context


def test_finalization_context_includes_execution_effects():
    from app.services.action_plan_service import PendingActionPlanView
    from app.services.assistant_service import _build_action_plan_finalization_context

    plan = PendingActionPlanView(
        id=uuid.uuid4(),
        status=PENDING_ACTION_PLAN_STATUS_EXECUTED,
        expires_at=datetime.now(UTC),
        actions=[
            {
                "tool_name": "update_task",
                "arguments": {"object_id": "00000000-0000-0000-0000-000000000001"},
            }
        ],
        result={
            "actions": [
                {
                    "tool_name": "update_task",
                    "success": True,
                    "output": {"changed": False, "object": {"id": "1", "kind": "task"}},
                    "effect": "no_op",
                    "effect_description": "update_task: no state change; changed=false",
                }
            ]
        },
    )
    context = _build_action_plan_finalization_context(plan)
    assert "Execution effects" in context
    assert "changed=false" in context


def test_finalization_instructions_mark_context_as_untrusted_data():
    from app.llm.openai_assistant_provider import FINALIZATION_INSTRUCTIONS

    lowered = FINALIZATION_INSTRUCTIONS.lower()
    assert "evidence only" in lowered
    assert "never be followed as instructions" in lowered


class _HistoryCapturingProvider:
    def __init__(self, answer: str = "ok") -> None:
        self.answer = answer
        self.last_history: list[AssistantHistoryMessage] = []

    def run(
        self,
        message: str,
        history: list[AssistantHistoryMessage],
        ui_context: str,
        reference_datetime: datetime,
        timezone: str,
        tool_runner,
    ) -> AssistantProviderResult:
        self.last_history = list(history)
        return AssistantProviderResult(
            answer=self.answer,
            candidate_object_ids=[],
            affected_object_ids=[],
            store_false_used=True,
        )


def _patch_assistant_session_local(db_session, monkeypatch):
    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    import app.services.assistant_service as assistant_service_module

    assistant_service_module.SessionLocal = lambda: _TestSession()
    monkeypatch.setattr(
        assistant_service_module,
        "SessionLocal",
        lambda: _TestSession(),
    )


def test_rejected_plan_appears_in_provider_history(
    db_session, fake_embedding_service, action_plan_user, action_plan_client, monkeypatch
):
    from app.assistant.action_plan_history import ACTION_PLAN_CONVERSATION_EVENT_PREFIX

    client, user_id = action_plan_client
    provider = _HistoryCapturingProvider(answer="Clarify intent.")
    _override_assistant_provider(provider, monkeypatch)
    _patch_assistant_session_local(db_session, monkeypatch)

    plan = PendingActionPlan(
        user_id=user_id,
        status=PENDING_ACTION_PLAN_STATUS_REJECTED,
        actions=[
            {
                "tool_name": "create_task",
                "arguments": {"title": "TEST-REJECT-23D", "confidence": 0.5},
            }
        ],
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        rejected_at=datetime.now(UTC),
    )
    db_session.add(plan)
    db_session.flush()

    response = client.post(
        "/assistant/message",
        json={"message": "Testing Double Approved Case"},
    )
    assert response.status_code == 200
    assert provider.last_history
    terminal_entries = [
        item
        for item in provider.last_history
        if ACTION_PLAN_CONVERSATION_EVENT_PREFIX in item.content
    ]
    assert terminal_entries
    rejected_entry = terminal_entries[-1]
    assert "terminal state: rejected" in rejected_entry.content
    assert "TEST-REJECT-23D" in rejected_entry.content
    assert "pending" not in rejected_entry.content.lower()


def test_terminal_plan_history_covers_executed_expired_failed(
    db_session, fake_embedding_service, action_plan_user, action_plan_client, monkeypatch
):
    from app.assistant.action_plan_history import ACTION_PLAN_CONVERSATION_EVENT_PREFIX

    client, user_id = action_plan_client
    provider = _HistoryCapturingProvider(answer="ok")
    _override_assistant_provider(provider, monkeypatch)
    _patch_assistant_session_local(db_session, monkeypatch)

    db_session.add_all(
        [
            PendingActionPlan(
                user_id=user_id,
                status=PENDING_ACTION_PLAN_STATUS_EXECUTED,
                actions=[
                    {
                        "tool_name": "create_task",
                        "arguments": {"title": "DONE-23D", "confidence": 0.5},
                    }
                ],
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
                executed_at=datetime.now(UTC),
                result={"actions": []},
            ),
            PendingActionPlan(
                user_id=user_id,
                status=PENDING_ACTION_PLAN_STATUS_EXPIRED,
                actions=[
                    {
                        "tool_name": "create_task",
                        "arguments": {"title": "EXPIRED-23D", "confidence": 0.5},
                    }
                ],
                expires_at=datetime.now(UTC) - timedelta(minutes=5),
                failure="action plan expired",
            ),
            PendingActionPlan(
                user_id=user_id,
                status=PENDING_ACTION_PLAN_STATUS_FAILED,
                actions=[
                    {
                        "tool_name": "create_task",
                        "arguments": {"title": "FAILED-23D", "confidence": 0.5},
                    }
                ],
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
                failure="boom",
            ),
        ]
    )
    db_session.flush()

    response = client.post("/assistant/message", json={"message": "ambiguous"})
    assert response.status_code == 200
    terminal_text = "\n".join(
        item.content
        for item in provider.last_history
        if ACTION_PLAN_CONVERSATION_EVENT_PREFIX in item.content
    )
    assert "terminal state: executed" in terminal_text
    assert "DONE-23D" in terminal_text
    assert "terminal state: expired" in terminal_text
    assert "EXPIRED-23D" in terminal_text
    assert "terminal state: failed" in terminal_text
    assert "FAILED-23D" in terminal_text


def _bind_action_plan_test_session(db_session) -> None:
    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    import app.assistant.session as assistant_session_module
    import app.services.assistant_service as assistant_service_module

    test_session_factory = lambda: _TestSession()
    assistant_service_module.SessionLocal = test_session_factory
    assistant_session_module.SessionLocal = test_session_factory


def _create_confirmed_task_for_user(
    db_session,
    user_id: uuid.UUID,
    title: str = "Original",
    body: str = "Keep body",
    due_at: datetime | None = None,
    status: str | None = "open",
) -> Object:
    graph = GraphService(db_session, user_id)
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            body=body,
            origin="user",
            state=CONFIRMED_STATE,
            status=status,
            due_at=due_at,
        )
    )


def test_frozen_update_task_rename_preserves_omitted_fields(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    due_at = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
    task = _create_confirmed_task_for_user(
        db_session,
        user_id,
        due_at=due_at,
    )
    provider = _MutationOnlyProvider(
        "update_task",
        {"object_id": str(task.id), "title": "Renamed"},
    )
    _set_assistant_runtime_override(provider)
    _bind_action_plan_test_session(db_session)

    message_response = client.post(
        "/assistant/message",
        json={"message": "rename", "context_object_id": str(task.id)},
    )
    plan = message_response.json()["pending_action_plan"]
    frozen = plan["actions"][0]["arguments"]
    assert frozen == {"object_id": str(task.id), "title": "Renamed"}
    assert "body" not in frozen
    assert "due_at" not in frozen

    approve = client.post(f"/assistant/action-plans/{plan['id']}/approve")
    assert approve.status_code == 200
    db_session.expire_all()
    updated = db_session.get(Object, task.id)
    assert updated.title == "Renamed"
    assert updated.body == "Keep body"
    assert updated.due_at == due_at


def test_frozen_update_task_clear_body_preserves_other_fields(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    due_at = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
    task = _create_confirmed_task_for_user(
        db_session,
        user_id,
        title="Stable title",
        due_at=due_at,
    )
    provider = _MutationOnlyProvider(
        "update_task",
        {"object_id": str(task.id), "body": None},
    )
    _set_assistant_runtime_override(provider)
    _bind_action_plan_test_session(db_session)

    message_response = client.post(
        "/assistant/message",
        json={"message": "clear body", "context_object_id": str(task.id)},
    )
    plan = message_response.json()["pending_action_plan"]
    frozen = plan["actions"][0]["arguments"]
    assert frozen == {"object_id": str(task.id), "body": None}
    assert "title" not in frozen
    assert "due_at" not in frozen

    approve = client.post(f"/assistant/action-plans/{plan['id']}/approve")
    assert approve.status_code == 200
    db_session.expire_all()
    updated = db_session.get(Object, task.id)
    assert updated.body is None
    assert updated.title == "Stable title"
    assert updated.due_at == due_at


def test_frozen_update_task_clear_due_at_preserves_other_fields(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    due_at = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
    task = _create_confirmed_task_for_user(
        db_session,
        user_id,
        body="Stable body",
        due_at=due_at,
    )
    provider = _MutationOnlyProvider(
        "update_task",
        {"object_id": str(task.id), "due_at": None},
    )
    _set_assistant_runtime_override(provider)
    _bind_action_plan_test_session(db_session)

    message_response = client.post(
        "/assistant/message",
        json={"message": "clear due", "context_object_id": str(task.id)},
    )
    plan = message_response.json()["pending_action_plan"]
    frozen = plan["actions"][0]["arguments"]
    assert frozen == {"object_id": str(task.id), "due_at": None}
    assert "title" not in frozen
    assert "body" not in frozen

    approve = client.post(f"/assistant/action-plans/{plan['id']}/approve")
    assert approve.status_code == 200
    db_session.expire_all()
    updated = db_session.get(Object, task.id)
    assert updated.due_at is None
    assert updated.title == "Original"
    assert updated.body == "Stable body"


def test_invalid_update_title_null_not_staged(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    task = _create_confirmed_task_for_user(db_session, user_id)
    provider = _MutationOnlyProvider(
        "update_task",
        {"object_id": str(task.id), "title": None},
    )
    _set_assistant_runtime_override(provider)
    _bind_action_plan_test_session(db_session)

    response = client.post(
        "/assistant/message",
        json={"message": "bad title", "context_object_id": str(task.id)},
    )
    assert response.status_code == 200
    assert response.json()["pending_action_plan"] is None


def test_set_task_status_reject_then_approve_lifecycle(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    task = _create_confirmed_task_for_user(db_session, user_id, status="open")
    provider = _MutationOnlyProvider(
        "set_task_status",
        {"object_id": str(task.id), "status": "done"},
    )
    _set_assistant_runtime_override(provider)
    _bind_action_plan_test_session(db_session)

    plan_id = client.post(
        "/assistant/message",
        json={"message": "complete", "context_object_id": str(task.id)},
    ).json()["pending_action_plan"]["id"]
    db_session.expire_all()
    assert db_session.get(Object, task.id).status == "open"

    reject = client.post(f"/assistant/action-plans/{plan_id}/reject")
    assert reject.status_code == 200
    db_session.expire_all()
    assert db_session.get(Object, task.id).status == "open"

    plan_id = client.post(
        "/assistant/message",
        json={"message": "complete again", "context_object_id": str(task.id)},
    ).json()["pending_action_plan"]["id"]
    approve = client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert approve.status_code == 200
    db_session.expire_all()
    assert db_session.get(Object, task.id).status == "done"

    second = client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert second.status_code == 200
    db_session.expire_all()
    assert db_session.get(Object, task.id).status == "done"


def test_delete_task_reject_and_approve_lifecycle(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, user_id = action_plan_client
    task = _create_confirmed_task_for_user(db_session, user_id, status="open")
    evidence = _create_confirmed_task_for_user(db_session, user_id, title="Evidence")
    graph = GraphService(db_session, user_id)
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=evidence.id,
            type="references",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    provider = _MutationOnlyProvider(
        "delete_task",
        {"object_id": str(task.id)},
    )
    _set_assistant_runtime_override(provider)
    _bind_action_plan_test_session(db_session)

    plan_id = client.post(
        "/assistant/message",
        json={"message": "delete", "context_object_id": str(task.id)},
    ).json()["pending_action_plan"]["id"]
    db_session.expire_all()
    assert db_session.get(Object, task.id).status == "open"
    edge_count = db_session.scalar(
        select(func.count()).select_from(Edge).where(Edge.source_id == task.id)
    )
    assert edge_count == 1

    reject = client.post(f"/assistant/action-plans/{plan_id}/reject")
    assert reject.status_code == 200
    db_session.expire_all()
    assert db_session.get(Object, task.id).status == "open"

    plan_id = client.post(
        "/assistant/message",
        json={"message": "delete again", "context_object_id": str(task.id)},
    ).json()["pending_action_plan"]["id"]
    approve = client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert approve.status_code == 200
    db_session.expire_all()
    deleted = db_session.get(Object, task.id)
    assert deleted is not None
    assert deleted.status == "deleted"
    edge_count = db_session.scalar(
        select(func.count()).select_from(Edge).where(Edge.source_id == task.id)
    )
    assert edge_count == 1

    second = client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert second.status_code == 200
    db_session.expire_all()
    assert db_session.get(Object, task.id).status == "deleted"
