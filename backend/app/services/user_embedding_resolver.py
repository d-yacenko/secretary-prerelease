"""Narrow per-user OpenAI embedding provider resolution for request-time paths."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.llm.embedding_service import (
    EmbeddingService,
    OpenAIEmbeddingService,
    create_embedding_service_for_api_key,
)
from app.services.effective_user_settings_service import EffectiveUserSettingsService
from app.services.openai_daily_budget import OpenAIDailyBudgetGuard

EMBEDDING_PROVIDER_UNAVAILABLE = "Embedding provider unavailable"


def resolve_embedding_service_for_user(session: Session, user_id: UUID) -> EmbeddingService:
    api_key = EffectiveUserSettingsService.build(session).resolve_openai_api_key(user_id)
    service = create_embedding_service_for_api_key(api_key)
    if not isinstance(service, OpenAIEmbeddingService):
        return service
    return OpenAIDailyBudgetGuard.build(session, user_id).guard_embedding_service(service)
