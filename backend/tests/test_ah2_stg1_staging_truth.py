"""AH2-STG1 — staged turns do not expose model prose as execution truth."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import ObjectCreate
from app.db.engine import engine
from app.db.models import User
from app.llm.assistant_models import AssistantHistoryMessage, AssistantProviderResult
from app.main import app
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE, USER_ORIGIN
from tests.conftest import AuthTestClient, apply_embedding_service_overrides
import app.api.assistant as assistant_api_module

HOSTILE_STATUS = "Статус изменён на open."
HOSTILE_MUTATION = "Создано. Отправлено. Удалено."
READ_ONLY_ANSWER = "В поиске три открытые задачи."
FINAL_ANSWER = "Статус не изменился."


class _ScriptedProvider:
    def __init__(self, calls: list[tuple[str, dict]], answer: str) -> None:
        self._calls = calls
        self._answer = answer
        self.run_calls = 0
        self.text_only_calls = 0

    def run(
        self,
        message: str,
        history: list[AssistantHistoryMessage],
        ui_context: str,
        reference_datetime,
        timezone: str,
        tool_runner,
    ) -> AssistantProviderResult:
        self.run_calls += 1
        for tool_name, arguments in self._calls:
            tool_runner(tool_name, arguments)
        return AssistantProviderResult(
            answer=self._answer,
            candidate_object_ids=[],
            affected_object_ids=[],
            store_false_used=True,
        )

    def run_text_only(self, message: str, context: str) -> AssistantProviderResult:
        self.text_only_calls += 1
        return AssistantProviderResult(
            answer=FINAL_ANSWER,
            candidate_object_ids=[],
            affected_object_ids=[],
            store_false_used=True,
        )


@pytest.fixture(autouse=True)
def _restore_session_local():
    yield
    import app.assistant.session as assistant_session_module
    import app.services.assistant_service as assistant_service_module
    from app.db.session import SessionLocal

    assistant_service_module.SessionLocal = SessionLocal
    assistant_session_module.SessionLocal = SessionLocal


@pytest.fixture(autouse=True)
def _committed_staging_users():
    user_ids: list[uuid.UUID] = []
    yield user_ids
    if not user_ids:
        return
    with Session(engine) as session:
        for user_id in user_ids:
            user = session.get(User, user_id)
            if user is not None:
                session.delete(user)
        session.commit()


@pytest.fixture
def staging_user(_committed_staging_users) -> uuid.UUID:
    user_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=user_id, display_name="staging truth"))
        session.commit()
    _committed_staging_users.append(user_id)
    return user_id


@pytest.fixture
def staging_client(db_session, fake_embedding_service, staging_user, issue_bearer):
    bearer = issue_bearer(staging_user)
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
    previous = assistant_api_module.build_assistant_runtime
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, headers), staging_user
    assistant_api_module.build_assistant_runtime = previous
    app.dependency_overrides.clear()


def _bind_plan_session(db_session) -> None:
    import app.assistant.session as assistant_session_module
    import app.services.assistant_service as assistant_service_module

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    assistant_service_module.SessionLocal = lambda: _TestSession()
    assistant_session_module.SessionLocal = lambda: _TestSession()


def _use_provider(provider: _ScriptedProvider) -> None:
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


def _task(db_session, user_id: uuid.UUID) -> str:
    created = GraphService(db_session, user_id).create_object(
        ObjectCreate(
            kind="task",
            title="Публикации",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
            status="open",
        )
    )
    return str(created.id)


def _post_message(client, provider: _ScriptedProvider, payload: dict):
    _use_provider(provider)
    response = client.post("/assistant/message", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_hostile_status_prose_is_dropped_and_card_stays_open_to_open(
    db_session, fake_embedding_service, staging_client
):
    client, user_id = staging_client
    _bind_plan_session(db_session)
    task_id = _task(db_session, user_id)
    provider = _ScriptedProvider(
        [("set_task_status", {"object_id": task_id, "status": "open"})],
        HOSTILE_STATUS,
    )
    body = _post_message(
        client,
        provider,
        {"message": "поставь open", "context_object_id": task_id},
    )
    assert body["answer"] == ""
    assert HOSTILE_STATUS not in body["answer"]
    plan = body["pending_action_plan"]
    snapshot = plan["actions"][0]["presentation"]
    fields = {item["name"]: item["value"] for item in snapshot["fields"]}
    assert snapshot["entities"][0]["title"] == "Публикации"
    assert fields["current_status"] == "open"
    assert fields["status"] == "open"
    assert provider.text_only_calls == 0
    assert "conversation_id" not in body


def test_generic_mutation_claims_are_not_user_facing(
    db_session, fake_embedding_service, staging_client
):
    client, _user_id = staging_client
    _bind_plan_session(db_session)
    provider = _ScriptedProvider(
        [("create_task", {"title": "Письмо", "confidence": 0.8})],
        HOSTILE_MUTATION,
    )
    body = _post_message(client, provider, {"message": "создай"})
    assert body["answer"] == ""
    assert "Создано" not in body["answer"]
    assert "Отправлено" not in body["answer"]
    assert "Удалено" not in body["answer"]
    assert body["pending_action_plan"]["actions"][0]["tool_name"] == "create_task"
    assert provider.text_only_calls == 0


def test_read_only_answer_is_preserved(db_session, fake_embedding_service, staging_client):
    client, _user_id = staging_client
    _bind_plan_session(db_session)
    provider = _ScriptedProvider([], READ_ONLY_ANSWER)
    body = _post_message(client, provider, {"message": "что открыто"})
    assert body["answer"] == READ_ONLY_ANSWER
    assert body.get("pending_action_plan") is None


def test_persistent_reload_does_not_resurrect_staging_prose(
    db_session, fake_embedding_service, staging_client
):
    client, _user_id = staging_client
    _bind_plan_session(db_session)
    conversation_id = client.post("/assistant/conversations").json()["id"]
    provider = _ScriptedProvider(
        [("create_task", {"title": "Письмо", "confidence": 0.8})],
        HOSTILE_MUTATION,
    )
    turn_id = str(uuid.uuid4())
    staged = _post_message(
        client,
        provider,
        {
            "message": "создай задачу",
            "conversation_id": conversation_id,
            "client_turn_id": turn_id,
        },
    )
    assert staged["answer"] == ""
    messages = client.get(f"/assistant/conversations/{conversation_id}/messages").json()
    assistant = messages["messages"][1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == ""
    assert HOSTILE_MUTATION not in assistant["content"]
    assert assistant["pending_action_plan"]["id"] == staged["pending_action_plan"]["id"]


def test_persistent_history_omits_discarded_staging_prose(
    db_session, fake_embedding_service, staging_client
):
    client, _user_id = staging_client
    _bind_plan_session(db_session)
    conversation_id = client.post("/assistant/conversations").json()["id"]
    staged = _ScriptedProvider(
        [("create_task", {"title": "Письмо", "confidence": 0.8})],
        HOSTILE_MUTATION,
    )
    _post_message(
        client,
        staged,
        {
            "message": "создай задачу",
            "conversation_id": conversation_id,
            "client_turn_id": str(uuid.uuid4()),
        },
    )

    class _HistoryProbe(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__([], READ_ONLY_ANSWER)
            self.seen: list[str] = []

        def run(self, message, history, ui_context, reference_datetime, timezone, tool_runner):
            self.seen = [item.content for item in history]
            return super().run(
                message, history, ui_context, reference_datetime, timezone, tool_runner
            )

    probe = _HistoryProbe()
    body = _post_message(
        client,
        probe,
        {
            "message": "уточни",
            "conversation_id": conversation_id,
            "client_turn_id": str(uuid.uuid4()),
        },
    )
    assert body["answer"] == READ_ONLY_ANSWER
    assert HOSTILE_MUTATION not in "\n".join(probe.seen)


def test_approval_finalization_keeps_the_staging_message_safe(
    db_session, fake_embedding_service, staging_client
):
    client, user_id = staging_client
    _bind_plan_session(db_session)
    task_id = _task(db_session, user_id)
    conversation_id = client.post("/assistant/conversations").json()["id"]
    provider = _ScriptedProvider(
        [("set_task_status", {"object_id": task_id, "status": "open"})],
        HOSTILE_STATUS,
    )
    staged = _post_message(
        client,
        provider,
        {
            "message": "поставь open",
            "context_object_id": task_id,
            "conversation_id": conversation_id,
            "client_turn_id": str(uuid.uuid4()),
        },
    )
    plan_id = staged["pending_action_plan"]["id"]
    approved = client.post(f"/assistant/action-plans/{plan_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "executed"
    resumed = client.post(f"/assistant/action-plans/{plan_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["answer"] == FINAL_ANSWER
    assert provider.text_only_calls == 1
    messages = client.get(f"/assistant/conversations/{conversation_id}/messages").json()["messages"]
    staging = next(item for item in messages if item["pending_action_plan"] is not None)
    assert staging["content"] == ""
    assert HOSTILE_STATUS not in staging["content"]
    assert any(item["content"] == FINAL_ANSWER for item in messages)


def test_rejection_does_not_acquire_execution_claims(
    db_session, fake_embedding_service, staging_client
):
    client, _user_id = staging_client
    _bind_plan_session(db_session)
    conversation_id = client.post("/assistant/conversations").json()["id"]
    provider = _ScriptedProvider(
        [("create_task", {"title": "Письмо", "confidence": 0.8})],
        HOSTILE_MUTATION,
    )
    staged = _post_message(
        client,
        provider,
        {
            "message": "создай задачу",
            "conversation_id": conversation_id,
            "client_turn_id": str(uuid.uuid4()),
        },
    )
    plan_id = staged["pending_action_plan"]["id"]
    rejected = client.post(f"/assistant/action-plans/{plan_id}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert "answer" not in rejected.json()
    messages = client.get(f"/assistant/conversations/{conversation_id}/messages").json()["messages"]
    staging = next(item for item in messages if item["role"] == "assistant")
    assert staging["content"] == ""
    assert staging["pending_action_plan"]["status"] == "rejected"
    assert provider.text_only_calls == 0
