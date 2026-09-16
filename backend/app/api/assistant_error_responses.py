"""Structured Assistant API error responses."""

from app.core.assistant_openai_config import AssistantOpenAIConfigError
from app.llm.assistant_provider_errors import (
    ASSISTANT_CONFIGURATION,
    ASSISTANT_INTERNAL,
    OPENAI_DAILY_BUDGET_EXHAUSTED,
    USER_MESSAGES,
    AssistantProviderError,
)
from app.services.assistant_service import AssistantConfigurationError
from app.services.openai_daily_budget import OpenAIDailyBudgetExhaustedError
from app.services.user_openai_credential_errors import UserOpenAICredentialConfigurationError


def build_openai_daily_budget_error_detail(
    exc: OpenAIDailyBudgetExhaustedError,
) -> dict[str, object]:
    """Stable typed payload the client renders locally instead of a network error."""
    detail: dict[str, object] = {
        "code": OPENAI_DAILY_BUDGET_EXHAUSTED,
        "message": USER_MESSAGES[OPENAI_DAILY_BUDGET_EXHAUSTED],
    }
    detail.update(exc.status.to_payload())
    return detail


def build_assistant_error_detail(exc: Exception) -> dict[str, str]:
    if isinstance(exc, AssistantProviderError):
        return {"code": exc.code, "message": exc.message}
    if isinstance(
        exc,
        (
            AssistantConfigurationError,
            AssistantOpenAIConfigError,
            UserOpenAICredentialConfigurationError,
        ),
    ):
        return {
            "code": ASSISTANT_CONFIGURATION,
            "message": USER_MESSAGES[ASSISTANT_CONFIGURATION],
        }
    return {
        "code": ASSISTANT_INTERNAL,
        "message": USER_MESSAGES[ASSISTANT_INTERNAL],
    }
