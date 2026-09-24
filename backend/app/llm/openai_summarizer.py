"""OpenAI semantic summarizer for resource representations."""

import logging
import time

from app.ai_audit.instrumentation import record_simple_model_call
from app.llm.summarizer import Summarizer
from app.services.background_ai_errors import BackgroundAIConfigurationError
from app.services.effective_user_settings_service import EffectiveUserSettings

logger = logging.getLogger(__name__)

_SUMMARY_INSTRUCTIONS = (
    "Summarize the resource in Russian in <=500 characters. "
    "Answer: what is it, what is it about, what role does it appear to have. "
    "No speculation beyond the provided text. No secrets not already in the text."
)

CONVERSATION_STACK_SUMMARY_INSTRUCTIONS = (
    "Write one short factual Russian sentence about this conversation burst. "
    "Ground the sentence only in the provided messages. No recommendations. "
    "Do not infer intent beyond the messages. Do not include secrets, tokens, "
    "or credentials even if they appear in the text."
)


class OpenAISummarizer:
    def __init__(
        self,
        api_key: str,
        model: str,
        reasoning_effort: str = "low",
        verbosity: str = "low",
        max_output_tokens: int = 400,
        max_chars: int = 500,
        instructions: str | None = None,
    ) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._verbosity = verbosity
        self._max_output_tokens = max_output_tokens
        self._max_chars = max_chars
        self._instructions = instructions or _SUMMARY_INSTRUCTIONS

    def summarize(self, text: str) -> str:
        bounded = text[:4000]
        started = time.perf_counter()
        try:
            response = self._client.responses.create(
                model=self._model,
                instructions=self._instructions,
                input=bounded,
                reasoning={"effort": self._reasoning_effort},
                text={"verbosity": self._verbosity},
                max_output_tokens=self._max_output_tokens,
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            record_simple_model_call(
                model=self._model,
                reasoning_effort=self._reasoning_effort,
                verbosity=self._verbosity,
                max_output_tokens=self._max_output_tokens,
                input_chars=len(bounded),
                output_chars=0,
                elapsed_ms=elapsed_ms,
                failed=True,
                error_category=type(exc).__name__,
            )
            raise
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        output = _extract_response_text(response).strip()
        record_simple_model_call(
            model=self._model,
            reasoning_effort=self._reasoning_effort,
            verbosity=self._verbosity,
            max_output_tokens=self._max_output_tokens,
            input_chars=len(bounded),
            output_chars=len(output),
            elapsed_ms=elapsed_ms,
            response=response,
            diagnostic_payloads={
                "instructions": _SUMMARY_INSTRUCTIONS,
                "model_input": bounded,
                "model_output": output,
            },
        )
        if len(output) > self._max_chars:
            return output[: self._max_chars].rstrip() + "…"
        return output


def _extract_response_text(response) -> str:
    for item in response.output or []:
        if item.type == "message":
            for content in item.content or []:
                if content.type == "output_text":
                    return content.text
    return ""


def create_openai_summarizer_from_effective(
    effective: EffectiveUserSettings,
) -> Summarizer:
    if not effective.openai_api_key:
        raise BackgroundAIConfigurationError("OpenAI API key is not configured")
    return OpenAISummarizer(
        api_key=effective.openai_api_key,
        model=effective.assistant_model,
        reasoning_effort=effective.assistant_reasoning_effort,
        verbosity=effective.assistant_verbosity,
    )


def create_openai_conversation_stack_summarizer_from_effective(
    effective: EffectiveUserSettings,
) -> Summarizer:
    if not effective.openai_api_key:
        raise BackgroundAIConfigurationError("OpenAI API key is not configured")
    return OpenAISummarizer(
        api_key=effective.openai_api_key,
        model=effective.assistant_model,
        reasoning_effort=effective.assistant_reasoning_effort,
        verbosity=effective.assistant_verbosity,
        max_output_tokens=120,
        max_chars=160,
        instructions=CONVERSATION_STACK_SUMMARY_INSTRUCTIONS,
    )
