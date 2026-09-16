from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Object, Representation
from app.llm.embedding_service import EmbeddingService
from app.llm.summarizer import FakeSummarizer, Summarizer
from app.local.bounded_io import (
    bounded_parquet_stats,
    read_bounded_text,
    read_csv_header,
    read_csv_sample_rows,
    read_parquet_sample_rows,
    read_parquet_schema,
    stream_csv_stats,
)
from app.services.bounded_chunks import (
    MAX_INDEXED_TEXT_CHUNKS,
    build_indexing_metadata,
    chunk_text,
    select_bounded_chunks,
)
from app.services.correlation_constants import (
    SEMANTIC_SUMMARY_MAX_CHARS,
    SEMANTIC_SUMMARY_METADATA_KEY,
    SEMANTIC_SUMMARY_REVISION_KEY,
)
from app.services.errors import NotFoundError
from app.services.representation_embedding import refresh_representation_embedding

SMALL_TEXT_MAX_CHARS = 500
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
MAX_SAMPLE_ROWS = 5

KIND_FULL = "full"
KIND_SUMMARY = "summary"
KIND_CHUNK = "chunk"
KIND_SAMPLE = "sample"
KIND_SCHEMA = "schema"
KIND_STATISTICS = "statistics"
KIND_CONVERSATION_STACK_SUMMARY = "conversation_stack_summary"
_PRESERVED_REPRESENTATION_KINDS = frozenset({KIND_CONVERSATION_STACK_SUMMARY})


class RepresentationService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        embedding_service: EmbeddingService | None = None,
        summarizer: Summarizer | None = None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._embedding_service = embedding_service
        self._summarizer = summarizer or FakeSummarizer()

    def list_for_object(self, object_id: UUID) -> list[Representation]:
        self._get_object(object_id)
        return list(
            self._session.scalars(
                select(Representation)
                .where(Representation.object_id == object_id)
                .order_by(Representation.kind, Representation.part_index)
            ).all()
        )

    def ingest_text_content(self, object_id: UUID, text: str) -> list[Representation]:
        obj = self._get_object(object_id)
        reps = self._build_text_representations(obj, text)
        result = self._replace_representations(object_id, reps)
        stripped = text.strip()
        if len(stripped) <= SMALL_TEXT_MAX_CHARS:
            self._mirror_small_text_summary(obj, stripped)
        return result

    def ingest_file(self, object_id: UUID, path: Path) -> list[Representation]:
        obj = self._get_object(object_id)
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md"}:
            text, source_meta = read_bounded_text(path)
            reps = self._build_text_representations(obj, text, source_meta=source_meta)
        elif suffix == ".csv":
            reps = self._build_csv_representations(obj, path)
        elif suffix == ".parquet":
            reps = self._build_parquet_representations(obj, path)
        else:
            raise ValueError(f"unsupported file format: {suffix}")
        return self._replace_representations(object_id, reps)

    def _get_object(self, object_id: UUID) -> Object:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if obj is None:
            raise NotFoundError("object", object_id)
        return obj

    def _mirror_small_text_summary(self, obj: Object, text: str) -> None:
        metadata = dict(obj.metadata_ or {})
        revision = metadata.get("content_revision")
        if revision is None:
            return
        metadata[SEMANTIC_SUMMARY_METADATA_KEY] = text[:SEMANTIC_SUMMARY_MAX_CHARS]
        metadata[SEMANTIC_SUMMARY_REVISION_KEY] = revision
        obj.metadata_ = metadata
        self._session.flush()

    def _replace_representations(
        self, object_id: UUID, reps: list[Representation]
    ) -> list[Representation]:
        self._session.execute(
            delete(Representation).where(
                Representation.object_id == object_id,
                Representation.kind.notin_(tuple(_PRESERVED_REPRESENTATION_KINDS)),
            )
        )
        for rep in reps:
            self._session.add(rep)
        self._session.flush()
        return reps

    def _build_text_representations(
        self,
        obj: Object,
        text: str,
        source_meta: dict | None = None,
    ) -> list[Representation]:
        extra_meta = source_meta or {}
        if len(text) <= SMALL_TEXT_MAX_CHARS:
            return [
                Representation(
                    object_id=obj.id,
                    kind=KIND_FULL,
                    text=text,
                    metadata_=extra_meta,
                )
            ]

        reps: list[Representation] = [
            Representation(
                object_id=obj.id,
                kind=KIND_SUMMARY,
                text=self._summarizer.summarize(text),
                metadata_=extra_meta,
            )
        ]
        all_chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
        selected_chunks, selected_indices = select_bounded_chunks(
            all_chunks, MAX_INDEXED_TEXT_CHUNKS
        )
        indexing_meta = build_indexing_metadata(
            source_chars=len(text),
            total_chunks=len(all_chunks),
            indexed_chunks=len(selected_chunks),
        )
        for part_index, (source_index, chunk) in enumerate(
            zip(selected_indices, selected_chunks, strict=True)
        ):
            rep = Representation(
                object_id=obj.id,
                kind=KIND_CHUNK,
                part_index=part_index,
                text=chunk,
                metadata_={
                    **indexing_meta,
                    **extra_meta,
                    "source_chunk_index": source_index,
                },
            )
            if self._embedding_service is not None:
                refresh_representation_embedding(rep, self._embedding_service, chunk)
            reps.append(rep)
        return reps

    def _build_csv_representations(self, obj: Object, path: Path) -> list[Representation]:
        fieldnames = read_csv_header(path)
        _, sample_rows = read_csv_sample_rows(path, MAX_SAMPLE_ROWS)
        stats_meta, stats_lines, column_types = stream_csv_stats(path, fieldnames)
        schema_text = _format_schema_text(fieldnames, column_types)
        schema_rep = Representation(
            object_id=obj.id,
            kind=KIND_SCHEMA,
            text=schema_text,
            metadata_={
                "columns": [
                    {"name": name, "type": column_types[name]} for name in fieldnames
                ]
            },
        )

        sample_rep = Representation(
            object_id=obj.id,
            kind=KIND_SAMPLE,
            text=_format_sample_text(sample_rows, fieldnames),
            metadata_={"row_count_in_sample": len(sample_rows)},
        )

        stats_rep = Representation(
            object_id=obj.id,
            kind=KIND_STATISTICS,
            text="\n".join(stats_lines),
            metadata_=stats_meta,
        )
        return [schema_rep, sample_rep, stats_rep]

    def _build_parquet_representations(self, obj: Object, path: Path) -> list[Representation]:
        fieldnames, column_types, row_count = read_parquet_schema(path)
        _, sample_rows = read_parquet_sample_rows(path, MAX_SAMPLE_ROWS)
        stats_meta, stats_lines = bounded_parquet_stats(
            path, fieldnames, column_types, row_count
        )

        schema_rep = Representation(
            object_id=obj.id,
            kind=KIND_SCHEMA,
            text=_format_schema_text(fieldnames, column_types),
            metadata_={
                "columns": [
                    {"name": name, "type": column_types[name]} for name in fieldnames
                ]
            },
        )
        sample_rep = Representation(
            object_id=obj.id,
            kind=KIND_SAMPLE,
            text=_format_sample_text(sample_rows, fieldnames),
            metadata_={"row_count_in_sample": len(sample_rows)},
        )
        stats_rep = Representation(
            object_id=obj.id,
            kind=KIND_STATISTICS,
            text="\n".join(stats_lines),
            metadata_=stats_meta,
        )
        return [schema_rep, sample_rep, stats_rep]


def _format_schema_text(fieldnames: list[str], column_types: dict[str, str]) -> str:
    lines = [f"{name}: {column_types.get(name, 'string')}" for name in fieldnames]
    return "schema\n" + "\n".join(lines)


def _format_sample_text(rows: list[dict[str, object]], fieldnames: list[str]) -> str:
    if not fieldnames:
        return "sample\n(empty)"
    lines = ["sample", ",".join(fieldnames)]
    for row in rows:
        lines.append(",".join(str(row.get(name, "")) for name in fieldnames))
    return "\n".join(lines)
