"""Immediate stale content invalidation for explicit cloud resources."""

from sqlalchemy.orm import Session

from app.content_extraction.constants import EXTRACTION_VERSION
from app.content_extraction.mechanical_persistence import MechanicalRepresentationPersistence
from app.content_extraction.metadata_keys import (
    CONTENT_EXTRACTION_STATUS,
    CONTENT_EXTRACTION_VERSION,
    MECHANICAL_REPRESENTATION_COUNT,
)
from app.db.models import Object
from app.services.embedding_index import clear_object_embedding
from app.services.semantic_summary_service import invalidate_semantic_summary_metadata

STATUS_PENDING = "pending"


def invalidate_object_content_immediately(session: Session, obj: Object) -> None:
    """Clear stale indexed content before a new revision is extracted."""
    MechanicalRepresentationPersistence(session).clear_mechanical_for_object(obj.id)
    clear_object_embedding(obj)
    merged = invalidate_semantic_summary_metadata(dict(obj.metadata_ or {}))
    merged[CONTENT_EXTRACTION_STATUS] = STATUS_PENDING
    merged[CONTENT_EXTRACTION_VERSION] = EXTRACTION_VERSION
    merged[MECHANICAL_REPRESENTATION_COUNT] = 0
    merged.pop("content_extraction_error", None)
    obj.metadata_ = merged
    session.flush()
