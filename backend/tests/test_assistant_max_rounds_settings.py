"""Per-user assistant_max_rounds settings and runtime behavior."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.ai_audit.constants import EVENT_MODEL_ROUND, WORKLOAD_ASSISTANT_INTERACTIVE
from app.ai_audit.context import ai_trace_session
from app.ai_audit.trace_service import AITraceService
from app.assistant.constants import (
    DEFAULT_ASSISTANT_MAX_ROUNDS,
    MAX_ASSISTANT_MAX_ROUNDS,
    MAX_ASSISTANT_TOOL_CALLS_PER_TURN,
    MIN_ASSISTANT_MAX_ROUNDS,
)
from app.db.models import AITrace, UserSettings
from app.llm.assistant_provider_errors import ASSISTANT_ROUND_LIMIT, AssistantRoundLimitError
from app.llm.openai_assistant_provider import OpenAIAssistantProvider
from app.tools.executor import ToolExecutionResult
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient
from tests.test_assistant_failure_taxonomy import (
    _assistant_tool_response,
    _install_always_tool_openai,
)


@pytest.fixture
def profile_client(db_session, auth_headers):
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as raw:
        yield AuthTestClient(raw, auth_headers)
    app.dependency_overrides.clear()


def _tool_runner(*_args, **_kwargs):
    return ToolExecutionResult(
        success=True,
        tool_name="retrieve",
        output={"results": []},
    )


def _run_until_round_limit(provider: OpenAIAssistantProvider) -> int:
    call_count = 0

    class CountingResponses:
        def create(self, **_kwargs):
            nonlocal call_count
            call_count += 1
            return _assistant_tool_response()

    provider._client = SimpleNamespace(responses=CountingResponses())
    with pytest.raises(AssistantRoundLimitError):
        provider.run(
            message="hello",
            history=[],
            ui_context="",
            reference_datetime=datetime.now(UTC),
            timezone="Europe/Amsterdam",
            tool_runner=_tool_runner,
        )
    return call_count


def test_no_override_effective_default(profile_client) -> None:
    response = profile_client.get("/me/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["assistant_max_rounds"] == DEFAULT_ASSISTANT_MAX_ROUNDS
    assert body["assistant_max_rounds_override"] is None
    assert body["default_assistant_max_rounds"] == DEFAULT_ASSISTANT_MAX_ROUNDS
    assert body["min_assistant_max_rounds"] == MIN_ASSISTANT_MAX_ROUNDS
    assert body["max_assistant_max_rounds"] == MAX_ASSISTANT_MAX_ROUNDS


def test_provider_default_executes_six_rounds(monkeypatch) -> None:
    _install_always_tool_openai(monkeypatch)
    provider = OpenAIAssistantProvider(
        api_key="test",
        model="gpt-5.6-luna",
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=1600,
    )
    assert provider.max_rounds == DEFAULT_ASSISTANT_MAX_ROUNDS
    assert _run_until_round_limit(provider) == DEFAULT_ASSISTANT_MAX_ROUNDS


def test_provider_override_three_rounds(monkeypatch) -> None:
    _install_always_tool_openai(monkeypatch)
    provider = OpenAIAssistantProvider(
        api_key="test",
        model="gpt-5.6-luna",
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=1600,
        max_rounds=3,
    )
    assert _run_until_round_limit(provider) == 3


def test_provider_override_nine_rounds(monkeypatch) -> None:
    _install_always_tool_openai(monkeypatch)
    provider = OpenAIAssistantProvider(
        api_key="test",
        model="gpt-5.6-luna",
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=1600,
        max_rounds=9,
    )
    assert _run_until_round_limit(provider) == 9


def test_patch_override_and_explicit_null_reset(profile_client, db_session) -> None:
    response = profile_client.patch("/me/settings", json={"assistant_max_rounds": 4})
    assert response.status_code == 200
    body = response.json()
    assert body["assistant_max_rounds"] == 4
    assert body["assistant_max_rounds_override"] == 4

    row = db_session.get(UserSettings, BOOTSTRAP_USER_ID)
    assert row is not None
    assert row.assistant_max_rounds == 4

    reset = profile_client.patch("/me/settings", json={"assistant_max_rounds": None})
    assert reset.status_code == 200
    reset_body = reset.json()
    assert reset_body["assistant_max_rounds"] == DEFAULT_ASSISTANT_MAX_ROUNDS
    assert reset_body["assistant_max_rounds_override"] is None
    db_session.refresh(row)
    assert row.assistant_max_rounds is None


def test_patch_rejects_out_of_range(profile_client) -> None:
    low = profile_client.patch("/me/settings", json={"assistant_max_rounds": 0})
    assert low.status_code == 422
    high = profile_client.patch("/me/settings", json={"assistant_max_rounds": 13})
    assert high.status_code == 422


def test_patch_isolated_per_user(profile_client, db_session, second_user) -> None:
    user_b_id, user_b_headers = second_user
    profile_client.patch("/me/settings", json={"assistant_max_rounds": 5})
    response_b = profile_client.get("/me/settings", headers=user_b_headers)
    assert response_b.status_code == 200
    assert response_b.json()["assistant_max_rounds"] == DEFAULT_ASSISTANT_MAX_ROUNDS
    assert response_b.json()["assistant_max_rounds_override"] is None
    row_b = db_session.get(UserSettings, user_b_id)
    assert row_b is None or row_b.assistant_max_rounds is None


@pytest.fixture
def second_user(db_session):
    import uuid

    from app.auth.token_service import AuthTokenService
    from app.db.models import User

    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Second user"))
    db_session.flush()
    service = AuthTokenService(db_session)
    token, _ = service.issue_token(user_id, label="pytest-second")
    headers = {"Authorization": f"Bearer {token}"}
    return user_id, headers


def test_tool_call_guardrail_constant_unchanged() -> None:
    assert MAX_ASSISTANT_TOOL_CALLS_PER_TURN == 12


def test_round_limit_error_code_unchanged(monkeypatch) -> None:
    _install_always_tool_openai(monkeypatch)
    provider = OpenAIAssistantProvider(
        api_key="test",
        model="gpt-5.6-luna",
        max_rounds=2,
    )
    with pytest.raises(AssistantRoundLimitError) as exc_info:
        provider.run(
            message="hello",
            history=[],
            ui_context="",
            reference_datetime=datetime.now(UTC),
            timezone="Europe/Amsterdam",
            tool_runner=_tool_runner,
        )
    assert exc_info.value.code == ASSISTANT_ROUND_LIMIT


def test_telemetry_records_effective_max_rounds(db_session, monkeypatch) -> None:
    _install_always_tool_openai(monkeypatch)
    provider = OpenAIAssistantProvider(
        api_key="sk-test",
        model="gpt-test",
        max_rounds=3,
    )
    with pytest.raises(AssistantRoundLimitError), ai_trace_session(
        BOOTSTRAP_USER_ID,
        WORKLOAD_ASSISTANT_INTERACTIVE,
        session=db_session,
    ):
        provider.run(
            message="hello",
            history=[],
            ui_context="",
            reference_datetime=datetime.now(UTC),
            timezone="Europe/Amsterdam",
            tool_runner=_tool_runner,
        )
    db_session.commit()
    trace = db_session.scalar(
        select(AITrace)
        .where(
            AITrace.user_id == BOOTSTRAP_USER_ID,
            AITrace.workload == WORKLOAD_ASSISTANT_INTERACTIVE,
        )
        .order_by(AITrace.started_at.desc())
    )
    assert trace is not None
    events = AITraceService(db_session).list_trace_events(
        trace.id,
        BOOTSTRAP_USER_ID,
        include_payloads=False,
    )
    round_events = [event for event in events if event["event_type"] == EVENT_MODEL_ROUND]
    assert round_events
    assert all(event["metadata"]["effective_max_rounds"] == 3 for event in round_events)


def test_model_reasoning_verbosity_unaffected_by_max_rounds_patch(profile_client) -> None:
    before = profile_client.get("/me/settings").json()
    response = profile_client.patch("/me/settings", json={"assistant_max_rounds": 7})
    assert response.status_code == 200
    after = response.json()
    assert after["assistant_model"] == before["assistant_model"]
    assert after["assistant_reasoning_effort"] == before["assistant_reasoning_effort"]
    assert after["assistant_verbosity"] == before["assistant_verbosity"]
    assert after["assistant_max_rounds"] == 7
