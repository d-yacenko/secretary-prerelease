from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.db.models import Object, Representation
from app.db.session import SessionLocal
from app.services.bounded_chunks import MAX_INDEXED_TEXT_CHUNKS
from app.services.representation_service import KIND_CHUNK


@dataclass(frozen=True)
class ChunkEmbeddingTarget:
    representation_id: UUID
    text: str


def load_unembedded_chunk_targets(object_id: UUID, user_id: UUID) -> list[ChunkEmbeddingTarget]:
    session = SessionLocal()
    try:
        obj = session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == user_id)
        )
        if obj is None:
            raise ValueError(f"object ownership mismatch: {object_id}")
        reps = session.scalars(
            select(Representation)
            .where(
                Representation.object_id == object_id,
                Representation.kind == KIND_CHUNK,
                Representation.embedding.is_(None),
            )
            .order_by(Representation.part_index)
            .limit(MAX_INDEXED_TEXT_CHUNKS)
        ).all()
        return [
            ChunkEmbeddingTarget(rep.id, rep.text or "")
            for rep in reps
        ]
    finally:
        session.close()


def store_representation_embeddings(
    object_id: UUID,
    user_id: UUID,
    embeddings: list[tuple[UUID, list[float]]],
) -> None:
    if not embeddings:
        return
    session = SessionLocal()
    try:
        obj = session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == user_id)
        )
        if obj is None:
            raise ValueError(f"object ownership mismatch: {object_id}")
        for rep_id, vector in embeddings:
            rep = session.scalar(
                select(Representation).where(
                    Representation.id == rep_id,
                    Representation.object_id == object_id,
                )
            )
            if rep is None:
                continue
            rep.embedding = vector
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
