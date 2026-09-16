"""Immediate stale content invalidation for generic web_page objects."""

from sqlalchemy.orm import Session

from app.content_extraction.mechanical_persistence import MechanicalRepresentationPersistence
from app.db.models import Object
from app.services.embedding_index import clear_object_embedding
from app.services.semantic_summary_service import invalidate_semantic_summary_metadata


def invalidate_web_page_content_immediately(session: Session, obj: Object) -> None:
    """Clear stale indexed content before a new web revision is persisted."""
    MechanicalRepresentationPersistence(session).clear_mechanical_for_object(obj.id)
    clear_object_embedding(obj)
    obj.metadata_ = invalidate_semantic_summary_metadata(dict(obj.metadata_ or {}))
    session.flush()
