"""Communication Action Plan Integrity — no fake approval without a staged plan."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db
from app.assistant.tool_runner import PerTurnToolBudget
from app.db.models import ExternalActionAttempt, Object
from app.llm.assistant_models import AssistantHistoryMessage, AssistantProviderResult
from app.llm.openai_assistant_provider import SYSTEM_INSTRUCTIONS
from app.main import app
from app.tools.assistant_contracts import ASSISTANT_FUNCTION_SCHEMAS
from app.tools.results import ToolExecutionStatus
from tests.conftest import AuthTestClient, apply_embedding_service_overrides
from tests.test_assistant_action_plans import (
    ORIGINAL_BUILD_ASSISTANT_RUNTIME,
    _bind_action_plan_test_session,
    _set_assistant_runtime_override,
)
from tests.test_telegram_a_send import BOT_TOKEN, BOT_USERNAME, _tg_account, _tg_object
from tests.test_unified_communications_a import _patch_session_spy
from app.users.bootstrap import BOOTSTRAP_USER_ID
import app.api.assistant as assistant_api_module


@pytest.fixture
def telegram_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.settings.telegram_bot_token", BOT_TOKEN)
    monkeypatch.setattr("app.core.config.settings.telegram_bot_username", BOT_USERNAME)
    monkeypatch.setattr("app.core.config.settings.telegram_webhook_secret", "webhook-secret")
    monkeypatch.setattr(
        "app.core.config.settings.telegram_webhook_url",
        "https://example.test/integrations/telegram/webhook",
    )


@pytest.fixture(autouse=True)
def _restore_session_local_after_integrity_test() -> None:
    yield
    import app.ai_audit.context as ai_audit_context
    import app.assistant.session as assistant_session_module
    import app.services.assistant_service as assistant_service_module
    from app.db.session import SessionLocal

    assistant_service_module.SessionLocal = SessionLocal
    assistant_session_module.SessionLocal = SessionLocal
    ai_audit_context.SessionLocal = SessionLocal


@pytest.fixture
def action_plan_user() -> UUID:
    return BOOTSTRAP_USER_ID


@pytest.fixture
def action_plan_client(db_session, fake_embedding_service, action_plan_user, issue_bearer):
    bearer = issue_bearer(action_plan_user)
    headers = {"Authorization": f"Bearer {bearer}"}

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)

    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, headers), action_plan_user
    app.dependency_overrides.clear()
    assistant_api_module.build_assistant_runtime = ORIGINAL_BUILD_ASSISTANT_RUNTIME


def _bind_integrity_sessions(db_session) -> None:
    _bind_action_plan_test_session(db_session)

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    import app.ai_audit.context as ai_audit_context

    ai_audit_context.SessionLocal = lambda: _TestSession()


class _ProseConfirmationProvider:
    def __init__(self, answer: str) -> None:
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
        return AssistantProviderResult(
            answer=self._answer,
            candidate_object_ids=[],
            affected_object_ids=[],
            store_false_used=True,
        )


class _SendMessageProvider:
    def __init__(self, arguments: dict, answer: str = "Staged send.") -> None:
        self._arguments = arguments
        self._answer = answer
        self.ui_context = ""

    def run(
        self,
        message: str,
        history: list[AssistantHistoryMessage],
        ui_context: str,
        reference_datetime: datetime,
        timezone: str,
        tool_runner,
    ) -> AssistantProviderResult:
        self.ui_context = ui_context
        tool_runner("send_message", self._arguments)
        return AssistantProviderResult(
            answer=self._answer,
            candidate_object_ids=[],
            affected_object_ids=[],
            store_false_used=True,
        )


def test_provider_neutral_communication_instructions_cover_all_chat_providers() -> None:
    text = SYSTEM_INSTRUCTIONS.lower()
    assert "mattermost, telegram, and teams use the same send_message tool" in text
    assert "send_telegram" in text
    assert "draft, prepare, formulate, or research" in text
    assert "do not ask the user to confirm a send in prose" in text
    assert "never claim an action is prepared merely because you composed text" in text
    assert "composed text is not an action plan" in text
    contract = ASSISTANT_FUNCTION_SCHEMAS["send_message"]["description"].lower()
    assert "mattermost" in contract
    assert "telegram" in contract
    assert "teams" in contract
    assert "approval_required" in contract


def test_ui_context_object_is_seeded_into_send_message_allowlist(
    monkeypatch,
) -> None:
    calls = _patch_session_spy(monkeypatch)
    anchor = uuid4()
    budget = PerTurnToolBudget(initial_seen_object_ids=[anchor])
    result = budget.run(
        uuid4(),
        "send_message",
        {
            "body": "Да, это действительно обидно",
            "reply_to_object_id": str(anchor),
        },
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert len(calls) == 1
    assert calls[0][1] == "send_message"
    assert budget.staged_actions


def test_prose_confirmation_without_send_message_has_null_pending_plan(
    db_session, fake_embedding_service, action_plan_user, action_plan_client
):
    client, _user_id = action_plan_client
    provider = _ProseConfirmationProvider(
        "Ответ Петрушину: «Да, это действительно обидно». Подтвердите отправку."
    )
    _set_assistant_runtime_override(provider)
    _bind_integrity_sessions(db_session)

    response = client.post(
        "/assistant/message",
        json={"message": "Да, это действительно обидно, ответь это Петрушину."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pending_action_plan"] is None
    assert "Подтвердите отправку" in body["answer"]


def test_staged_telegram_send_message_returns_pending_action_plan(
    db_session, fake_embedding_service, action_plan_user, action_plan_client, telegram_settings
):
    client, user_id = action_plan_client
    account = _tg_account(db_session, user_id)
    inbound = _tg_object(db_session, user_id, account, body="TMLR есть в Scopus")
    provider = _SendMessageProvider(
        {
            "body": "Да, это действительно обидно",
            "reply_to_object_id": str(inbound.id),
        }
    )
    _set_assistant_runtime_override(provider)
    _bind_integrity_sessions(db_session)

    response = client.post(
        "/assistant/message",
        json={
            "message": "Да, это действительно обидно, ответь это Петрушину.",
            "context_object_id": str(inbound.id),
        },
    )

    assert response.status_code == 200
    body = response.json()
    plan = body["pending_action_plan"]
    assert plan is not None
    assert plan["status"] == "pending"
    assert plan["actions"][0]["tool_name"] == "send_message"
    frozen = plan["actions"][0]["arguments"]
    assert frozen["provider"] == "telegram"
    assert frozen["mode"] == "reply"
    assert frozen["body"] == "Да, это действительно обидно"
    assert frozen["anchor_object_id"] == str(inbound.id)
    assert str(inbound.id) in provider.ui_context
    attempts = db_session.scalars(select(ExternalActionAttempt)).all()
    assert attempts == []
    outbound = db_session.scalars(
        select(Object).where(
            Object.user_id == user_id,
            Object.provider == "telegram",
            Object.id != inbound.id,
        )
    ).all()
    assert outbound == []


def test_staged_teams_send_message_returns_pending_action_plan(
    db_session, fake_embedding_service, action_plan_user, action_plan_client, monkeypatch
):
    from cryptography.fernet import Fernet

    from tests.test_teams_a import _connect_account
    from tests.test_teams_a_send import _teams_object

    credential_key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    monkeypatch.setattr("app.core.config.settings.microsoft_oauth_client_id", "client-id")
    monkeypatch.setattr("app.core.config.settings.microsoft_oauth_client_secret", "client-secret")
    monkeypatch.setattr(
        "app.core.config.settings.microsoft_redirect_uri",
        "http://localhost:18080/auth/teams/callback",
    )
    client, user_id = action_plan_client
    account = _connect_account(db_session, credential_key, user_id)
    inbound = _teams_object(db_session, user_id, account)
    provider = _SendMessageProvider(
        {
            "body": "Да, это действительно обидно",
            "reply_to_object_id": str(inbound.id),
        }
    )
    _set_assistant_runtime_override(provider)
    _bind_integrity_sessions(db_session)

    response = client.post(
        "/assistant/message",
        json={
            "message": "Да, это действительно обидно, ответь это Петрушину.",
            "context_object_id": str(inbound.id),
        },
    )

    assert response.status_code == 200
    body = response.json()
    plan = body["pending_action_plan"]
    assert plan is not None
    frozen = plan["actions"][0]["arguments"]
    assert frozen["provider"] == "teams"
    assert frozen["mode"] == "reply"
    assert frozen["body"] == "Да, это действительно обидно"
    attempts = db_session.scalars(select(ExternalActionAttempt)).all()
    assert attempts == []
    assert db_session.scalars(
        select(Object).where(
            Object.user_id == user_id,
            Object.provider == "teams",
            Object.id != inbound.id,
        )
    ).all() == []
