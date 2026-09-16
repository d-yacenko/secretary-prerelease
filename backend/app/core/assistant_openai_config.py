from dataclasses import dataclass

from app.core.config import Settings, normalize_allowed_assistant_models

ALLOWED_ASSISTANT_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high"})
ALLOWED_ASSISTANT_VERBOSITY = frozenset({"low", "medium", "high"})
MIN_ASSISTANT_MAX_OUTPUT_TOKENS = 64
MAX_ASSISTANT_MAX_OUTPUT_TOKENS = 4096


@dataclass(frozen=True)
class AssistantOpenAISettings:
    model: str
    reasoning_effort: str
    verbosity: str
    max_output_tokens: int


class AssistantOpenAIConfigError(ValueError):
    pass


def validate_assistant_reasoning_effort(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in ALLOWED_ASSISTANT_REASONING_EFFORTS:
        allowed = ", ".join(sorted(ALLOWED_ASSISTANT_REASONING_EFFORTS))
        raise AssistantOpenAIConfigError(
            f"assistant_reasoning_effort must be one of: {allowed}"
        )
    return normalized


def validate_assistant_verbosity(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in ALLOWED_ASSISTANT_VERBOSITY:
        allowed = ", ".join(sorted(ALLOWED_ASSISTANT_VERBOSITY))
        raise AssistantOpenAIConfigError(
            f"assistant_verbosity must be one of: {allowed}"
        )
    return normalized


def validate_assistant_model(value: str, allowed_models: list[str]) -> str:
    model = value.strip()
    if not model:
        raise AssistantOpenAIConfigError("assistant_model cannot be blank")
    if model not in allowed_models:
        allowed = ", ".join(allowed_models)
        raise AssistantOpenAIConfigError(
            f"assistant_model must be one of: {allowed}"
        )
    return model


def validated_assistant_openai_settings(settings: Settings) -> AssistantOpenAISettings:
    model = settings.openai_assistant_model.strip()
    if not model:
        raise AssistantOpenAIConfigError("OPENAI_ASSISTANT_MODEL cannot be blank")

    try:
        reasoning_effort = validate_assistant_reasoning_effort(
            settings.openai_assistant_reasoning_effort
        )
    except AssistantOpenAIConfigError as exc:
        message = str(exc).replace(
            "assistant_reasoning_effort",
            "OPENAI_ASSISTANT_REASONING_EFFORT",
        )
        raise AssistantOpenAIConfigError(message) from exc

    try:
        verbosity = validate_assistant_verbosity(settings.openai_assistant_verbosity)
    except AssistantOpenAIConfigError as exc:
        message = str(exc).replace("assistant_verbosity", "OPENAI_ASSISTANT_VERBOSITY")
        raise AssistantOpenAIConfigError(message) from exc

    max_output_tokens = settings.openai_assistant_max_output_tokens
    if not MIN_ASSISTANT_MAX_OUTPUT_TOKENS <= max_output_tokens <= MAX_ASSISTANT_MAX_OUTPUT_TOKENS:
        raise AssistantOpenAIConfigError(
            f"OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS must be between "
            f"{MIN_ASSISTANT_MAX_OUTPUT_TOKENS} and {MAX_ASSISTANT_MAX_OUTPUT_TOKENS}"
        )

    allowed_models = normalize_allowed_assistant_models(
        settings.openai_allowed_assistant_models,
        model,
    )
    if model not in allowed_models:
        raise AssistantOpenAIConfigError(
            f"OPENAI_ASSISTANT_MODEL must be one of: {', '.join(allowed_models)}"
        )

    return AssistantOpenAISettings(
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity=verbosity,
        max_output_tokens=max_output_tokens,
    )
