class FakeTranscriptionProvider:
    """Deterministic transcription for tests without OpenAI."""

    def __init__(self, text: str = "recognized speech") -> None:
        self._text = text
        self.calls: list[tuple[bytes, str, str | None]] = []

    def transcribe(
        self,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        self.calls.append((audio_bytes, filename, content_type))
        return self._text
