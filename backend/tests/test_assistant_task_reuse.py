"""PHASE 22.6 — Assistant task reuse and explicit duplicate creation."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

from app.api.schemas import ObjectCreate
from app.assistant.tool_args import normalize_assistant_tool_arguments
from app.db.models import Object
from app.llm.openai_assistant_provider import OpenAIAssistantProvider
from app.services.assistant_service import AssistantService
from app.services.domain_tool_service import DomainToolService
from app.services.graph_service import GraphService
from app.services.provenance import AGENT_ORIGIN, PROPOSED_STATE
from app.tools.executor import DEFAULT_MAX_TOOL_CALLS, ToolExecutionResult, _dispatch
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import ToolError
from app.users.bootstrap import BOOTSTRAP_USER_ID

EXISTING_TASK_TITLE = "Подготовить и провести семинары ADC и DQF для Норникеля"


@pytest.fixture
def reuse_user_id(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    from app.db.models import User

    db_session.add(User(id=user_id, display_name="Task reuse test user"))
    db_session.flush()
    return user_id


@pytest.fixture(autouse=True)
def assistant_tool_env(db_session, fake_embedding_service, monkeypatch):
    trace = {"tool_names": []}

    def _run(user_id, tool_name, arguments):
        trace["tool_names"].append(tool_name)
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
    monkeypatch.setattr("app.services.assistant_service.run_assistant_tool", _run)

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
    yield trace


def _seed_reuse_fixture(
    db_session, fake_embedding_service, user_id: uuid.UUID
) -> dict[str, Object]:
    now = datetime.now(UTC)
    graph = GraphService(db_session, user_id, fake_embedding_service)
    event = graph.create_object(
        ObjectCreate(
            kind="event",
            title="Вопрос по Норникелю",
            body="Обсуждение активности",
            origin="source",
            provider="google_calendar",
        )
    )
    event.occurred_at = now - timedelta(days=3)
    email = graph.create_object(
        ObjectCreate(
            kind="email",
            title="Fwd: Обучающий семинар ADC DQF Норникель",
            body="Семинар ADC",
            origin="source",
            provider="gmail",
        )
    )
    email.occurred_at = now - timedelta(days=2)
    existing_task = graph.create_object(
        ObjectCreate(
            kind="task",
            title=EXISTING_TASK_TITLE,
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.75,
        )
    )
    graph.create_object(
        ObjectCreate(
            kind="task",
            title="Тестовая задача из Linux клиента",
            body="linux noise",
            origin="user",
        )
    )
    for index in range(8):
        graph.create_object(
            ObjectCreate(
                kind="email",
                title=f"Server status newsletter {index}",
                body="automated server monitoring message",
                origin="source",
                provider="gmail",
            )
        )
    db_session.flush()
    return {"event": event, "email": email, "existing_task": existing_task}


def test_retrieve_tool_output_includes_task_state(db_session, fake_embedding_service) -> None:
    from app.assistant.tool_output import serialize_tool_output_for_model

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Retrieve state exposure task",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            status="pending",
            confidence=0.7,
        )
    )
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    output = tools.retrieve(
        __import__("app.tools.schemas", fromlist=["RetrieveInput"]).RetrieveInput(
            query="Retrieve state exposure",
            kind="task",
            limit=5,
        )
    )
    serialized = serialize_tool_output_for_model(
        "retrieve",
        output.model_dump(mode="json"),
    )
    hit = next(h for h in serialized["hits"] if h["object_id"] == str(task.id))
    assert hit["state"] == PROPOSED_STATE
    assert hit["status"] == "pending"


def test_assistant_reuse_existing_task_no_create(
    monkeypatch, db_session, fake_embedding_service, assistant_tool_env, reuse_user_id
) -> None:
    fixture = _seed_reuse_fixture(db_session, fake_embedding_service, reuse_user_id)
    event = fixture["event"]
    existing_task = fixture["existing_task"]
    task_count_before = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(Object.kind == "task", Object.user_id == reuse_user_id)
    )

    tool_names = assistant_tool_env["tool_names"]

    class FakeResponses:
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
                function_call.name = "retrieve"
                function_call.call_id = "call-evidence"
                function_call.arguments = '{"query":"норникель","limit":5}'
                response.output = [function_call]
            elif tool_output_count == 1:
                function_call = MagicMock()
                function_call.type = "function_call"
                function_call.name = "get_context"
                function_call.call_id = "call-context"
                function_call.arguments = json.dumps({"object_id": str(event.id)})
                response.output = [function_call]
            elif tool_output_count == 2:
                function_call = MagicMock()
                function_call.type = "function_call"
                function_call.name = "retrieve"
                function_call.call_id = "call-task-dup"
                function_call.arguments = (
                    '{"query":"норникель семинар","kind":"task",'
                    '"time_scope":"all","limit":3}'
                )
                response.output = [function_call]
            else:
                response.output = []
                response.output_text = (
                    "Похожая задача уже существует: «"
                    + EXISTING_TASK_TITLE
                    + "». Использовать её? Если нужна отдельная, скажите «создай новую»."
                )
            response.output_text = getattr(response, "output_text", None)
            return response

    class FakeClient:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))

    provider = OpenAIAssistantProvider(api_key="test", model="gpt-test")
    service = AssistantService(reuse_user_id, provider)
    result = service.send_message(
        message="Посмотри, что есть по курсам Норникеля и собери задачу",
        history=[],
    )

    provider_tool_names = [
        name for name in tool_names if name in ("retrieve", "get_context", "create_task", "update_task")
    ]
    assert "create_task" not in provider_tool_names
    assert len(provider_tool_names) <= DEFAULT_MAX_TOOL_CALLS
    task_count_after = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(Object.kind == "task", Object.user_id == reuse_user_id)
    )
    assert task_count_after == task_count_before
    assert not result.affected_objects
    ref_ids = {ref.object_id for ref in result.references}
    assert existing_task.id in ref_ids
    ref_titles = {ref.title for ref in result.references}
    assert EXISTING_TASK_TITLE in ref_titles
    assert "Тестовая задача из Linux клиента" not in ref_titles
    assert "уже" in result.answer.lower() or "существует" in result.answer.lower()


def test_assistant_explicit_new_task_creates_duplicate(
    monkeypatch, db_session, fake_embedding_service, assistant_tool_env, reuse_user_id
) -> None:
    fixture = _seed_reuse_fixture(db_session, fake_embedding_service, reuse_user_id)
    event = fixture["event"]
    existing_task = fixture["existing_task"]
    task_count_before = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(Object.kind == "task", Object.user_id == reuse_user_id)
    )

    tool_names = assistant_tool_env["tool_names"]

    class FakeResponses:
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
                function_call.name = "retrieve"
                function_call.call_id = "call-evidence-2"
                function_call.arguments = '{"query":"норникель","limit":5}'
                response.output = [function_call]
            elif tool_output_count == 1:
                function_call = MagicMock()
                function_call.type = "function_call"
                function_call.name = "get_context"
                function_call.call_id = "call-context-2"
                function_call.arguments = json.dumps({"object_id": str(event.id)})
                response.output = [function_call]
            elif tool_output_count == 2:
                function_call = MagicMock()
                function_call.type = "function_call"
                function_call.name = "retrieve"
                function_call.call_id = "call-task-dup-2"
                function_call.arguments = (
                    '{"query":"норникель семинар","kind":"task",'
                    '"time_scope":"all","limit":3}'
                )
                response.output = [function_call]
            elif tool_output_count == 3:
                function_call = MagicMock()
                function_call.type = "function_call"
                function_call.name = "create_task"
                function_call.call_id = "call-create-new"
                function_call.arguments = json.dumps(
                    {
                        "title": "Отдельная задача по Норникелю",
                        "confidence": 0.75,
                        "evidence_object_ids": [str(event.id)],
                    }
                )
                response.output = [function_call]
            else:
                response.output = []
                response.output_text = "Создал предложение отдельной задачи."
            response.output_text = getattr(response, "output_text", None)
            return response

    class FakeClient:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))

    provider = OpenAIAssistantProvider(api_key="test", model="gpt-test")
    service = AssistantService(reuse_user_id, provider)
    result = service.send_message(
        message="Нет, создай новую отдельную задачу по курсам Норникеля",
        history=[],
    )

    provider_tool_names = [
        name for name in tool_names if name in ("retrieve", "get_context", "create_task", "update_task")
    ]
    assert "create_task" in provider_tool_names
    task_count_after = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(Object.kind == "task", Object.user_id == reuse_user_id)
    )
    assert task_count_after == task_count_before + 1
    untouched = db_session.get(Object, existing_task.id)
    assert untouched is not None
    assert untouched.title == EXISTING_TASK_TITLE
    assert result.affected_objects
    assert result.affected_objects[0].kind == "task"
    assert result.affected_objects[0].state == PROPOSED_STATE
    assert result.affected_objects[0].object_id != existing_task.id
