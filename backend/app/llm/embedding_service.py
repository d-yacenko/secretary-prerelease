import hashlib
import math
import re
import time
from typing import Protocol

from openai import OpenAI

from app.ai_audit.instrumentation import record_simple_model_call
from app.core.config import settings
from app.llm.embedding_text import EMBEDDING_DIMENSION

_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "about",
        "is",
        "are",
        "was",
        "were",
    }
)


class EmbeddingService(Protocol):
    def embed(self, text: str) -> list[float]: ...


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [token for token in tokens if token not in _STOP_WORDS]


class FakeEmbeddingService:
    """Deterministic bag-of-words style vectors for tests without OpenAI."""

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSION
        for token in _tokenize(text):
            digest = hashlib.sha256(token.encode()).digest()
            for offset in range(8):
                index = int.from_bytes(digest[offset:offset + 2], "big") % EMBEDDING_DIMENSION
                vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]


class OpenAIEmbeddingService:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def embed(self, text: str) -> list[float]:
        started = time.perf_counter()
        try:
            response = self._client.embeddings.create(input=text, model=self._model)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            record_simple_model_call(
                model=self._model,
                input_chars=len(text),
                output_chars=0,
                elapsed_ms=elapsed_ms,
                failed=True,
                error_category=type(exc).__name__,
                extra={"embedding_dimension": EMBEDDING_DIMENSION},
            )
            raise
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        vector = list(response.data[0].embedding)
        usage = getattr(response, "usage", None)
        extra: dict = {"embedding_dimension": len(vector)}
        if usage is not None:
            total_tokens = getattr(usage, "total_tokens", None)
            if total_tokens is not None:
                extra["input_tokens"] = int(total_tokens)
        record_simple_model_call(
            model=self._model,
            input_chars=len(text),
            output_chars=0,
            elapsed_ms=elapsed_ms,
            extra=extra,
            diagnostic_payloads={"model_input_text": text},
        )
        return vector


def create_embedding_service() -> EmbeddingService:
    if settings.openai_api_key:
        return OpenAIEmbeddingService(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
        )
    return FakeEmbeddingService()


def create_embedding_service_for_api_key(api_key: str | None) -> EmbeddingService:
    if api_key:
        return OpenAIEmbeddingService(
            api_key=api_key,
            model=settings.openai_embedding_model,
        )
    return FakeEmbeddingService()
