from dataclasses import dataclass


class TranscriptionProviderError(Exception):
    code = "transcription_provider_failed"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class TranscriptionAudioInvalidError(Exception):
    code = "transcription_audio_invalid"

    def __init__(self, message: str = "transcription audio invalid") -> None:
        self.message = message
        super().__init__(message)


class TranscriptionUnrecognizedError(Exception):
    code = "transcription_unrecognized"

    def __init__(self, message: str = "transcription unrecognized") -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class TranscriptionCallResult:
    """Provider result that can carry actual OpenAI token usage across threads."""

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    return None


def extract_transcription_token_usage(
    response: object,
) -> tuple[int | None, int | None]:
    """Read actual token usage from an OpenAI transcription response.

    SDK 3.7 `Transcription.usage` is either `UsageTokens` (`type="tokens"` with
    `input_tokens`/`output_tokens`) or `UsageDuration` (`type="duration"`).
    Duration-only usage is not converted into a token estimate.
    """
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return None, None
    usage_type = getattr(usage, "type", None)
    if usage_type is None and isinstance(usage, dict):
        usage_type = usage.get("type")
    if usage_type == "duration":
        return None, None

    if isinstance(usage, dict):
        input_tokens = _optional_int(usage.get("input_tokens"))
        output_tokens = _optional_int(usage.get("output_tokens"))
    else:
        input_tokens = _optional_int(getattr(usage, "input_tokens", None))
        output_tokens = _optional_int(getattr(usage, "output_tokens", None))
    if input_tokens is None and output_tokens is None:
        return None, None
    return input_tokens, output_tokens


class OpenAITranscriptionProvider:
    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def transcribe(
        self,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> TranscriptionCallResult:
        file_payload = (
            filename,
            audio_bytes,
            content_type or "application/octet-stream",
        )
        try:
            response = self._client.audio.transcriptions.create(
                model=self._model,
                file=file_payload,
            )
        except Exception as exc:
            raise TranscriptionProviderError("transcription call failed") from exc

        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise TranscriptionUnrecognizedError("transcription returned empty text")
        input_tokens, output_tokens = extract_transcription_token_usage(response)
        return TranscriptionCallResult(
            text=str(text),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
