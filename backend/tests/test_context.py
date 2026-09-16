from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.api.schemas import EdgeCreate, ObjectCreate
from app.llm.concept_stub_embedding import ConceptStubEmbeddingService
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.summarizer import FakeSummarizer
from app.services.context_service import DEFAULT_MAX_CHARS, ContextService
from app.services.graph_service import GraphService
from app.services.representation_service import (
    KIND_CHUNK,
    KIND_FULL,
    KIND_SAMPLE,
    KIND_SCHEMA,
    KIND_STATISTICS,
    KIND_SUMMARY,
    RepresentationService,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture
def fake_embedding_service() -> FakeEmbeddingService:
    return FakeEmbeddingService()


@pytest.fixture
def context_service(db_session, fake_embedding_service) -> ContextService:
    return ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)


def _ingest_long_document(
    db_session,
    embedding_service: FakeEmbeddingService,
    title: str = "Budget report",
    uri: str = "file:///data/budget-report.md",
) -> tuple:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, embedding_service)
    doc = graph.create_object(
        ObjectCreate(
            kind="document",
            title=title,
            origin="system",
            canonical_uri=uri,
        )
    )
    rep_service = RepresentationService(
        db_session,
        BOOTSTRAP_USER_ID,
        embedding_service=embedding_service,
        summarizer=FakeSummarizer(max_chars=120),
    )
    long_text = (
        "Budget planning section with revenue targets and expense review. "
        * 80
    )
    rep_service.ingest_text_content(doc.id, long_text)
    return graph, doc, long_text


def test_task_linked_to_long_document_context(
    db_session, fake_embedding_service: FakeEmbeddingService
) -> None:
    graph, doc, _ = _ingest_long_document(db_session, fake_embedding_service)
    task = graph.create_object(
        ObjectCreate(kind="task", title="Review quarterly budget", origin="system")
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=doc.id,
            type="related_to",
            origin="system",
            state="observed",
        )
    )

    service = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    result = service.build_context(
        object_id=task.id,
        query="budget revenue review",
        max_chars=DEFAULT_MAX_CHARS,
    )

    kinds = {item.kind for item in result.items}
    titles = {item.title for item in result.items}
    repr_kinds = {item.representation_kind for item in result.items if item.representation_kind}

    assert "task" in kinds
    assert "Review quarterly budget" in titles
    assert "document" in kinds
    assert doc.canonical_uri in {
        item.canonical_uri for item in result.items if item.canonical_uri
    }
    assert KIND_SUMMARY in repr_kinds
    assert KIND_CHUNK in repr_kinds
    assert KIND_FULL not in repr_kinds


def test_context_contains_document_reference_and_summary(
    db_session, fake_embedding_service: FakeEmbeddingService
) -> None:
    graph, doc, _ = _ingest_long_document(
        db_session,
        fake_embedding_service,
        uri="file:///refs/budget.md",
    )
    task = graph.create_object(ObjectCreate(kind="task", title="Budget task", origin="system"))
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=doc.id,
            type="attached_to",
            origin="system",
            state="observed",
        )
    )

    result = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service).build_context(
        object_id=task.id,
        query="budget",
    )

    reference_items = [
        item
        for item in result.items
        if item.object_id == doc.id and item.representation_kind is None
    ]
    summary_items = [
        item for item in result.items if item.representation_kind == KIND_SUMMARY
    ]

    assert reference_items
    assert "file:///refs/budget.md" in reference_items[0].content
    assert summary_items
    assert summary_items[0].content


def test_context_contains_only_bounded_chunks(
    db_session, fake_embedding_service: FakeEmbeddingService
) -> None:
    graph, doc, long_text = _ingest_long_document(db_session, fake_embedding_service)
    task = graph.create_object(ObjectCreate(kind="task", title="Chunk task", origin="system"))
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=doc.id,
            type="related_to",
            origin="system",
            state="observed",
        )
    )

    rep_service = RepresentationService(db_session, BOOTSTRAP_USER_ID, embedding_service=fake_embedding_service)
    all_chunks = [
        rep
        for rep in rep_service.list_for_object(doc.id)
        if rep.kind == KIND_CHUNK
    ]

    result = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service).build_context(
        object_id=task.id,
        query="expense revenue planning",
    )
    chunk_items = [
        item for item in result.items if item.representation_kind == KIND_CHUNK
    ]

    assert len(chunk_items) <= 8
    if len(all_chunks) > 8:
        assert len(chunk_items) < len(all_chunks)
    assert long_text not in " ".join(item.content for item in result.items)


def test_context_does_not_contain_full_large_document(
    db_session, fake_embedding_service: FakeEmbeddingService
) -> None:
    graph, doc, long_text = _ingest_long_document(db_session, fake_embedding_service)
    task = graph.create_object(ObjectCreate(kind="task", title="No full doc", origin="system"))
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=doc.id,
            type="related_to",
            origin="system",
            state="observed",
        )
    )

    result = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service).build_context(
        object_id=task.id,
        query="budget",
    )

    assert long_text not in "\n".join(item.content for item in result.items)
    assert KIND_FULL not in {
        item.representation_kind for item in result.items if item.representation_kind
    }


def test_max_chars_is_respected(db_session, fake_embedding_service: FakeEmbeddingService) -> None:
    graph, doc, _ = _ingest_long_document(db_session, fake_embedding_service)
    task = graph.create_object(ObjectCreate(kind="task", title="Budget cap", origin="system"))
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=doc.id,
            type="related_to",
            origin="system",
            state="observed",
        )
    )

    max_chars = 400
    service = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    result = service.build_context(object_id=task.id, query="budget revenue", max_chars=max_chars)

    assert result.total_chars <= max_chars
    assert result.truncated


def test_small_budget_excludes_unrelated_semantic_candidates(db_session) -> None:
    stub = ConceptStubEmbeddingService()
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, stub)
    graph.create_object(
        ObjectCreate(
            kind="note",
            title="Solar energy roadmap unrelated",
            origin="system",
        )
    )
    graph, doc, _ = _ingest_long_document(db_session, stub)
    task = graph.create_object(ObjectCreate(kind="task", title="Finance task", origin="system"))
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=doc.id,
            type="related_to",
            origin="system",
            state="observed",
        )
    )

    result = ContextService(db_session, BOOTSTRAP_USER_ID, stub).build_context(
        object_id=task.id,
        query="budget revenue planning",
        max_chars=500,
    )

    titles = {item.title for item in result.items}
    assert "Solar energy roadmap unrelated" not in titles
    assert "Finance task" in titles


def test_dataset_context_uses_schema_sample_statistics_not_full(
    db_session, fake_embedding_service: FakeEmbeddingService, tmp_path: Path
) -> None:
    csv_path = tmp_path / "metrics.csv"
    rows = ["id,value"] + [f"{index},{index * 10}" for index in range(50)]
    csv_path.write_text("\n".join(rows), encoding="utf-8")

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    dataset = graph.create_object(
        ObjectCreate(
            kind="dataset",
            title="Sales metrics",
            origin="system",
            canonical_uri=str(csv_path),
        )
    )
    task = graph.create_object(ObjectCreate(kind="task", title="Analyze sales", origin="system"))
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=dataset.id,
            type="related_to",
            origin="system",
            state="observed",
        )
    )

    RepresentationService(db_session, BOOTSTRAP_USER_ID, embedding_service=fake_embedding_service).ingest_file(
        dataset.id, csv_path
    )

    result = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service).build_context(
        object_id=task.id,
        query="sales metrics",
    )
    repr_kinds = {
        item.representation_kind for item in result.items if item.representation_kind
    }

    assert KIND_SCHEMA in repr_kinds
    assert KIND_SAMPLE in repr_kinds
    assert KIND_STATISTICS in repr_kinds
    assert KIND_FULL not in repr_kinds
    assert "49,490" not in "\n".join(item.content for item in result.items)


def test_dataset_parquet_context_policy(
    db_session, fake_embedding_service: FakeEmbeddingService, tmp_path: Path
) -> None:
    parquet_path = tmp_path / "metrics.parquet"
    table = pa.table({"name": ["a", "b"], "value": [1, 2]})
    pq.write_table(table, parquet_path)

    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    dataset = graph.create_object(
        ObjectCreate(
            kind="dataset",
            title="Parquet metrics",
            origin="system",
            canonical_uri=str(parquet_path),
        )
    )
    task = graph.create_object(ObjectCreate(kind="task", title="Parquet task", origin="system"))
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=dataset.id,
            type="related_to",
            origin="system",
            state="observed",
        )
    )
    RepresentationService(db_session, BOOTSTRAP_USER_ID, embedding_service=fake_embedding_service).ingest_file(
        dataset.id, parquet_path
    )

    result = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service).build_context(object_id=task.id)
    repr_kinds = {
        item.representation_kind for item in result.items if item.representation_kind
    }
    assert repr_kinds == {KIND_SCHEMA, KIND_SAMPLE, KIND_STATISTICS}


def test_build_context_stable_ordering(db_session, fake_embedding_service: FakeEmbeddingService) -> None:
    graph, doc, _ = _ingest_long_document(db_session, fake_embedding_service)
    task = graph.create_object(ObjectCreate(kind="task", title="Stable task", origin="system"))
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=doc.id,
            type="related_to",
            origin="system",
            state="observed",
        )
    )

    service = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    first = service.build_context(object_id=task.id, query="budget expense")
    second = service.build_context(object_id=task.id, query="budget expense")

    first_keys = [
        (
            item.object_id,
            item.representation_kind,
            item.relation_type,
            item.title,
            item.content,
        )
        for item in first.items
    ]
    second_keys = [
        (
            item.object_id,
            item.representation_kind,
            item.relation_type,
            item.title,
            item.content,
        )
        for item in second.items
    ]
    assert first_keys == second_keys


def test_reingest_replaces_previous_representations(
    db_session, fake_embedding_service: FakeEmbeddingService
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    obj = graph.create_object(
        ObjectCreate(kind="document", title="Re-ingest doc", origin="system")
    )
    service = RepresentationService(
        db_session,
        BOOTSTRAP_USER_ID,
        embedding_service=fake_embedding_service,
        summarizer=FakeSummarizer(max_chars=80),
    )

    service.ingest_text_content(obj.id, "small text")
    after_small = service.list_for_object(obj.id)
    assert len(after_small) == 1
    assert after_small[0].kind == KIND_FULL

    long_text = "segment " * 200
    service.ingest_text_content(obj.id, long_text)
    final_reps = service.list_for_object(obj.id)
    kinds = {rep.kind for rep in final_reps}

    assert KIND_FULL not in kinds
    assert KIND_SUMMARY in kinds
    assert KIND_CHUNK in kinds
    assert len([rep for rep in final_reps if rep.kind == KIND_CHUNK]) > 1
