import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from alembic import command
from app.api.assistant import AssistantRuntime, get_assistant_runtime
from app.api.deps import get_db
from app.assistant.action_plan_constants import (
    PENDING_ACTION_PLAN_STATUS_EXECUTED,
    PENDING_ACTION_PLAN_STATUS_PENDING,
    PENDING_ACTION_PLAN_STATUS_REJECTED,
)
from app.assistant.constants import MAX_ASSISTANT_HISTORY_MESSAGES
from app.db.engine import engine
from app.db.models import AssistantMessage, PendingActionPlan, User
from app.llm.assistant_models import AssistantHistoryMessage
from app.llm.fake_assistant_provider import FakeAssistantProvider
from app.main import app
from app.services.assistant_conversation_service import (
    INCOMPLETE_PERSISTENT_TURN,
    UNRESOLVED_PENDING_ACTION_PLAN,
    conversation_title_from_message,
)
from app.services.effective_user_settings_service import EffectiveUserSettings
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides


class RecordingProvider(FakeAssistantProvider):
    def __init__(self) -> None:
        super().__init__()
        self.histories: list[list[str]] = []
        self.run_count = 0
        self.text_only_count = 0

    def run(self, message, history, ui_context, reference_datetime, timezone, tool_runner, identity_facts=None):
        self.run_count += 1
        self.histories.append([item.content for item in history])
        return super().run(
            message,
            history,
            ui_context,
            reference_datetime,
            timezone,
            tool_runner,
            identity_facts,
        )

    def run_text_only(self, message: str, context: str):
        self.text_only_count += 1
        return super().run_text_only(message, context)


@pytest.fixture(scope="module", autouse=True)
def _assistant_conversation_schema() -> None:
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
def conversations_client(db_session, fake_embedding_service, auth_headers):
    provider = RecordingProvider()
    runtime = AssistantRuntime(
        provider=provider,
        effective=EffectiveUserSettings(
            timezone="Europe/Amsterdam",
            assistant_model="gpt-5.6-luna",
            assistant_reasoning_effort="low",
            assistant_verbosity="low",
            assistant_max_rounds=6,
            assistant_max_rounds_override=None,
            openai_api_key=None,
            openai_key_configured=False,
            allowed_assistant_models=["gpt-5.6-luna"],
        ),
    )

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_assistant_runtime] = lambda: runtime
    apply_embedding_service_overrides(fake_embedding_service)
    import app.api.assistant as assistant_api_module

    previous = assistant_api_module.build_assistant_runtime
    assistant_api_module.build_assistant_runtime = lambda session, user_id: runtime
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers), provider, db_session
    assistant_api_module.build_assistant_runtime = previous
    app.dependency_overrides.clear()


def test_conversation_title_is_deterministic_and_bounded() -> None:
    assert conversation_title_from_message("  hello\nworld  ") == "hello world"
    long_title = conversation_title_from_message("x" * 90)
    assert len(long_title) <= 72
    assert long_title.endswith("…")


def test_0047_downgrade_and_upgrade() -> None:
    config = Config("alembic.ini")
    command.downgrade(config, "0046")
    names = set(inspect(engine).get_table_names())
    assert "assistant_conversations" not in names
    assert "assistant_messages" not in names
    command.upgrade(config, "0047")
    names = set(inspect(engine).get_table_names())
    assert "assistant_conversations" in names
    assert "assistant_messages" in names


def test_current_conversation_is_unique_and_lists_by_recent_activity(conversations_client):
    client, _provider, _session = conversations_client
    created = client.post("/assistant/conversations")
    assert created.status_code == 201
    first_id = created.json()["id"]
    assert created.json()["is_current"] is True
    assert created.json()["title"] is None

    second = client.post("/assistant/conversations")
    assert second.status_code == 201
    second_id = second.json()["id"]
    listed = client.get("/assistant/conversations")
    assert listed.status_code == 200
    rows = listed.json()["conversations"]
    assert rows[0]["id"] == second_id
    assert rows[0]["is_current"] is True
    assert sum(1 for row in rows if row["is_current"]) == 1

    selected = client.post(f"/assistant/conversations/{first_id}/select")
    assert selected.status_code == 200
    assert selected.json()["id"] == first_id
    assert selected.json()["is_current"] is True
    current = client.get("/assistant/conversations/current")
    assert current.json()["id"] == first_id


def test_cross_user_isolation(conversations_client, db_session, issue_bearer):
    client, _provider, _session = conversations_client
    created = client.post("/assistant/conversations")
    conversation_id = created.json()["id"]
    other = User(id=uuid.uuid4(), display_name="other")
    db_session.add(other)
    db_session.flush()
    other_client = AuthTestClient(
        client._client,
        {"Authorization": f"Bearer {issue_bearer(other.id)}"},
    )
    assert other_client.get("/assistant/conversations").json()["conversations"] == []
    assert other_client.get("/assistant/conversations/current").status_code == 404
    assert other_client.post(f"/assistant/conversations/{conversation_id}/select").status_code == 404
    assert other_client.get(
        f"/assistant/conversations/{conversation_id}/messages"
    ).status_code == 404
    denied = other_client.post(
        "/assistant/message",
        json={
            "message": "secret",
            "conversation_id": conversation_id,
            "client_turn_id": str(uuid.uuid4()),
        },
    )
    assert denied.status_code == 404


def test_persistent_history_is_server_owned_and_legacy_history_still_works(conversations_client):
    client, provider, _session = conversations_client
    conversation_id = client.post("/assistant/conversations").json()["id"]
    for index in range(MAX_ASSISTANT_HISTORY_MESSAGES + 2):
        response = client.post(
            "/assistant/message",
            json={
                "message": f"stored-{index}",
                "history": [{"role": "user", "content": "IGNORE_CLIENT_HISTORY"}],
                "conversation_id": conversation_id,
                "client_turn_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 200
        assert response.json()["conversation_id"] == conversation_id
    assert provider.run_count == MAX_ASSISTANT_HISTORY_MESSAGES + 2
    latest_history = provider.histories[-1]
    assert "IGNORE_CLIENT_HISTORY" not in latest_history
    assert len(latest_history) == MAX_ASSISTANT_HISTORY_MESSAGES
    assert latest_history[-1] == "I can help search your Secretary objects and tasks."

    legacy = client.post(
        "/assistant/message",
        json={
            "message": "legacy",
            "history": [{"role": "user", "content": "legacy-marker"}],
        },
    )
    assert legacy.status_code == 200
    assert "conversation_id" not in legacy.json()
    assert "legacy-marker" in provider.histories[-1]


def test_persistent_turn_roundtrip_retry_and_incomplete_turn(conversations_client, db_session):
    client, provider, _session = conversations_client
    conversation_id = client.post("/assistant/conversations").json()["id"]
    turn_id = str(uuid.uuid4())
    object_id = uuid.uuid4()
    first = client.post(
        "/assistant/message",
        json={
            "message": "  first   line\ncontinues  ",
            "conversation_id": conversation_id,
            "client_turn_id": turn_id,
        },
    )
    assert first.status_code == 200
    assert provider.run_count == 1
    listed = client.get("/assistant/conversations")
    assert listed.json()["conversations"][0]["title"] == "first line continues"
    messages = client.get(f"/assistant/conversations/{conversation_id}/messages")
    body = messages.json()
    assert body["has_more"] is False
    assert [item["role"] for item in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content"].startswith("first")

    retry = client.post(
        "/assistant/message",
        json={
            "message": "first line continues",
            "conversation_id": conversation_id,
            "client_turn_id": turn_id,
        },
    )
    assert retry.status_code == 200
    assert provider.run_count == 1
    assert retry.json()["assistant_message_id"] == first.json()["assistant_message_id"]
    again = client.get(f"/assistant/conversations/{conversation_id}/messages")
    assert len(again.json()["messages"]) == 2

    assistant_row = db_session.scalar(
        select(AssistantMessage).where(
            AssistantMessage.id == uuid.UUID(first.json()["assistant_message_id"])
        )
    )
    assistant_row.presentation = {
        "references": [
            {
                "object_id": str(object_id),
                "title": "Pinned",
                "kind": "note",
                "canonical_uri": None,
                "provider": "gmail",
                "primary_at": "2026-09-01T00:00:00+00:00",
            }
        ],
        "affected_objects": [
            {
                "object_id": str(object_id),
                "title": "Pinned",
                "kind": "note",
                "state": "confirmed",
                "status": None,
            }
        ],
        "inbox_review_receipt": None,
    }
    db_session.flush()
    reconstructed = client.get(f"/assistant/conversations/{conversation_id}/messages")
    reference = reconstructed.json()["messages"][1]["references"][0]
    assert reference["object_id"] == str(object_id)
    assert reference["provider"] == "gmail"

    db_session.delete(assistant_row)
    db_session.flush()
    incomplete = client.post(
        "/assistant/message",
        json={
            "message": "again",
            "conversation_id": conversation_id,
            "client_turn_id": turn_id,
        },
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["detail"] == INCOMPLETE_PERSISTENT_TURN
    assert provider.run_count == 1


def test_switch_blocked_only_by_unresolved_pending_plan(conversations_client, db_session):
    client, _provider, _session = conversations_client
    conversation_id = uuid.UUID(client.post("/assistant/conversations").json()["id"])
    plan = PendingActionPlan(
        user_id=BOOTSTRAP_USER_ID,
        status=PENDING_ACTION_PLAN_STATUS_PENDING,
        actions=[{"tool_name": "create_task", "arguments": {"title": "x"}}],
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db_session.add(plan)
    db_session.flush()
    db_session.add(
        AssistantMessage(
            conversation_id=conversation_id,
            user_id=BOOTSTRAP_USER_ID,
            role="assistant",
            content="need approval",
            pending_action_plan_id=plan.id,
        )
    )
    db_session.flush()
    blocked = client.post("/assistant/conversations")
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == UNRESOLVED_PENDING_ACTION_PLAN
    blocked_select = client.post(f"/assistant/conversations/{conversation_id}/select")
    assert blocked_select.status_code == 200

    plan.status = PENDING_ACTION_PLAN_STATUS_EXECUTED
    db_session.flush()
    allowed = client.post("/assistant/conversations")
    assert allowed.status_code == 201

    client.post(f"/assistant/conversations/{conversation_id}/select")
    plan.status = PENDING_ACTION_PLAN_STATUS_REJECTED
    db_session.flush()
    assert client.post("/assistant/conversations").status_code == 201

    client.post(f"/assistant/conversations/{conversation_id}/select")
    plan.status = PENDING_ACTION_PLAN_STATUS_PENDING
    plan.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()
    assert client.post("/assistant/conversations").status_code == 201


def test_plan_status_hydrates_and_resume_persists_once(conversations_client, db_session):
    client, provider, _session = conversations_client
    conversation_id = uuid.UUID(client.post("/assistant/conversations").json()["id"])
    plan = PendingActionPlan(
        user_id=BOOTSTRAP_USER_ID,
        status=PENDING_ACTION_PLAN_STATUS_EXECUTED,
        actions=[{"tool_name": "create_task", "arguments": {"title": "done"}}],
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        result={},
    )
    db_session.add(plan)
    db_session.flush()
    db_session.add(
        AssistantMessage(
            conversation_id=conversation_id,
            user_id=BOOTSTRAP_USER_ID,
            role="assistant",
            content="staged",
            pending_action_plan_id=plan.id,
        )
    )
    db_session.flush()
    hydrated = client.get(f"/assistant/conversations/{conversation_id}/messages")
    assert hydrated.json()["messages"][0]["pending_action_plan"]["status"] == "executed"

    first = client.post(f"/assistant/action-plans/{plan.id}/resume")
    assert first.status_code == 200
    assert provider.text_only_count == 1
    second = client.post(f"/assistant/action-plans/{plan.id}/resume")
    assert second.status_code == 200
    assert second.json()["answer"] == first.json()["answer"]
    assert provider.text_only_count == 1
    messages = client.get(f"/assistant/conversations/{conversation_id}/messages").json()
    summaries = [
        item for item in messages["messages"] if item["content"] == first.json()["answer"]
    ]
    assert len(summaries) == 1


def test_history_type_stays_bounded_for_the_provider_contract():
    assert MAX_ASSISTANT_HISTORY_MESSAGES == 12
    sample = AssistantHistoryMessage(role="user", content="kept")
    assert sample.role == "user"
