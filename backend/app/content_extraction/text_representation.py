"""Shared bounded text representation builders for mechanical extraction."""

from typing import Any

from app.content_extraction.constants import (
    MAX_EXTRACTED_TEXT_CHARS,
    MAX_REPRESENTATION_PART_BYTES,
)
from app.db.models import Representation
from app.services.bounded_chunks import (
    MAX_INDEXED_TEXT_CHUNKS,
    build_indexing_metadata,
    chunk_text,
    select_bounded_chunks,
)
from app.services.representation_service import KIND_CHUNK, KIND_FULL, SMALL_TEXT_MAX_CHARS


def cap_structural_text(
    text: str,
    max_bytes: int = MAX_REPRESENTATION_PART_BYTES,
) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def cap_text(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_EXTRACTED_TEXT_CHARS:
        return text, False
    return text[:MAX_EXTRACTED_TEXT_CHARS], True


def build_bounded_text_representations(
    object_id,
    text: str,
    max_parts: int,
    source_meta: dict[str, Any] | None = None,
) -> tuple[list[Representation], bool]:
    """Build full/chunk reps using only the remaining mechanical part budget."""
    if max_parts <= 0 or not text.strip():
        return [], False

    extra_meta = dict(source_meta or {})
    capped, truncated = cap_text(text)
    if len(capped) <= SMALL_TEXT_MAX_CHARS:
        return [
            Representation(
                object_id=object_id,
                kind=KIND_FULL,
                text=capped,
                metadata_={**extra_meta, "truncated": truncated},
            )
        ], truncated

    all_chunks = chunk_text(capped, 800, 100)
    max_chunks = min(max_parts, MAX_INDEXED_TEXT_CHUNKS)
    selected_chunks, selected_indices = select_bounded_chunks(all_chunks, max_chunks)
    indexing_meta = build_indexing_metadata(
        source_chars=len(capped),
        total_chunks=len(all_chunks),
        indexed_chunks=len(selected_chunks),
    )
    reps: list[Representation] = []
    for part_index, (source_index, chunk) in enumerate(
        zip(selected_indices, selected_chunks, strict=True)
    ):
        reps.append(
            Representation(
                object_id=object_id,
                kind=KIND_CHUNK,
                part_index=part_index,
                text=chunk,
                metadata_={
                    **indexing_meta,
                    **extra_meta,
                    "truncated": truncated,
                    "source_chunk_index": source_index,
                },
            )
        )
    return reps, truncated or indexing_meta["indexing_truncated"]


def build_text_representations(
    object_id,
    text: str,
    source_meta: dict[str, Any] | None = None,
) -> tuple[list[Representation], bool]:
    extra_meta = dict(source_meta or {})
    capped, truncated = cap_text(text)
    if len(capped) <= SMALL_TEXT_MAX_CHARS:
        return [
            Representation(
                object_id=object_id,
                kind=KIND_FULL,
                text=capped,
                metadata_={**extra_meta, "truncated": truncated},
            )
        ], truncated

    all_chunks = chunk_text(capped, 800, 100)
    selected_chunks, selected_indices = select_bounded_chunks(
        all_chunks, MAX_INDEXED_TEXT_CHUNKS
    )
    indexing_meta = build_indexing_metadata(
        source_chars=len(capped),
        total_chunks=len(all_chunks),
        indexed_chunks=len(selected_chunks),
    )
    reps: list[Representation] = []
    for part_index, (source_index, chunk) in enumerate(
        zip(selected_indices, selected_chunks, strict=True)
    ):
        reps.append(
            Representation(
                object_id=object_id,
                kind=KIND_CHUNK,
                part_index=part_index,
                text=chunk,
                metadata_={
                    **indexing_meta,
                    **extra_meta,
                    "truncated": truncated,
                    "source_chunk_index": source_index,
                },
            )
        )
    return reps, truncated
