import os
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from app.api.schemas import ContextBuildResult, ContextItem
from app.core.config import settings
from app.llm.openai_secretary_provider import OpenAISecretaryProvider
from app.services.secretary_service import SECRETARY_INSTRUCTIONS

FIXED_REFERENCE = datetime(2026, 8, 28, 10, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
EMAIL_TEXT = (
    "Let's meet tomorrow at 13:30. Please send the updated forecast before the meeting."
)


@pytest.mark.live
def test_openai_secretary_live_smoke() -> None:
    if os.getenv("RUN_LIVE_OPENAI") != "1":
        pytest.skip("set RUN_LIVE_OPENAI=1 to run live OpenAI secretary smoke test")
    if not settings.openai_api_key:
        pytest.skip("OPENAI_API_KEY is not configured")

    provider = OpenAISecretaryProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )
    context = ContextBuildResult(
        items=[
            ContextItem(
                object_id=UUID("00000000-0000-4000-8000-000000000001"),
                kind="email",
                title="Inbound email",
                content=EMAIL_TEXT,
                origin="source",
                state="observed",
                why_included="target object",
            )
        ],
        total_chars=len(EMAIL_TEXT),
        truncated=False,
    )
    analysis = provider.analyze(
        trigger="analyze inbound email",
        context=context,
        reference_datetime=FIXED_REFERENCE,
        timezone=settings.secretary_timezone,
        instructions=SECRETARY_INSTRUCTIONS,
    )
    assert analysis.proposals
