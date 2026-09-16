from typing import Protocol


class Summarizer(Protocol):
    def summarize(self, text: str) -> str: ...


class FakeSummarizer:
    """Deterministic short summary for tests without an LLM."""

    def __init__(self, max_chars: int = 200) -> None:
        self._max_chars = max_chars

    def summarize(self, text: str) -> str:
        stripped = " ".join(text.split())
        if len(stripped) <= self._max_chars:
            return stripped
        return stripped[: self._max_chars].rstrip() + "…"
