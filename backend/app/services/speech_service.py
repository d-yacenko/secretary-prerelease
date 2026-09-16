import time

from starlette.concurrency import run_in_threadpool

from app.ai_audit.context import get_active_trace
from app.ai_audit.instrumentation import record_simple_model_call
from app.assistant.speech_constants import (
    MAX_SPEECH_INPUT_CHARS,
    SPEECH_AUDIO_CONTENT_TYPE,
    SPEECH_TEXT_EMPTY,
    SPEECH_TEXT_TOO_LONG,
)
from app.assistant.speech_text import prepare_speech_text
from app.core.config import settings
from app.llm.fake_speech_provider import FakeSpeechProvider
from app.llm.openai_speech_provider import (
    OpenAISpeechProvider,
    SpeechCallResult,
    SpeechProviderError,
)
from app.services.errors import ValidationError


class SpeechConfigurationError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class SpeechProvider:
    def synthesize(self, text: str) -> SpeechCallResult:
        raise NotImplementedError


def prepare_speech_request_text(text: str) -> str:
    if text is None:
        raise ValidationError(SPEECH_TEXT_EMPTY)
    if len(text) > MAX_SPEECH_INPUT_CHARS:
        raise ValidationError(SPEECH_TEXT_TOO_LONG)
    if not text.strip():
        raise ValidationError(SPEECH_TEXT_EMPTY)
    prepared = prepare_speech_text(text)
    if not prepared:
        raise ValidationError(SPEECH_TEXT_EMPTY)
    return prepared


async def synthesize_speech_text(text: str, provider: SpeechProvider) -> SpeechCallResult:
    return await synthesize_prepared_speech_text(
        prepare_speech_request_text(text),
        provider,
    )


async def synthesize_prepared_speech_text(
    prepared: str,
    provider: SpeechProvider,
) -> SpeechCallResult:
    model = _provider_model(provider)
    started = time.perf_counter()
    try:
        result = await run_in_threadpool(provider.synthesize, prepared)
        audio, token_usage, content_type = _normalize_speech_result(result)
    except SpeechProviderError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if get_active_trace() is not None:
            record_simple_model_call(
                model=model,
                input_chars=len(prepared),
                output_chars=0,
                elapsed_ms=elapsed_ms,
                failed=True,
                error_category=type(exc).__name__,
                extra={"speech_chars": len(prepared)},
            )
        raise

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    extra = {
        "speech_chars": len(prepared),
        "audio_bytes": len(audio),
        "content_type": content_type,
        **token_usage,
    }
    if get_active_trace() is not None:
        record_simple_model_call(
            model=model,
            input_chars=len(prepared),
            output_chars=len(audio),
            elapsed_ms=elapsed_ms,
            extra=extra,
            diagnostic_payloads={"speech_input": prepared},
        )
    return SpeechCallResult(audio_bytes=audio, content_type=content_type)


def _normalize_speech_result(result: object) -> tuple[bytes, dict[str, int], str]:
    if isinstance(result, SpeechCallResult):
        extra: dict[str, int] = {}
        if result.input_tokens is not None:
            extra["input_tokens"] = result.input_tokens
        if result.output_tokens is not None:
            extra["output_tokens"] = result.output_tokens
        content_type = result.content_type or SPEECH_AUDIO_CONTENT_TYPE
        if not result.audio_bytes:
            raise SpeechProviderError("speech returned empty audio")
        return result.audio_bytes, extra, content_type
    raise SpeechProviderError("speech returned empty audio")


def _provider_model(provider: SpeechProvider) -> str:
    model = getattr(provider, "model", None)
    if isinstance(model, str) and model:
        return model
    return settings.openai_tts_model.strip() or "unknown"


def create_speech_provider_for_api_key(api_key: str | None) -> OpenAISpeechProvider:
    if not api_key:
        raise SpeechConfigurationError("OpenAI API key is not configured")
    model = settings.openai_tts_model.strip()
    if not model:
        raise SpeechConfigurationError("OPENAI_TTS_MODEL cannot be blank")
    voice = settings.openai_tts_voice.strip()
    if not voice:
        raise SpeechConfigurationError("OPENAI_TTS_VOICE cannot be blank")
    return OpenAISpeechProvider(api_key=api_key, model=model, voice=voice)


def create_fake_speech_provider(
    audio_bytes: bytes = b"fake-mp3-bytes",
) -> FakeSpeechProvider:
    return FakeSpeechProvider(audio_bytes=audio_bytes)
