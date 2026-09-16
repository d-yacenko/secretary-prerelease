from app.assistant.speech_constants import SPEECH_AUDIO_CONTENT_TYPE
from app.llm.openai_speech_provider import SpeechCallResult


class FakeSpeechProvider:
    """Deterministic speech synthesis for tests without OpenAI."""

    def __init__(
        self,
        audio_bytes: bytes = b"fake-mp3-bytes",
        content_type: str = SPEECH_AUDIO_CONTENT_TYPE,
    ) -> None:
        self._audio_bytes = audio_bytes
        self._content_type = content_type
        self.calls: list[str] = []
        self.model = "fake-tts"

    def synthesize(self, text: str) -> SpeechCallResult:
        self.calls.append(text)
        return SpeechCallResult(
            audio_bytes=self._audio_bytes,
            content_type=self._content_type,
        )
