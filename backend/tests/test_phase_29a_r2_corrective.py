"""PHASE 29A-R2 — XLSX searchable content and context closure."""

import uuid
from pathlib import Path

from app.content_extraction.constants import EXTRACTION_VERSION
from app.content_extraction.mechanical_extractors import extract_from_path
from app.content_extraction.mechanical_persistence import MechanicalRepresentationPersistence
from app.content_extraction.metadata_keys import (
    MECHANICAL_REPRESENTATION_COUNT,
)
from app.db.models import Object, Representation
from app.services.context_service import ContextService
from app.services.explicit_link_intake_service import ExplicitLinkIntakeService
from app.services.retrieval_service import RetrievalService
from app.tools.registry import ASSISTANT_TOOL_DEFINITIONS
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.fixtures.phase_29a_fixtures import write_xlsx_search_regression_workbook

TARGET_PHRASE = "phase29a_row15_target_phrase_marker"
FULL_PHRASE = (
    "Контрольное мероприятие №1: Классификация на ручных признаках"
)


def _make_file_object(db_session, title: str = "synthetic.xlsx") -> Object:
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        provider="google_drive",
        external_id=f"gdrive-{uuid.uuid4().hex[:8]}",
        origin="explicit",
        state="observed",
        title=title,
        metadata_={
            "content_revision": f"test:rev:{uuid.uuid4().hex[:8]}",
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
    )
    db_session.add(obj)
    db_session.flush()
    return obj


def _persist_xlsx_extraction(db_session, obj: Object, xlsx_path: Path) -> None:
    reps, extract_meta = extract_from_path(obj.id, xlsx_path)
    count = MechanicalRepresentationPersistence(db_session).replace_mechanical_for_object(
        obj.id, reps
    )
    meta = dict(obj.metadata_ or {})
    meta.update(extract_meta)
    meta["content_extraction_status"] = "ready"
    meta["content_extraction_version"] = EXTRACTION_VERSION
    meta[MECHANICAL_REPRESENTATION_COUNT] = count
    obj.metadata_ = meta
    db_session.commit()


def test_xlsx_sparse_columns_and_row15_phrase_persisted(tmp_path: Path) -> None:
    obj_id = uuid.uuid4()
    xlsx_path = tmp_path / "regression.xlsx"
    write_xlsx_search_regression_workbook(xlsx_path, target_phrase=TARGET_PHRASE)
    reps, meta = extract_from_path(obj_id, xlsx_path)
    sample = next(r for r in reps if r.kind == "sample")
    stats = next(r for r in reps if r.kind == "statistics")
    searchable = [r for r in reps if r.kind in {"full", "chunk"}]
    assert "D=Тема" in sample.text
    assert "columns=8" in stats.text
    assert "rows=46" in stats.text
    joined = "\n".join(r.text for r in searchable)
    assert TARGET_PHRASE in joined
    assert "[sheet=Учебный план row=15]" in joined
    assert "A=Учебная часть" in joined and "D=" in joined
    assert meta["content_truncated"] is False


def test_xlsx_small_workbook_not_truncated(tmp_path: Path) -> None:
    obj_id = uuid.uuid4()
    xlsx_path = tmp_path / "small.xlsx"
    write_xlsx_search_regression_workbook(xlsx_path, data_rows=46)
    _, meta = extract_from_path(obj_id, xlsx_path)
    assert meta["content_truncated"] is False


def test_xlsx_representation_part_bounds(tmp_path: Path) -> None:
    obj_id = uuid.uuid4()
    xlsx_path = tmp_path / "bounded.xlsx"
    write_xlsx_search_regression_workbook(xlsx_path, data_rows=46)
    reps, _ = extract_from_path(obj_id, xlsx_path)
    assert len(reps) <= 64
    total_bytes = sum(len(r.text.encode("utf-8")) for r in reps)
    assert total_bytes <= 256 * 1024
    for rep in reps:
        assert len(rep.text.encode("utf-8")) <= 16 * 1024


def test_retrieve_exact_phrase_finds_xlsx(db_session, tmp_path: Path) -> None:
    obj = _make_file_object(db_session, "Второе полугодие.xlsx")
    xlsx_path = tmp_path / "file.xlsx"
    write_xlsx_search_regression_workbook(
        xlsx_path,
        target_phrase=FULL_PHRASE,
    )
    _persist_xlsx_extraction(db_session, obj, xlsx_path)

    svc = RetrievalService(db_session, BOOTSTRAP_USER_ID)
    res = svc.retrieve(FULL_PHRASE, limit=5, time_scope="all")
    ids = [h.object_id for h in res.hits]
    assert obj.id in ids


def test_retrieve_title_still_finds_xlsx(db_session, tmp_path: Path) -> None:
    obj = _make_file_object(db_session, "Второе полугодие.xlsx")
    xlsx_path = tmp_path / "file.xlsx"
    write_xlsx_search_regression_workbook(xlsx_path)
    _persist_xlsx_extraction(db_session, obj, xlsx_path)

    res = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "Второе полугодие", limit=5, time_scope="all"
    )
    assert any(h.object_id == obj.id for h in res.hits)


def test_stale_v1_representation_not_searchable_by_phrase(db_session, tmp_path: Path) -> None:
    obj = _make_file_object(db_session, "stale.xlsx")
    xlsx_path = tmp_path / "stale.xlsx"
    write_xlsx_search_regression_workbook(xlsx_path, target_phrase=FULL_PHRASE)
    reps, _ = extract_from_path(obj.id, xlsx_path)
    for rep in reps:
        db_session.add(
            Representation(
                object_id=obj.id,
                kind=rep.kind,
                part_index=rep.part_index,
                text=rep.text,
                metadata_=rep.metadata_,
            )
        )
    meta = dict(obj.metadata_ or {})
    meta["content_extraction_status"] = "ready"
    meta["content_extraction_version"] = "phase29a-v1"
    obj.metadata_ = meta
    db_session.commit()

    res = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        FULL_PHRASE, limit=10, time_scope="all"
    )
    assert obj.id not in [h.object_id for h in res.hits]

    title_res = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "stale", limit=5, time_scope="all"
    )
    assert obj.id in [h.object_id for h in title_res.hits]


def test_get_context_query_lexical_without_embeddings(db_session, tmp_path: Path) -> None:
    obj = _make_file_object(db_session, "context.xlsx")
    xlsx_path = tmp_path / "ctx.xlsx"
    write_xlsx_search_regression_workbook(xlsx_path, target_phrase=TARGET_PHRASE)
    _persist_xlsx_extraction(db_session, obj, xlsx_path)

    ctx = ContextService(db_session, BOOTSTRAP_USER_ID, embedding_service=None)
    result = ctx.build_context(
        object_id=obj.id,
        query=TARGET_PHRASE,
        max_chars=8000,
    )
    joined = "\n".join(item.content for item in result.items)
    assert TARGET_PHRASE in joined


def test_retrieval_false_positive_target_ranks_ahead(db_session, tmp_path: Path) -> None:
    target = _make_file_object(db_session, "target_file.xlsx")
    partial = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="event",
        provider="yandex_calendar",
        external_id=f"ycal-{uuid.uuid4().hex[:8]}",
        origin="sync",
        state="observed",
        title="Архитектура платформы данных",
        body="Модуль 1. Классификация применяемого ПО с точки зрения архитектуры.",
        metadata_={},
    )
    db_session.add(partial)
    db_session.flush()

    xlsx_path = tmp_path / "target.xlsx"
    write_xlsx_search_regression_workbook(xlsx_path, target_phrase=FULL_PHRASE)
    _persist_xlsx_extraction(db_session, target, xlsx_path)

    res = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        FULL_PHRASE, limit=5, time_scope="all"
    )
    ids = [h.object_id for h in res.hits[:5]]
    assert target.id in ids
    assert ids.index(target.id) < ids.index(partial.id) if partial.id in ids else True


def test_assistant_get_context_schema_exposes_query() -> None:
    get_context = next(d for d in ASSISTANT_TOOL_DEFINITIONS if d["name"] == "get_context")
    assert "query" in get_context["parameters"]["properties"]
    assert len(ASSISTANT_TOOL_DEFINITIONS) == len({d["name"] for d in ASSISTANT_TOOL_DEFINITIONS})


def test_same_revision_v1_reintake_schedules_one_current_version_job(db_session, monkeypatch) -> None:
    obj = _make_file_object(db_session, "reintake.xlsx")
    meta = dict(obj.metadata_ or {})
    meta.update(
        {
            "content_extraction_status": "ready",
            "content_extraction_version": "phase29a-v1",
            "content_revision": "gdrive:md5:abc123",
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "file_id": "file123",
            "md5_checksum": "abc123",
        }
    )
    obj.metadata_ = meta
    db_session.add(
        Representation(object_id=obj.id, kind="sample", text="old sample", metadata_={})
    )
    db_session.commit()

    enqueue_calls: list[tuple] = []
    monkeypatch.setattr(
        "app.services.explicit_link_intake_service.enqueue_extract_explicit_resource_content",
        lambda session, object_id, user_id, revision, version: enqueue_calls.append(
            (object_id, revision, version)
        ),
    )

    service = ExplicitLinkIntakeService(db_session, BOOTSTRAP_USER_ID)
    normalized = {
        "provider": "google_drive",
        "kind": "file",
        "title": obj.title,
        "external_id": obj.external_id,
        "origin": "explicit",
        "state": "observed",
        "metadata": dict(meta),
    }
    _, status, jobs = service._upsert(obj, normalized)
    assert status != "unchanged"
    assert jobs == 1
    assert len(enqueue_calls) == 1
    assert enqueue_calls[0][2] == EXTRACTION_VERSION


def test_v2_ready_reintake_is_noop(db_session, monkeypatch) -> None:
    obj = _make_file_object(db_session, "ready.xlsx")
    meta = dict(obj.metadata_ or {})
    meta.update(
        {
            "content_extraction_status": "ready",
            "content_extraction_version": EXTRACTION_VERSION,
            "content_revision": "gdrive:md5:ready123",
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "file_id": "file456",
            "md5_checksum": "ready123",
        }
    )
    obj.metadata_ = meta
    db_session.add(
        Representation(object_id=obj.id, kind="sample", text="sample", metadata_={})
    )
    db_session.commit()

    enqueue_calls: list[tuple] = []
    monkeypatch.setattr(
        "app.services.explicit_link_intake_service.enqueue_extract_explicit_resource_content",
        lambda *args, **kwargs: enqueue_calls.append(args),
    )

    service = ExplicitLinkIntakeService(db_session, BOOTSTRAP_USER_ID)
    normalized = {
        "provider": "google_drive",
        "kind": "file",
        "title": obj.title,
        "external_id": obj.external_id,
        "origin": "explicit",
        "state": "observed",
        "metadata": dict(meta),
    }
    _, status, jobs = service._upsert(obj, normalized)
    assert status == "unchanged"
    assert jobs == 0
    assert enqueue_calls == []
