"""Semantic summary generation and metadata mirroring."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Object, Representation
from app.llm.summarizer import FakeSummarizer, Summarizer
from app.services.bounded_chunks import select_bounded_chunk_indices
from app.services.correlation_constants import (
    SEMANTIC_SUMMARY_INPUT_MAX_CHARS,
    SEMANTIC_SUMMARY_MAX_CHARS,
    SEMANTIC_SUMMARY_METADATA_KEY,
    SEMANTIC_SUMMARY_REVISION_KEY,
)
from app.services.errors import NotFoundError
from app.services.representation_generation import (
    get_representation_generation,
    representation_generation_matches,
)
from app.services.representation_service import (
    KIND_CHUNK,
    KIND_FULL,
    KIND_SAMPLE,
    KIND_SCHEMA,
    KIND_STATISTICS,
    KIND_SUMMARY,
    SMALL_TEXT_MAX_CHARS,
    RepresentationService,
)

_MAX_SUMMARY_CHUNKS = 8


def invalidate_semantic_summary_metadata(metadata: dict) -> dict:
    cleaned = dict(metadata)
    cleaned.pop(SEMANTIC_SUMMARY_METADATA_KEY, None)
    cleaned.pop(SEMANTIC_SUMMARY_REVISION_KEY, None)
    return cleaned


class SemanticSummaryService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        summarizer: Summarizer | None = None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._summarizer = summarizer or FakeSummarizer(max_chars=SEMANTIC_SUMMARY_MAX_CHARS)
        self._representations = RepresentationService(session, user_id)

    def update_summary_for_object(
        self,
        object_id: UUID,
        *,
        expected_revision: str | None = None,
        expected_representation_generation: int | None = None,
    ) -> str | None:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if obj is None:
            raise NotFoundError("object", object_id)

        metadata = dict(obj.metadata_ or {})
        revision = expected_revision if expected_revision is not None else metadata.get("content_revision")
        generation = (
            expected_representation_generation
            if expected_representation_generation is not None
            else get_representation_generation(metadata)
        )
        if revision is None:
            return None
        if not representation_generation_matches(metadata, revision, generation):
            return None

        reps = self._representations.list_for_object(object_id)
        summary_input = self._build_summary_input(obj, reps)
        if not summary_input:
            return None

        if len(summary_input.strip()) <= SMALL_TEXT_MAX_CHARS:
            summary_text = summary_input.strip()[:SEMANTIC_SUMMARY_MAX_CHARS]
        else:
            summary_text = self._summarizer.summarize(summary_input)

        self._session.refresh(obj)
        current_metadata = dict(obj.metadata_ or {})
        if not representation_generation_matches(
            current_metadata,
            revision,
            generation,
        ):
            return None

        summary_text = summary_text[:SEMANTIC_SUMMARY_MAX_CHARS]
        reps = self._representations.list_for_object(object_id)
        self._upsert_summary_representation(object_id, summary_text, reps)
        current_metadata[SEMANTIC_SUMMARY_METADATA_KEY] = summary_text
        current_metadata[SEMANTIC_SUMMARY_REVISION_KEY] = revision
        obj.metadata_ = current_metadata
        self._session.flush()
        return summary_text

    def _build_summary_input(self, obj: Object, reps: list[Representation]) -> str:
        if obj.kind == "dataset":
            ordered_kinds = [KIND_SCHEMA, KIND_STATISTICS, KIND_SAMPLE]
            parts: list[str] = []
            total = 0
            for kind in ordered_kinds:
                for rep in reps:
                    if rep.kind != kind:
                        continue
                    text = rep.text or ""
                    if not text:
                        continue
                    if total + len(text) > SEMANTIC_SUMMARY_INPUT_MAX_CHARS:
                        remaining = SEMANTIC_SUMMARY_INPUT_MAX_CHARS - total
                        if remaining > 0:
                            parts.append(text[:remaining])
                        return "\n".join(parts).strip()
                    parts.append(text)
                    total += len(text) + 1
                if total >= SEMANTIC_SUMMARY_INPUT_MAX_CHARS:
                    break
            return "\n".join(parts).strip()

        full_text = None
        for rep in reps:
            if rep.kind == KIND_FULL:
                full_text = rep.text
                break
        if full_text and len(full_text.strip()) <= SMALL_TEXT_MAX_CHARS:
            return full_text

        chunk_texts = [rep.text for rep in reps if rep.kind == KIND_CHUNK and rep.text]
        if chunk_texts:
            return self._bounded_chunks_input(chunk_texts)

        if full_text:
            return full_text[:SEMANTIC_SUMMARY_INPUT_MAX_CHARS]
        if obj.body:
            return obj.body[:SEMANTIC_SUMMARY_INPUT_MAX_CHARS]
        for rep in reps:
            if rep.kind == KIND_SUMMARY:
                return rep.text
        return obj.title

    def _bounded_chunks_input(self, chunks: list[str]) -> str:
        max_chunks = min(len(chunks), _MAX_SUMMARY_CHUNKS)
        indices = select_bounded_chunk_indices(len(chunks), max_chunks)
        parts: list[str] = []
        total = 0
        for index in indices:
            chunk = chunks[index]
            if total + len(chunk) > SEMANTIC_SUMMARY_INPUT_MAX_CHARS:
                remaining = SEMANTIC_SUMMARY_INPUT_MAX_CHARS - total
                if remaining > 0:
                    parts.append(chunk[:remaining])
                break
            parts.append(chunk)
            total += len(chunk) + 1
        return "\n".join(parts)

    def _upsert_summary_representation(
        self,
        object_id: UUID,
        summary_text: str,
        reps: list[Representation],
    ) -> None:
        existing = next((rep for rep in reps if rep.kind == KIND_SUMMARY), None)
        if existing is not None:
            existing.text = summary_text
            return
        if any(rep.kind == KIND_FULL for rep in reps):
            self._session.add(
                Representation(
                    object_id=object_id,
                    kind=KIND_SUMMARY,
                    text=summary_text,
                    metadata_={},
                )
            )
            return
        self._session.execute(
            delete(Representation).where(
                Representation.object_id == object_id,
                Representation.kind == KIND_SUMMARY,
            )
        )
        self._session.add(
            Representation(
                object_id=object_id,
                kind=KIND_SUMMARY,
                text=summary_text,
                metadata_={},
            )
        )
