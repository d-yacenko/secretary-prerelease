"""PHASE 22.7 — Assistant cost profile and usage telemetry."""

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db, get_embedding_service
from app.core.assistant_openai_config import (
    ALLOWED_ASSISTANT_REASONING_EFFORTS,
    ALLOWED_ASSISTANT_VERBOSITY,
    AssistantOpenAIConfigError,
    validated_assistant_openai_settings,
)
from app.core.config import Settings
from app.llm.assistant_provider_errors import AssistantOutputLimitError
from app.llm.openai_assistant_provider import AssistantProviderError, OpenAIAssistantProvider
from app.llm.openai_usage import ResponsesUsageAccumulated, response_hit_max_output_tokens
from app.main import app
from app.services.assistant_service import AssistantConfigurationError, create_assistant_provider
from app.tools.executor import ToolExecutionResult


def test_validated_assistant_openai_settings_defaults() -> None:
    settings = Settings(
        openai_assistant_model="gpt-5.6-luna",
        openai_assistant_reasoning_effort="low",
        openai_assistant_verbosity="low",
        openai_assistant_max_output_tokens=1600,
    )
    assistant = validated_assistant_openai_settings(settings)
    assert assistant.model == "gpt-5.6-luna"
    assert assistant.reasoning_effort == "low"
    assert assistant.verbosity == "low"
    assert assistant.max_output_tokens == 1600


def test_validated_assistant_openai_settings_rejects_invalid_effort() -> None:
    settings = Settings(openai_assistant_reasoning_effort="xhigh")
    with pytest.raises(AssistantOpenAIConfigError, match="REASONING_EFFORT"):
        validated_assistant_openai_settings(settings)


def test_validated_assistant_openai_settings_rejects_invalid_verbosity() -> None:
    settings = Settings(openai_assistant_verbosity="verbose")
    with pytest.raises(AssistantOpenAIConfigError, match="VERBOSITY"):
        validated_assistant_openai_settings(settings)


def test_validated_assistant_openai_settings_rejects_huge_max_output() -> None:
    settings = Settings(openai_assistant_max_output_tokens=100000)
    with pytest.raises(AssistantOpenAIConfigError, match="MAX_OUTPUT_TOKENS"):
        validated_assistant_openai_settings(settings)


def test_create_assistant_provider_uses_assistant_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.assistant_service.settings",
        Settings(
            openai_api_key="sk-test",
            openai_model="gpt-5.6-terra",
            openai_assistant_model="gpt-5.6-luna",
            openai_assistant_reasoning_effort="low",
            openai_assistant_verbosity="low",
            openai_assistant_max_output_tokens=1600,
        ),
    )
    provider = create_assistant_provider()
    assert provider._model == "gpt-5.6-luna"
    assert provider._reasoning_effort == "low"
    assert provider._verbosity == "low"
    assert provider._max_output_tokens == 1600


def test_responses_create_passes_assistant_profile(monkeypatch) -> None:
    captured: list[dict] = []

    class FakeResponses:
        def create(self, **kwargs):
            captured.append(kwargs)
            response = MagicMock()
            response.status = "completed"
            response.usage = MagicMock(input_tokens=10, output_tokens=5)
            response.output = []
            response.output_text = "ok"
            return response

    class FakeClient:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))

    provider = OpenAIAssistantProvider(
        api_key="test",
        model="gpt-5.6-luna",
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=1600,
    )
    provider.run(
        message="hello",
        history=[],
        ui_context="",
        reference_datetime=datetime.now(UTC),
        timezone="Europe/Amsterdam",
        tool_runner=lambda *_: ToolExecutionResult(success=True, tool_name="get_today", output={}),
    )

    assert len(captured) == 1
    call = captured[0]
    assert call["model"] == "gpt-5.6-luna"
    assert call["reasoning"] == {"effort": "low"}
    assert call["text"] == {"verbosity": "low"}
    assert call["max_output_tokens"] == 1600
    assert call["store"] is False


def test_usage_accumulates_across_responses_rounds() -> None:
    totals = ResponsesUsageAccumulated()

    round_one = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=30,
            input_tokens_details=SimpleNamespace(cached_tokens=40, cache_write_tokens=0),
            output_tokens_details=SimpleNamespace(reasoning_tokens=20),
        )
    )
    totals.accumulate(round_one)

    round_two = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=200,
            output_tokens=50,
            input_tokens_details=SimpleNamespace(cached_tokens=100, cache_write_tokens=20),
            output_tokens_details=SimpleNamespace(reasoning_tokens=35),
        )
    )
    totals.accumulate(round_two)

    assert totals.input_tokens == 300
    assert totals.cached_input_tokens == 140
    assert totals.cache_write_tokens == 20
    assert totals.output_tokens == 80
    assert totals.reasoning_tokens == 55
    assert totals.responses_rounds == 2


def test_usage_accumulates_dict_shaped_usage() -> None:
    totals = ResponsesUsageAccumulated()
    totals.accumulate(
        SimpleNamespace(
            usage={
                "input_tokens": 100,
                "input_tokens_details": {
                    "cached_tokens": 40,
                    "cache_write_tokens": 10,
                },
                "output_tokens": 30,
                "output_tokens_details": {
                    "reasoning_tokens": 20,
                },
            }
        )
    )

    assert totals.input_tokens == 100
    assert totals.cached_input_tokens == 40
    assert totals.cache_write_tokens == 10
    assert totals.output_tokens == 30
    assert totals.reasoning_tokens == 20
    assert totals.responses_rounds == 1


def test_usage_details_absent_metrics_remain_none() -> None:
    totals = ResponsesUsageAccumulated()
    totals.accumulate(
        SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=50,
                output_tokens=10,
                input_tokens_details=None,
                output_tokens_details=None,
            )
        )
    )

    assert totals.input_tokens == 50
    assert totals.output_tokens == 10
    assert totals.cached_input_tokens is None
    assert totals.cache_write_tokens is None
    assert totals.reasoning_tokens is None


def test_usage_details_object_with_missing_individual_fields() -> None:
    totals = ResponsesUsageAccumulated()
    totals.accumulate(
        SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=20,
                output_tokens=5,
                input_tokens_details=SimpleNamespace(cached_tokens=10),
                output_tokens_details=SimpleNamespace(),
            )
        )
    )

    assert totals.cached_input_tokens == 10
    assert totals.cache_write_tokens is None
    assert totals.reasoning_tokens is None


def test_usage_partial_metrics_across_rounds() -> None:
    totals = ResponsesUsageAccumulated()

    totals.accumulate(
        SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                input_tokens_details=SimpleNamespace(cache_write_tokens=3),
                output_tokens_details=SimpleNamespace(reasoning_tokens=20),
            )
        )
    )
    totals.accumulate(
        SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=20,
                output_tokens=10,
                input_tokens_details=SimpleNamespace(cached_tokens=0),
                output_tokens_details=None,
            )
        )
    )
    totals.accumulate(SimpleNamespace(usage=None))

    assert totals.input_tokens == 30
    assert totals.output_tokens == 15
    assert totals.cached_input_tokens == 0
    assert totals.cache_write_tokens == 3
    assert totals.reasoning_tokens == 20
    assert totals.responses_rounds == 3


def test_usage_reasoning_sums_only_reported_rounds() -> None:
    totals = ResponsesUsageAccumulated()

    totals.accumulate(
        SimpleNamespace(
            usage=SimpleNamespace(
                output_tokens_details=SimpleNamespace(reasoning_tokens=20),
            )
        )
    )
    totals.accumulate(SimpleNamespace(usage=SimpleNamespace(output_tokens_details=None)))
    totals.accumulate(
        SimpleNamespace(
            usage=SimpleNamespace(
                output_tokens_details=SimpleNamespace(reasoning_tokens=10),
            )
        )
    )

    assert totals.reasoning_tokens == 30
    assert totals.responses_rounds == 3


def test_usage_cache_write_stays_none_when_never_reported() -> None:
    totals = ResponsesUsageAccumulated()

    totals.accumulate(
        SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens_details=SimpleNamespace(cached_tokens=5),
            )
        )
    )
    totals.accumulate(
        SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens_details=SimpleNamespace(cached_tokens=0),
            )
        )
    )

    assert totals.cached_input_tokens == 5
    assert totals.cache_write_tokens is None


def test_create_assistant_provider_invalid_effort_raises_configuration_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.assistant_service.settings",
        Settings(
            openai_api_key="sk-test",
            openai_assistant_reasoning_effort="xhigh",
        ),
    )
    with pytest.raises(AssistantConfigurationError, match="REASONING_EFFORT"):
        create_assistant_provider()


def test_create_assistant_provider_invalid_max_output_raises_configuration_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.assistant_service.settings",
        Settings(
            openai_api_key="sk-test",
            openai_assistant_max_output_tokens=100000,
        ),
    )
    with pytest.raises(AssistantConfigurationError, match="MAX_OUTPUT_TOKENS"):
        create_assistant_provider()


def test_assistant_invalid_openai_assistant_config_returns_502(
    db_session,
    fake_embedding_service,
    auth_headers,
    monkeypatch,
) -> None:
    from tests.conftest import apply_embedding_service_overrides, AuthTestClient

    monkeypatch.setattr("app.core.config.settings.openai_api_key", "sk-test")
    monkeypatch.setattr("app.core.config.settings.openai_assistant_reasoning_effort", "xhigh")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(fake_embedding_service)
    with TestClient(app) as test_client:
        client = AuthTestClient(test_client, auth_headers)
        response = client.post("/assistant/message", json={"message": "hello"})
    app.dependency_overrides.clear()
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "assistant_configuration"


def test_max_output_tokens_incomplete_raises_provider_error(monkeypatch) -> None:
    class FakeResponses:
        def create(self, **kwargs):
            response = MagicMock()
            response.status = "incomplete"
            response.incomplete_details = MagicMock(reason="max_output_tokens")
            response.usage = MagicMock(input_tokens=50, output_tokens=1600)
            response.output = []
            return response

    class FakeClient:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))

    provider = OpenAIAssistantProvider(
        api_key="test",
        model="gpt-5.6-luna",
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=1600,
    )
    with pytest.raises(AssistantOutputLimitError):
        provider.run(
            message="hello",
            history=[],
            ui_context="",
            reference_datetime=datetime.now(UTC),
            timezone="Europe/Amsterdam",
            tool_runner=lambda *_: ToolExecutionResult(success=True, tool_name="get_today", output={}),
        )


def test_response_hit_max_output_tokens_detector() -> None:
    incomplete = MagicMock(status="incomplete", incomplete_details=MagicMock(reason="max_output_tokens"))
    complete = MagicMock(status="completed", incomplete_details=None)
    assert response_hit_max_output_tokens(incomplete)
    assert not response_hit_max_output_tokens(complete)


def test_allowed_assistant_config_values_cover_gpt56_profile() -> None:
    assert "none" in ALLOWED_ASSISTANT_REASONING_EFFORTS
    assert "low" in ALLOWED_ASSISTANT_REASONING_EFFORTS
    assert "medium" in ALLOWED_ASSISTANT_REASONING_EFFORTS
    assert "high" in ALLOWED_ASSISTANT_REASONING_EFFORTS
    assert "low" in ALLOWED_ASSISTANT_VERBOSITY


def test_openai_provider_accumulates_detailed_usage_across_rounds(monkeypatch) -> None:
    from app.assistant.tool_runner import PerTurnToolBudget
    from app.users.bootstrap import BOOTSTRAP_USER_ID

    api_calls = 0
    captured_kwargs: list[dict] = []
    usage_rounds = [
        {
            "input_tokens": 100,
            "output_tokens": 30,
            "cached": 40,
            "cache_write": 0,
            "reasoning": 20,
        },
        {
            "input_tokens": 200,
            "output_tokens": 50,
            "cached": 100,
            "cache_write": 20,
            "reasoning": 35,
        },
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached": 0,
            "cache_write": 0,
            "reasoning": 0,
        },
    ]

    class FakeResponses:
        def create(self, **kwargs):
            nonlocal api_calls
            captured_kwargs.append(kwargs)
            usage = usage_rounds[api_calls]
            response = SimpleNamespace(
                status="completed",
                usage=SimpleNamespace(
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    input_tokens_details=SimpleNamespace(
                        cached_tokens=usage["cached"],
                        cache_write_tokens=usage["cache_write"],
                    ),
                    output_tokens_details=SimpleNamespace(
                        reasoning_tokens=usage["reasoning"],
                    ),
                ),
                output=(
                    [
                        {
                            "type": "function_call",
                            "name": "get_today",
                            "call_id": f"call-{api_calls + 1}",
                            "arguments": "{}",
                        }
                    ]
                    if api_calls < 2
                    else []
                ),
                output_text=None if api_calls < 2 else "done",
            )
            api_calls += 1
            return response

    class FakeClient:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))

    budget = PerTurnToolBudget()
    provider = OpenAIAssistantProvider(
        api_key="test",
        model="gpt-5.6-luna",
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=1600,
    )
    result = provider.run(
        message="hello",
        history=[],
        ui_context="",
        reference_datetime=datetime.now(UTC),
        timezone="Europe/Amsterdam",
        tool_runner=lambda name, args: budget.run(BOOTSTRAP_USER_ID, name, args),
    )

    assert result.openai_input_tokens == 300
    assert result.openai_cached_input_tokens == 140
    assert result.openai_cache_write_tokens == 20
    assert result.openai_output_tokens == 80
    assert result.openai_reasoning_tokens == 55
    assert result.openai_responses_rounds == 3
    assert api_calls == 3
    for kwargs in captured_kwargs:
        assert kwargs["model"] == "gpt-5.6-luna"
        assert kwargs["reasoning"] == {"effort": "low"}
        assert kwargs["text"] == {"verbosity": "low"}
        assert kwargs["max_output_tokens"] == 1600
        assert kwargs["store"] is False


@pytest.mark.live
def test_live_assistant_minimal_round() -> None:
    if os.environ.get("RUN_LIVE_OPENAI") != "1":
        pytest.skip("set RUN_LIVE_OPENAI=1 to run live OpenAI smoke")
    from app.core.config import settings

    if not settings.openai_api_key:
        pytest.skip("OPENAI_API_KEY not configured")

    provider = create_assistant_provider()
    result = provider.run(
        message="Reply with exactly: pong",
        history=[],
        ui_context="",
        reference_datetime=datetime.now(UTC),
        timezone=settings.secretary_timezone,
        tool_runner=lambda *_: ToolExecutionResult(success=True, tool_name="get_today", output={}),
    )
    assert result.answer
    assert result.openai_input_tokens is not None
    assert result.openai_output_tokens is not None
    assert result.openai_model == settings.openai_assistant_model
