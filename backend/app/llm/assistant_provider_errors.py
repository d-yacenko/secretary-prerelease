"""Typed Assistant provider failures with stable machine-readable codes."""

from __future__ import annotations

ASSISTANT_CONFIGURATION = "assistant_configuration"
OPENAI_CONNECTION = "openai_connection"
OPENAI_RATE_LIMIT = "openai_rate_limit"
OPENAI_SERVICE = "openai_service"
ASSISTANT_ROUND_LIMIT = "assistant_round_limit"
ASSISTANT_OUTPUT_LIMIT = "assistant_output_limit"
ASSISTANT_INTERNAL = "assistant_internal"
OPENAI_DAILY_BUDGET_EXHAUSTED = "openai_daily_budget_exhausted"

USER_MESSAGES: dict[str, str] = {
    ASSISTANT_CONFIGURATION: (
        "Не удалось запустить модель Секретаря. Проверьте настройки OpenAI."
    ),
    OPENAI_CONNECTION: "Не удалось связаться с OpenAI. Попробуйте ещё раз чуть позже.",
    OPENAI_RATE_LIMIT: (
        "OpenAI временно ограничил количество запросов. Попробуйте ещё раз позже."
    ),
    OPENAI_SERVICE: "Сервис OpenAI временно недоступен. Попробуйте ещё раз позже.",
    ASSISTANT_ROUND_LIMIT: (
        "Секретарю не хватило лимита шагов, чтобы завершить поиск. "
        "Попробуйте повторить или немного уточнить запрос."
    ),
    ASSISTANT_OUTPUT_LIMIT: (
        "Ответ оказался слишком большим для одного запроса. "
        "Попробуйте немного сузить запрос."
    ),
    ASSISTANT_INTERNAL: (
        "Секретарь не смог завершить запрос из-за внутренней ошибки."
    ),
    OPENAI_DAILY_BUDGET_EXHAUSTED: (
        "Дневной лимит OpenAI исчерпан. AI-функции приостановлены до 00:00."
    ),
}


class AssistantProviderError(Exception):
    code: str = ASSISTANT_INTERNAL

    def __init__(self, message: str | None = None) -> None:
        self.message = message or USER_MESSAGES[self.code]
        super().__init__(self.message)


class AssistantRoundLimitError(AssistantProviderError):
    code = ASSISTANT_ROUND_LIMIT


class AssistantOutputLimitError(AssistantProviderError):
    code = ASSISTANT_OUTPUT_LIMIT


class OpenAIConnectionError(AssistantProviderError):
    code = OPENAI_CONNECTION


class OpenAIRateLimitError(AssistantProviderError):
    code = OPENAI_RATE_LIMIT


class OpenAIServiceError(AssistantProviderError):
    code = OPENAI_SERVICE


class AssistantInternalError(AssistantProviderError):
    code = ASSISTANT_INTERNAL


def classify_openai_exception(exc: Exception) -> AssistantProviderError:
    if isinstance(exc, AssistantProviderError):
        return exc

    try:
        from openai import APIConnectionError, APIStatusError, InternalServerError, RateLimitError
    except ImportError:
        return AssistantInternalError()

    if isinstance(exc, APIConnectionError):
        return OpenAIConnectionError()
    if isinstance(exc, RateLimitError):
        return OpenAIRateLimitError()
    if isinstance(exc, InternalServerError):
        return OpenAIServiceError()
    if isinstance(exc, APIStatusError):
        if exc.status_code == 429:
            return OpenAIRateLimitError()
        if exc.status_code >= 500:
            return OpenAIServiceError()
    return AssistantInternalError()


def audit_error_category(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    return type(exc).__name__
