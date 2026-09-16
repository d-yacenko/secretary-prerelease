from dataclasses import dataclass

from app.assistant.speech_constants import SPEECH_AUDIO_CONTENT_TYPE, SPEECH_RESPONSE_FORMAT


class SpeechProviderError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class SpeechCallResult:
    """Provider result that can carry actual OpenAI token usage across threads."""

    audio_bytes: bytes
    content_type: str = SPEECH_AUDIO_CONTENT_TYPE
    input_tokens: int | None = None
    output_tokens: int | None = None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    return None


def extract_speech_token_usage(response: object) -> tuple[int | None, int | None]:
    """Read actual token usage when the SDK/API reports it. Never estimate."""
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        http_response = getattr(response, "response", None)
        if http_response is not None:
            usage = getattr(http_response, "usage", None)
    if usage is None:
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


class OpenAISpeechProvider:
    def __init__(self, api_key: str, model: str, voice: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._voice = voice

    @property
    def model(self) -> str:
        return self._model

    @property
    def voice(self) -> str:
        return self._voice

    def synthesize(self, text: str) -> SpeechCallResult:
        try:
            response = self._client.audio.speech.create(
                model=self._model,
                voice=self._voice,
                input=text,
                response_format=SPEECH_RESPONSE_FORMAT,
            )
        except Exception as exc:
            raise SpeechProviderError("speech call failed") from exc

        audio_bytes = getattr(response, "content", None)
        if not audio_bytes:
            raise SpeechProviderError("speech returned empty audio")
        input_tokens, output_tokens = extract_speech_token_usage(response)
        return SpeechCallResult(
            audio_bytes=bytes(audio_bytes),
            content_type=SPEECH_AUDIO_CONTENT_TYPE,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
