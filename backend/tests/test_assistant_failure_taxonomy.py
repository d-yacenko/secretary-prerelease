"""Assistant failure taxonomy and user-facing API error responses."""

pytest_plugins = ("tests.test_assistant",)

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.ai_audit.constants import WORKLOAD_ASSISTANT_INTERACTIVE
from app.ai_audit.context import ai_trace_session
from app.assistant.constants import DEFAULT_ASSISTANT_MAX_ROUNDS
from app.db.models import AITrace
from app.llm.assistant_provider_errors import (
    ASSISTANT_CONFIGURATION,
    ASSISTANT_OUTPUT_LIMIT,
    ASSISTANT_ROUND_LIMIT,
    OPENAI_CONNECTION,
    OPENAI_RATE_LIMIT,
    OPENAI_SERVICE,
    USER_MESSAGES,
    AssistantOutputLimitError,
    AssistantRoundLimitError,
    OpenAIConnectionError,
    OpenAIRateLimitError,
    OpenAIServiceError,
)
from app.llm.openai_assistant_provider import AssistantProviderError, OpenAIAssistantProvider
from app.tools.executor import ToolExecutionResult
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _assistant_tool_response():
    return SimpleNamespace(
        status="completed",
        incomplete_details=None,
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            input_tokens_details=SimpleNamespace(cached_tokens=0, cache_write_tokens=0),
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
        output=[
            {
                "type": "function_call",
                "name": "retrieve",
                "call_id": "call-1",
                "arguments": '{"query":"test"}',
            }
        ],
        output_text=None,
    )


def _install_always_tool_openai(monkeypatch) -> None:
    class FakeResponses:
        def create(self, **kwargs):
            return _assistant_tool_response()

    class FakeClient:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))


def test_round_limit_raises_typed_error(monkeypatch) -> None:
    _install_always_tool_openai(monkeypatch)
    provider = OpenAIAssistantProvider(
        api_key="test",
        model="gpt-5.6-luna",
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=1600,
    )
    with pytest.raises(AssistantRoundLimitError) as exc_info:
        provider.run(
            message="hello",
            history=[],
            ui_context="",
            reference_datetime=datetime.now(UTC),
            timezone="Europe/Amsterdam",
            tool_runner=lambda *_: ToolExecutionResult(
                success=True,
                tool_name="retrieve",
                output={"results": []},
            ),
        )
    assert exc_info.value.code == ASSISTANT_ROUND_LIMIT


def test_round_limit_api_response(assistant_client) -> None:
    client, provider = assistant_client

    def failing_run(*args, **kwargs):
        raise AssistantRoundLimitError()

    provider.run = failing_run
    response = client.post("/assistant/message", json={"message": "hello"})
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == ASSISTANT_ROUND_LIMIT
    assert detail["message"] == USER_MESSAGES[ASSISTANT_ROUND_LIMIT]
    assert "Assistant provider unavailable" not in detail["message"]
    assert "Assistant provider unavailable" not in response.text


def test_round_limit_audit_error_category(db_session, monkeypatch) -> None:
    _install_always_tool_openai(monkeypatch)
    provider = OpenAIAssistantProvider(api_key="sk-test", model="gpt-test")
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
            tool_runner=lambda *_: ToolExecutionResult(
                success=True,
                tool_name="retrieve",
                output={"results": []},
            ),
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
    assert trace.success is False
    assert trace.error_category == ASSISTANT_ROUND_LIMIT


def test_output_limit_api_response(assistant_client) -> None:
    client, provider = assistant_client

    def incomplete_run(*args, **kwargs):
        raise AssistantOutputLimitError()

    provider.run = incomplete_run
    response = client.post("/assistant/message", json={"message": "hello"})
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == ASSISTANT_OUTPUT_LIMIT
    assert detail["message"] == USER_MESSAGES[ASSISTANT_OUTPUT_LIMIT]


def test_openai_connection_api_response(assistant_client) -> None:
    client, provider = assistant_client

    def failing_run(*args, **kwargs):
        raise OpenAIConnectionError()

    provider.run = failing_run
    response = client.post("/assistant/message", json={"message": "hello"})
    detail = response.json()["detail"]
    assert detail["code"] == OPENAI_CONNECTION
    assert detail["message"] == USER_MESSAGES[OPENAI_CONNECTION]


def test_openai_rate_limit_api_response(assistant_client) -> None:
    client, provider = assistant_client

    def failing_run(*args, **kwargs):
        raise OpenAIRateLimitError()

    provider.run = failing_run
    response = client.post("/assistant/message", json={"message": "hello"})
    detail = response.json()["detail"]
    assert detail["code"] == OPENAI_RATE_LIMIT
    assert detail["message"] == USER_MESSAGES[OPENAI_RATE_LIMIT]


def test_openai_service_api_response(assistant_client) -> None:
    client, provider = assistant_client

    def failing_run(*args, **kwargs):
        raise OpenAIServiceError()

    provider.run = failing_run
    response = client.post("/assistant/message", json={"message": "hello"})
    detail = response.json()["detail"]
    assert detail["code"] == OPENAI_SERVICE
    assert detail["message"] == USER_MESSAGES[OPENAI_SERVICE]


def test_configuration_failure_api_response(
    db_session,
    fake_embedding_service,
    auth_headers,
    monkeypatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import app
    from tests.conftest import AuthTestClient, apply_embedding_service_overrides

    monkeypatch.setattr("app.core.config.settings.openai_api_key", "")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        client = AuthTestClient(test_client, auth_headers)
        response = client.post("/assistant/message", json={"message": "hello"})
    app.dependency_overrides.clear()
    detail = response.json()["detail"]
    assert response.status_code == 502
    assert detail["code"] == ASSISTANT_CONFIGURATION
    assert detail["message"] == USER_MESSAGES[ASSISTANT_CONFIGURATION]


def test_provider_error_response_does_not_leak_raw_text(assistant_client) -> None:
    client, provider = assistant_client

    def failing_run(*args, **kwargs):
        raise AssistantProviderError()

    provider.run = failing_run
    response = client.post("/assistant/message", json={"message": "hello"})
    assert "sk-" not in response.text
    assert "Traceback" not in response.text
    detail = response.json()["detail"]
    assert set(detail.keys()) == {"code", "message"}


def test_openai_provider_classifies_rate_limit_error(monkeypatch) -> None:
    from openai import RateLimitError

    class FailingResponses:
        def create(self, **kwargs):
            raise RateLimitError(
                "rate limited",
                response=MagicMock(status_code=429),
                body=None,
            )

    provider = OpenAIAssistantProvider(api_key="sk-test", model="gpt-test")
    provider._client = SimpleNamespace(responses=FailingResponses())

    with pytest.raises(AssistantProviderError) as exc_info:
        provider.run_text_only(message="hi", context="ctx")
    assert exc_info.value.code == OPENAI_RATE_LIMIT


def test_openai_provider_classifies_service_error(monkeypatch) -> None:
    from openai import InternalServerError

    class FailingResponses:
        def create(self, **kwargs):
            raise InternalServerError(
                "server down",
                response=MagicMock(status_code=500),
                body=None,
            )

    provider = OpenAIAssistantProvider(api_key="sk-test", model="gpt-test")
    provider._client = SimpleNamespace(responses=FailingResponses())

    with pytest.raises(AssistantProviderError) as exc_info:
        provider.run_text_only(message="hi", context="ctx")
    assert exc_info.value.code == OPENAI_SERVICE


def test_openai_provider_classifies_connection_error(monkeypatch) -> None:
    from openai import APIConnectionError

    class FailingResponses:
        def create(self, **kwargs):
            raise APIConnectionError(request=MagicMock())

    provider = OpenAIAssistantProvider(api_key="sk-test", model="gpt-test")
    provider._client = SimpleNamespace(responses=FailingResponses())

    with pytest.raises(AssistantProviderError) as exc_info:
        provider.run_text_only(message="hi", context="ctx")
    assert exc_info.value.code == OPENAI_CONNECTION


def test_max_assistant_rounds_constant_unchanged() -> None:
    assert DEFAULT_ASSISTANT_MAX_ROUNDS == 6
