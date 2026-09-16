from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import func, select

from app.api.schemas import ObjectCreate
from app.db.models import Object, Representation
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.summarizer import FakeSummarizer
from app.services.graph_service import GraphService
from app.services.representation_service import (
    KIND_CHUNK,
    KIND_FULL,
    KIND_SAMPLE,
    KIND_SCHEMA,
    KIND_STATISTICS,
    KIND_SUMMARY,
    MAX_INDEXED_TEXT_CHUNKS,
    SMALL_TEXT_MAX_CHARS,
    RepresentationService,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID


class FailingEmbeddingService:
    def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding provider unavailable")


@pytest.fixture
def fake_embedding_service() -> FakeEmbeddingService:
    return FakeEmbeddingService()


@pytest.fixture
def representation_service(db_session, fake_embedding_service) -> RepresentationService:
    return RepresentationService(
        db_session,
        BOOTSTRAP_USER_ID,
        embedding_service=fake_embedding_service,
        summarizer=FakeSummarizer(max_chars=80),
    )


def _create_resource_object(
    db_session,
    title: str = "Resource",
    canonical_uri: str | None = None,
) -> Object:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    return graph.create_object(
        ObjectCreate(
            kind="document",
            title=title,
            origin="system",
            canonical_uri=canonical_uri,
        )
    )


def test_small_text_creates_full_representation(
    db_session, representation_service: RepresentationService
) -> None:
    obj = _create_resource_object(db_session)
    text = "Short note for the secretary."
    reps = representation_service.ingest_text_content(obj.id, text)

    assert len(reps) == 1
    assert reps[0].kind == KIND_FULL
    assert reps[0].text == text


def test_long_text_creates_summary_and_chunks(
    db_session, representation_service: RepresentationService
) -> None:
    obj = _create_resource_object(db_session)
    text = "segment " * 200
    reps = representation_service.ingest_text_content(obj.id, text)

    kinds = {rep.kind for rep in reps}
    assert KIND_SUMMARY in kinds
    chunk_reps = [rep for rep in reps if rep.kind == KIND_CHUNK]
    assert len(chunk_reps) > 1
    assert len(chunk_reps) <= MAX_INDEXED_TEXT_CHUNKS
    assert all(rep.part_index is not None for rep in chunk_reps)


def test_large_text_caps_indexed_chunks_and_marks_truncation(
    db_session, representation_service: RepresentationService
) -> None:
    obj = _create_resource_object(db_session, canonical_uri="file:///data/huge.txt")
    text = "word " * 25000
    reps = representation_service.ingest_text_content(obj.id, text)
    chunk_reps = [rep for rep in reps if rep.kind == KIND_CHUNK]

    assert len(chunk_reps) == MAX_INDEXED_TEXT_CHUNKS
    assert chunk_reps[0].metadata_["indexing_truncated"] is True
    assert chunk_reps[0].metadata_["total_chunks"] > MAX_INDEXED_TEXT_CHUNKS
    assert chunk_reps[0].metadata_["source_chars"] == len(text)
    db_session.refresh(obj)
    assert obj.canonical_uri == "file:///data/huge.txt"


def test_bounded_chunks_include_document_beginning_and_end(
    db_session, representation_service: RepresentationService
) -> None:
    obj = _create_resource_object(db_session)
    text = "BEGIN_TOKEN " + ("middle " * 20000) + "END_TOKEN"
    reps = representation_service.ingest_text_content(obj.id, text)
    chunk_reps = [rep for rep in reps if rep.kind == KIND_CHUNK]
    assert chunk_reps[0].text.startswith("BEGIN_TOKEN")
    assert chunk_reps[-1].text.endswith("END_TOKEN")


def test_long_document_retains_canonical_uri(
    db_session, representation_service: RepresentationService
) -> None:
    uri = "file:///data/projects/long-report.md"
    obj = _create_resource_object(db_session, canonical_uri=uri)
    representation_service.ingest_text_content(obj.id, "word " * 300)

    db_session.refresh(obj)
    assert obj.canonical_uri == uri


def test_csv_creates_schema_and_sample(tmp_path: Path, db_session, fake_embedding_service) -> None:
    csv_path = tmp_path / "metrics.csv"
    csv_path.write_text("name,value\nalpha,1\nbeta,2\n", encoding="utf-8")

    obj = _create_resource_object(db_session, canonical_uri=str(csv_path))
    service = RepresentationService(db_session, BOOTSTRAP_USER_ID, embedding_service=fake_embedding_service)
    reps = service.ingest_file(obj.id, csv_path)

    kinds = {rep.kind for rep in reps}
    assert KIND_SCHEMA in kinds
    assert KIND_SAMPLE in kinds
    assert KIND_STATISTICS in kinds
    schema_rep = next(rep for rep in reps if rep.kind == KIND_SCHEMA)
    assert "name" in schema_rep.text
    assert "value" in schema_rep.text


def test_csv_does_not_create_full_representation(
    tmp_path: Path, db_session, fake_embedding_service
) -> None:
    csv_path = tmp_path / "large.csv"
    rows = ["id,value"] + [f"{index},{index}" for index in range(100)]
    csv_path.write_text("\n".join(rows), encoding="utf-8")

    obj = _create_resource_object(db_session)
    service = RepresentationService(db_session, BOOTSTRAP_USER_ID, embedding_service=fake_embedding_service)
    reps = service.ingest_file(obj.id, csv_path)

    assert KIND_FULL not in {rep.kind for rep in reps}
    sample_rep = next(rep for rep in reps if rep.kind == KIND_SAMPLE)
    assert sample_rep.text.count("\n") <= 6


def test_parquet_follows_dataset_policy(tmp_path: Path, db_session, fake_embedding_service) -> None:
    parquet_path = tmp_path / "metrics.parquet"
    table = pa.table(
        {
            "name": ["alpha", "beta", "gamma"],
            "value": [1, 2, 3],
        }
    )
    pq.write_table(table, parquet_path)

    obj = _create_resource_object(db_session, canonical_uri=str(parquet_path))
    service = RepresentationService(db_session, BOOTSTRAP_USER_ID, embedding_service=fake_embedding_service)
    reps = service.ingest_file(obj.id, parquet_path)

    kinds = {rep.kind for rep in reps}
    assert kinds == {KIND_SCHEMA, KIND_SAMPLE, KIND_STATISTICS}
    stats_rep = next(rep for rep in reps if rep.kind == KIND_STATISTICS)
    assert stats_rep.metadata_["row_count"] == 3
    assert stats_rep.metadata_["column_count"] == 2


def test_deleting_object_cascades_representations(
    db_session, representation_service: RepresentationService
) -> None:
    obj = _create_resource_object(db_session)
    representation_service.ingest_text_content(obj.id, "cascade check")

    rep_count = db_session.scalar(
        select(func.count()).select_from(Representation).where(Representation.object_id == obj.id)
    )
    assert rep_count == 1

    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    graph.delete_object(obj.id)
    db_session.expire_all()

    remaining = db_session.scalar(select(func.count()).select_from(Representation))
    assert remaining == 0


def test_chunk_representations_use_embedding_service(
    db_session, fake_embedding_service: FakeEmbeddingService
) -> None:
    obj = _create_resource_object(db_session)
    service = RepresentationService(db_session, BOOTSTRAP_USER_ID, embedding_service=fake_embedding_service)
    text = "x" * (SMALL_TEXT_MAX_CHARS + 50)
    reps = service.ingest_text_content(obj.id, text)

    chunk_reps = [rep for rep in reps if rep.kind == KIND_CHUNK]
    assert chunk_reps
    assert all(rep.embedding is not None for rep in chunk_reps)
    assert all(len(rep.embedding) > 0 for rep in chunk_reps)


def test_patch_metadata_refreshes_object_embedding(db_session, fake_embedding_service) -> None:
    from app.api.schemas import ObjectUpdate

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    obj = graph.create_object(
        ObjectCreate(
            kind="note",
            title="Stable title",
            origin="system",
            metadata={"location": "alpha"},
        )
    )
    before = list(obj.embedding or [])

    graph.update_object(obj.id, ObjectUpdate(metadata={"location": "beta"}))
    db_session.refresh(obj)

    assert obj.embedding is not None
    assert list(obj.embedding) != before


def test_create_object_survives_embedding_failure(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, FailingEmbeddingService())
    obj = graph.create_object(
        ObjectCreate(kind="task", title="Keep me", body="details", origin="system")
    )
    db_session.refresh(obj)
    assert obj.id is not None
    assert obj.embedding is None
    assert obj.embedding_signature is None


def test_update_clears_stale_embedding_on_failure(db_session, fake_embedding_service) -> None:
    from app.api.schemas import ObjectUpdate

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    obj = graph.create_object(ObjectCreate(kind="task", title="Original", origin="system"))
    assert obj.embedding is not None

    failing_graph = GraphService(db_session, BOOTSTRAP_USER_ID, FailingEmbeddingService())
    failing_graph.update_object(obj.id, ObjectUpdate(title="Changed title"))
    db_session.refresh(obj)
    assert obj.embedding is None
    assert obj.embedding_signature is None


def test_non_searchable_patch_does_not_refresh_embedding(
    db_session, fake_embedding_service: FakeEmbeddingService
) -> None:
    from app.api.schemas import ObjectUpdate

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    obj = graph.create_object(
        ObjectCreate(kind="task", title="Title", origin="system", status="open")
    )
    before = list(obj.embedding or [])

    graph.update_object(obj.id, ObjectUpdate(status="done"))
    db_session.refresh(obj)

    assert obj.status == "done"
    assert [round(value, 5) for value in obj.embedding or []] == [
        round(value, 5) for value in before
    ]
