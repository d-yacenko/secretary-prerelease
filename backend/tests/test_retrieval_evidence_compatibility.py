"""Retrieval/context compatibility with large document representations."""

import uuid

from app.api.schemas import ObjectCreate
from app.db.models import Representation
from app.llm.embedding_text import EMBEDDING_DIMENSION
from app.llm.embedding_service import FakeEmbeddingService
from app.services.context_service import DEFAULT_MAX_CHARS, ContextService
from app.services.graph_service import GraphService
from app.services.representation_service import KIND_CHUNK
from app.services.retrieval_constants import SHORT_EXCERPT_MAX_CHARS, TIME_SCOPE_ALL
from app.services.retrieval_service import RetrievalService
from app.users.bootstrap import BOOTSTRAP_USER_ID

EXACT_CODE_LINE = 'print(f"RES_GROUP concurence:{max_workers}")'
SLIDE_MARKER = "[slide 115]"
SLIDE_PHRASE = (
    "Ручные действия вне ADCM опасны: можно рассинхронизировать "
    "ADB, ADBM, ADB Control и конфигурацию кластера."
)


def _create_object(
    db_session,
    *,
    kind: str = "document",
    title: str,
    body: str | None = None,
) -> uuid.UUID:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    obj = graph.create_object(
        ObjectCreate(
            kind=kind,
            title=title,
            body=body,
            origin="source",
            state="observed",
        )
    )
    db_session.flush()
    return obj.id


def _add_chunk(db_session, object_id: uuid.UUID, text: str, part_index: int = 0) -> None:
    db_session.add(
        Representation(
            object_id=object_id,
            kind=KIND_CHUNK,
            text=text,
            part_index=part_index,
            metadata_={},
        )
    )
    db_session.flush()


def _large_text_with_marker(marker: str, marker_offset: int, pad_char: str = "d") -> str:
    prefix = f"{pad_char * marker_offset}\n"
    suffix = f"\n{pad_char * 5000}"
    return f"{prefix}{marker}{suffix}"


def test_retrieval_excerpt_contains_exact_code_line_far_from_prefix(db_session) -> None:
    object_id = _create_object(
        db_session,
        title="ADBA2.odp",
        body="presentation archive",
    )
    source = _large_text_with_marker(EXACT_CODE_LINE, 9000)
    assert len(source) > 8000
    _add_chunk(db_session, object_id, source)

    query = f'Найди мне {EXACT_CODE_LINE}'
    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        query,
        time_scope=TIME_SCOPE_ALL,
        limit=5,
    ).hits
    qualified = [hit for hit in hits if hit.object_id == object_id]
    assert qualified, "expected object in retrieval hits"
    hit = qualified[0]
    assert EXACT_CODE_LINE in hit.short_excerpt
    assert len(hit.short_excerpt) <= SHORT_EXCERPT_MAX_CHARS
    assert not hit.short_excerpt.startswith(source[:100])


def test_relaxed_representation_only_atom_finds_object(db_session) -> None:
    unique_atom = "UNIQUE_REP_ATOM_ZEBRA_9911"
    object_id = _create_object(
        db_session,
        title="Neutral container title",
        body="Body without searchable unique terms here.",
    )
    source = _large_text_with_marker(unique_atom, 10000, pad_char="n")
    _add_chunk(db_session, object_id, source)

    query = f"Найди мне {unique_atom}"
    result = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        query,
        time_scope=TIME_SCOPE_ALL,
        limit=5,
    )
    hit_ids = {hit.object_id for hit in result.hits}
    assert object_id in hit_ids
    hit = next(hit for hit in result.hits if hit.object_id == object_id)
    assert unique_atom in hit.short_excerpt


def test_context_large_chunk_returns_bounded_evidence_window(db_session) -> None:
    target = "CONTEXT_TARGET_LITERAL_FAR_7788"
    object_id = _create_object(db_session, title="Large chunk doc", body="short body")
    source = _large_text_with_marker(target, 11000, pad_char="c")
    assert len(source) > DEFAULT_MAX_CHARS
    _add_chunk(db_session, object_id, source)

    result = ContextService(db_session, BOOTSTRAP_USER_ID).build_context(
        object_id=object_id,
        query=target,
        max_chars=DEFAULT_MAX_CHARS,
    )
    assert result.total_chars <= DEFAULT_MAX_CHARS
    joined = "\n".join(item.content for item in result.items)
    assert target in joined
    assert source not in joined
    chunk_items = [item for item in result.items if item.representation_kind == KIND_CHUNK]
    assert chunk_items
    assert len(chunk_items[0].content) < len(source)


def test_context_exact_chunk_ranks_above_semantic_embedding(db_session) -> None:
    target = "TARGET_LITERAL_ZEBRA"
    fake = FakeEmbeddingService()
    object_id = _create_object(db_session, title="Embedding rank doc", body="body")
    chunk_exact = Representation(
        object_id=object_id,
        kind=KIND_CHUNK,
        text=_large_text_with_marker(target, 7000, pad_char="a"),
        part_index=0,
        metadata_={},
    )
    chunk_semantic = Representation(
        object_id=object_id,
        kind=KIND_CHUNK,
        text="semantic planning budget revenue review " * 200,
        part_index=1,
        metadata_={},
    )
    query_vector = fake.embed(target)
    chunk_exact.embedding = [1.0] + [0.0] * (EMBEDDING_DIMENSION - 1)
    chunk_semantic.embedding = query_vector
    db_session.add(chunk_exact)
    db_session.add(chunk_semantic)
    db_session.flush()

    service = ContextService(db_session, BOOTSTRAP_USER_ID, fake)
    ranked = service._rank_chunks([chunk_semantic, chunk_exact], target)
    assert ranked[0].id == chunk_exact.id


def test_retrieval_and_context_keep_slide_marker_evidence(db_session) -> None:
    object_id = _create_object(
        db_session,
        title="ADCM deck",
        body="deck",
    )
    marker_block = f"{SLIDE_MARKER}\n{SLIDE_PHRASE}"
    source = _large_text_with_marker(marker_block, 9500, pad_char="p")
    _add_chunk(db_session, object_id, source)

    query = SLIDE_PHRASE
    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        query,
        time_scope=TIME_SCOPE_ALL,
        limit=5,
    ).hits
    hit = next((row for row in hits if row.object_id == object_id), None)
    assert hit is not None
    assert SLIDE_PHRASE in hit.short_excerpt
    assert SLIDE_MARKER in hit.short_excerpt or "slide 115" in hit.short_excerpt.lower()

    context = ContextService(db_session, BOOTSTRAP_USER_ID).build_context(
        object_id=object_id,
        query=query,
        max_chars=DEFAULT_MAX_CHARS,
    )
    joined = "\n".join(item.content for item in context.items)
    assert SLIDE_PHRASE in joined


def test_short_exact_adb_far_from_prefix_retrieve_and_context(db_session) -> None:
    object_id = _create_object(db_session, title="ADB deck", body="neutral")
    source = _large_text_with_marker(f"{SLIDE_MARKER}\nADB", 9500, pad_char="z")
    _add_chunk(db_session, object_id, source)

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "ADB",
        time_scope=TIME_SCOPE_ALL,
        limit=5,
    ).hits
    hit = next((row for row in hits if row.object_id == object_id), None)
    assert hit is not None
    assert "ADB" in hit.short_excerpt
    assert not hit.short_excerpt.startswith(source[:100])

    context = ContextService(db_session, BOOTSTRAP_USER_ID).build_context(
        object_id=object_id,
        query="ADB",
        max_chars=DEFAULT_MAX_CHARS,
    )
    chunk_items = [item for item in context.items if item.representation_kind == KIND_CHUNK]
    assert chunk_items
    assert "ADB" in chunk_items[0].content


def test_short_exact_adbm_far_from_prefix_retrieve(db_session) -> None:
    object_id = _create_object(db_session, title="ADBM deck", body="neutral")
    source = _large_text_with_marker(f"{SLIDE_MARKER}\nADBM", 9500, pad_char="m")
    _add_chunk(db_session, object_id, source)

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "ADBM",
        time_scope=TIME_SCOPE_ALL,
        limit=5,
    ).hits
    hit = next((row for row in hits if row.object_id == object_id), None)
    assert hit is not None
    assert "ADBM" in hit.short_excerpt
    assert not hit.short_excerpt.startswith(source[:100])


def test_weak_partial_fragment_ranks_below_strong_token_coverage(db_session) -> None:
    fake = FakeEmbeddingService()
    object_id = _create_object(db_session, title="split-brain doc", body="body")
    query = "перед активацией важно исключить split-brain"
    chunk_weak = Representation(
        object_id=object_id,
        kind=KIND_CHUNK,
        text=("unrelated " * 400) + "важно " + ("noise " * 400),
        part_index=0,
        metadata_={},
    )
    chunk_strong = Representation(
        object_id=object_id,
        kind=KIND_CHUNK,
        text=(
            "перед активацией важно исключить split brain operational guidance "
            + ("context " * 200)
        ),
        part_index=1,
        metadata_={},
    )
    db_session.add(chunk_weak)
    db_session.add(chunk_strong)
    db_session.flush()

    ranked = ContextService(db_session, BOOTSTRAP_USER_ID, fake)._rank_chunks(
        [chunk_weak, chunk_strong],
        query,
    )
    assert ranked[0].id == chunk_strong.id
