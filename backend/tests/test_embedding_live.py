import os

import pytest

from app.core.config import settings
from app.llm.embedding_service import OpenAIEmbeddingService
from app.llm.embedding_text import EMBEDDING_DIMENSION


@pytest.mark.live
def test_openai_embedding_live_smoke() -> None:
    if os.getenv("RUN_LIVE_OPENAI") != "1":
        pytest.skip("set RUN_LIVE_OPENAI=1 to run live OpenAI embedding smoke test")
    if not settings.openai_api_key:
        pytest.skip("OPENAI_API_KEY is not configured")

    service = OpenAIEmbeddingService(
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model,
    )
    vector = service.embed("personal secretary live embedding smoke test")
    assert len(vector) == EMBEDDING_DIMENSION
    assert any(value != 0.0 for value in vector)
