"""PHASE 22.6 — model-round evidence provenance (pending vs committed seen IDs)."""

import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

from app.api.schemas import ObjectCreate
from app.assistant.tool_runner import BoundAssistantToolRunner, PerTurnToolBudget
from app.db.models import Edge, Object
from app.llm.openai_assistant_provider import OpenAIAssistantProvider
from app.services.domain_tool_service import DomainToolService
from app.services.graph_service import GraphService
from app.tools.executor import DEFAULT_MAX_TOOL_CALLS, ToolExecutionResult, _dispatch
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import ToolError
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture(autouse=True)
def patch_assistant_tool_session(db_session, fake_embedding_service, monkeypatch):
    from app.assistant.tool_args import normalize_assistant_tool_arguments

    def _run(user_id, tool_name, arguments):
        try:
            normalized_arguments = normalize_assistant_tool_arguments(tool_name, arguments)
        except ToolError as exc:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error=exc.message,
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        nested = db_session.begin_nested()
        tools = DomainToolService(
            db_session,
            user_id,
            fake_embedding_service,
            defer_write_embeddings=True,
        )
        try:
            output = _dispatch(tools, tool_name, normalized_arguments)
            nested.commit()
            return ToolExecutionResult(
                success=True,
                tool_name=tool_name,
                output=output.model_dump(mode="json"),
            )
        except ToolError as exc:
            nested.rollback()
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error=exc.message,
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        except Exception as exc:  # noqa: BLE001
            nested.rollback()
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error=f"tool execution failed: {type(exc).__name__}",
                status=ToolExecutionStatus.EXECUTION_FAILED,
            )

    monkeypatch.setattr("app.assistant.session.run_assistant_tool", _run)

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    monkeypatch.setattr(
        "app.services.assistant_service.SessionLocal",
        lambda: _TestSession(),
    )


def _create_evidence_email(graph: GraphService, title: str) -> Object:
    return graph.create_object(
        ObjectCreate(
            kind="email",
            title=title,
            body="evidence body",
            origin="source",
            provider="gmail",
        )
    )


def test_same_model_response_read_then_write_rejects_evidence(
    db_session, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    evidence = _create_evidence_email(graph, "MODEL_ROUND_EVIDENCE_B")
    db_session.flush()

    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, BOOTSTRAP_USER_ID)

    context_result = runner(
        "get_context",
        {"object_id": str(evidence.id), "max_chars": 2000},
    )
    assert context_result.success
    assert evidence.id in budget.pending_seen_object_ids
    assert evidence.id not in budget.seen_object_ids

    create_result = runner(
        "create_task",
        {
            "title": "Same-round blocked task",
            "confidence": 0.7,
            "evidence_object_ids": [str(evidence.id)],
        },
    )
    assert not create_result.success
    assert create_result.error == "evidence object was not exposed in this Assistant turn"

    task_count = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(Object.kind == "task", Object.title == "Same-round blocked task")
    )
    assert task_count == 0


def test_next_model_round_after_commit_allows_evidence(
    db_session, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    evidence = _create_evidence_email(graph, "MODEL_ROUND_COMMIT_EVIDENCE_B")
    db_session.flush()

    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, BOOTSTRAP_USER_ID)

    context_result = runner(
        "get_context",
        {"object_id": str(evidence.id), "max_chars": 2000},
    )
    assert context_result.success
    runner.commit_model_visible_outputs()
    assert evidence.id in budget.seen_object_ids
    assert evidence.id not in budget.pending_seen_object_ids

    create_result = runner(
        "create_task",
        {
            "title": "Next-round evidence task",
            "confidence": 0.72,
            "evidence_object_ids": [str(evidence.id)],
        },
    )
    assert create_result.success
    task_id = create_result.output["object"]["id"]
    edge = db_session.scalar(
        select(Edge).where(
            Edge.source_id == task_id,
            Edge.target_id == evidence.id,
            Edge.type == "references",
        )
    )
    assert edge is not None


def test_ui_context_seed_allows_evidence_in_first_model_round(
    db_session, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    context_event = graph.create_object(
        ObjectCreate(
            kind="event",
            title="UI round-one context event",
            body="context",
            origin="source",
            provider="google_calendar",
        )
    )
    db_session.flush()

    budget = PerTurnToolBudget(initial_seen_object_ids=[context_event.id])
    runner = BoundAssistantToolRunner(budget, BOOTSTRAP_USER_ID)

    create_result = runner(
        "create_task",
        {
            "title": "UI-seeded evidence task",
            "confidence": 0.7,
            "evidence_object_ids": [str(context_event.id)],
        },
    )
    assert create_result.success


def test_openai_provider_two_round_flow_commits_between_responses(
    monkeypatch, db_session, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    evidence = _create_evidence_email(graph, "OPENAI_TWO_ROUND_EVIDENCE_B")
    db_session.flush()
    create_rounds: list[int] = []

    class FakeResponses:
        def __init__(self) -> None:
            self._round = 0

        def create(self, **kwargs):
            input_items = kwargs.get("input", [])
            tool_output_count = sum(
                1
                for item in input_items
                if isinstance(item, dict) and item.get("type") == "function_call_output"
            )
            response = MagicMock()
            if tool_output_count == 0:
                function_call = MagicMock()
                function_call.type = "function_call"
                function_call.name = "get_context"
                function_call.call_id = "call-context-round-1"
                function_call.arguments = json.dumps({"object_id": str(evidence.id)})
                response.output = [function_call]
                response.output_text = None
            elif tool_output_count == 1:
                create_rounds.append(1)
                function_call = MagicMock()
                function_call.type = "function_call"
                function_call.name = "create_task"
                function_call.call_id = "call-create-round-2"
                function_call.arguments = json.dumps(
                    {
                        "title": "OpenAI two-round task",
                        "confidence": 0.75,
                        "evidence_object_ids": [str(evidence.id)],
                    }
                )
                response.output = [function_call]
                response.output_text = None
            else:
                response.output = []
                response.output_text = "Создал задачу с evidence."
            return response

    class FakeClient:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))

    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, BOOTSTRAP_USER_ID)
    provider = OpenAIAssistantProvider(api_key="test", model="gpt-test")
    result = provider.run(
        message="Собери задачу по этому письму",
        history=[],
        ui_context="",
        reference_datetime=__import__("datetime").datetime.now(__import__("datetime").UTC),
        timezone="Europe/Amsterdam",
        tool_runner=runner,
    )

    assert result.answer
    assert len(create_rounds) == 1
    assert budget.calls_made <= DEFAULT_MAX_TOOL_CALLS
    task = db_session.scalar(
        select(Object).where(Object.title == "OpenAI two-round task")
    )
    assert task is not None
    edge = db_session.scalar(
        select(Edge).where(
            Edge.source_id == task.id,
            Edge.target_id == evidence.id,
            Edge.type == "references",
        )
    )
    assert edge is not None


def test_openai_provider_same_response_parallel_calls_block_evidence_write(
    monkeypatch, db_session, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    evidence = _create_evidence_email(graph, "OPENAI_PARALLEL_EVIDENCE_B")
    db_session.flush()

    class FakeResponses:
        def create(self, **kwargs):
            input_items = kwargs.get("input", [])
            tool_output_count = sum(
                1
                for item in input_items
                if isinstance(item, dict) and item.get("type") == "function_call_output"
            )
            response = MagicMock()
            if tool_output_count >= 2:
                response.output = []
                response.output_text = "done"
                return response
            context_call = MagicMock()
            context_call.type = "function_call"
            context_call.name = "get_context"
            context_call.call_id = "call-context-parallel"
            context_call.arguments = json.dumps({"object_id": str(evidence.id)})
            create_call = MagicMock()
            create_call.type = "function_call"
            create_call.name = "create_task"
            create_call.call_id = "call-create-parallel"
            create_call.arguments = json.dumps(
                {
                    "title": "Parallel blocked task",
                    "confidence": 0.7,
                    "evidence_object_ids": [str(evidence.id)],
                }
            )
            response.output = [context_call, create_call]
            response.output_text = None
            return response

    class FakeClient:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))

    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, BOOTSTRAP_USER_ID)
    provider = OpenAIAssistantProvider(api_key="test", model="gpt-test")
    provider.run(
        message="test",
        history=[],
        ui_context="",
        reference_datetime=__import__("datetime").datetime.now(__import__("datetime").UTC),
        timezone="Europe/Amsterdam",
        tool_runner=runner,
    )

    task_count = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(Object.kind == "task", Object.title == "Parallel blocked task")
    )
    assert task_count == 0
