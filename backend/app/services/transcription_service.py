import time

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.ai_audit.context import get_active_trace
from app.ai_audit.instrumentation import record_simple_model_call
from app.assistant.transcription_audio import read_bounded_transcription_audio
from app.assistant.transcription_telemetry import log_transcription_telemetry
from app.assistant.wav_inspect import inspect_wav, should_reject_wav_for_transcription
from app.core.config import settings
from app.llm.fake_transcription_provider import FakeTranscriptionProvider
from app.llm.openai_transcription_provider import (
    OpenAITranscriptionProvider,
    TranscriptionAudioInvalidError,
    TranscriptionCallResult,
    TranscriptionProviderError,
    TranscriptionUnrecognizedError,
)


class TranscriptionConfigurationError(Exception):
    code = "transcription_provider_not_configured"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class TranscriptionProvider:
    def transcribe(
        self,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        raise NotImplementedError


async def transcribe_audio_upload(
    upload: UploadFile,
    provider: TranscriptionProvider,
) -> str:
    audio_bytes, filename = await read_bounded_transcription_audio(upload)
    content_type = upload.content_type
    _reject_locally_invalid_wav(audio_bytes, filename)
    model = _provider_model(provider)
    started = time.perf_counter()
    try:
        text = await run_in_threadpool(
            provider.transcribe,
            audio_bytes,
            filename,
            content_type,
        )
        transcript, token_usage = _normalize_transcription_result(text)
    except (
        TranscriptionProviderError,
        TranscriptionAudioInvalidError,
        TranscriptionUnrecognizedError,
    ) as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        category = getattr(exc, "code", type(exc).__name__)
        if get_active_trace() is not None:
            record_simple_model_call(
                model=model,
                input_chars=len(audio_bytes),
                output_chars=0,
                elapsed_ms=elapsed_ms,
                failed=True,
                error_category=category,
                extra={
                    "audio_bytes": len(audio_bytes),
                    "filename": filename,
                    "content_type": content_type,
                    "error_category": category,
                },
            )
        log_transcription_telemetry(
            model=model,
            input_bytes=len(audio_bytes),
            elapsed_ms=elapsed_ms,
            success=False,
            filename=filename,
            content_type=content_type,
            error_category=category,
        )
        raise

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    extra = {
        "audio_bytes": len(audio_bytes),
        "filename": filename,
        "content_type": content_type,
        **token_usage,
    }
    if get_active_trace() is not None:
        record_simple_model_call(
            model=model,
            input_chars=len(audio_bytes),
            output_chars=len(transcript),
            elapsed_ms=elapsed_ms,
            extra=extra,
            diagnostic_payloads={"transcript_output": transcript},
        )
    log_transcription_telemetry(
        model=model,
        input_bytes=len(audio_bytes),
        elapsed_ms=elapsed_ms,
        success=True,
        filename=filename,
        content_type=content_type,
    )
    return transcript


def _normalize_transcription_result(result: object) -> tuple[str, dict[str, int]]:
    """Keep actual billed tokens if the provider returned them. Never estimate."""
    if isinstance(result, str):
        if not result.strip():
            raise TranscriptionUnrecognizedError("transcription returned empty text")
        return result, {}
    if isinstance(result, TranscriptionCallResult):
        if not result.text.strip():
            raise TranscriptionUnrecognizedError("transcription returned empty text")
        extra: dict[str, int] = {}
        if result.input_tokens is not None:
            extra["input_tokens"] = result.input_tokens
        if result.output_tokens is not None:
            extra["output_tokens"] = result.output_tokens
        return result.text, extra
    text = getattr(result, "text", None)
    if isinstance(text, str) and text.strip():
        return text, {}
    raise TranscriptionUnrecognizedError("transcription returned empty text")


def _reject_locally_invalid_wav(audio_bytes: bytes, filename: str) -> None:
    if not filename.lower().endswith(".wav"):
        return
    inspect = inspect_wav(audio_bytes)
    if inspect is None or should_reject_wav_for_transcription(inspect):
        raise TranscriptionAudioInvalidError("secretary wav too short or malformed")


def _provider_model(provider: TranscriptionProvider) -> str:
    model = getattr(provider, "model", None)
    if isinstance(model, str) and model:
        return model
    return settings.openai_transcription_model.strip() or "unknown"


def create_transcription_provider_for_api_key(
    api_key: str | None,
) -> OpenAITranscriptionProvider:
    if not api_key:
        raise TranscriptionConfigurationError("OpenAI API key is not configured")
    model = settings.openai_transcription_model.strip()
    if not model:
        raise TranscriptionConfigurationError("OPENAI_TRANSCRIPTION_MODEL cannot be blank")
    return OpenAITranscriptionProvider(api_key=api_key, model=model)


def create_transcription_provider() -> OpenAITranscriptionProvider:
    deployment_key = settings.openai_api_key.strip() or None
    return create_transcription_provider_for_api_key(deployment_key)


def create_fake_transcription_provider(text: str = "recognized speech") -> FakeTranscriptionProvider:
    return FakeTranscriptionProvider(text=text)
