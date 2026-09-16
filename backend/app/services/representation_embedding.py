import logging

from app.db.models import Representation
from app.llm.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


def refresh_representation_embedding(
    rep: Representation,
    embedding_service: EmbeddingService,
    text: str,
) -> None:
    try:
        rep.embedding = embedding_service.embed(text)
    except Exception:  # noqa: BLE001
        logger.warning("representation embedding failed for representation %s", rep.id)
        rep.embedding = None
