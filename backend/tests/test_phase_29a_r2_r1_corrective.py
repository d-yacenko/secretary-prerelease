"""PHASE 29A-R2-R1 — Assistant retrieve kind wildcard normalization."""

import uuid
from pathlib import Path

import pytest

from app.assistant.session import run_assistant_tool
from app.assistant.tool_args import normalize_assistant_tool_arguments
from app.db.models import Object
from app.services.domain_tool_service import DomainToolService
from app.tools.registry import ASSISTANT_TOOL_DEFINITIONS
from app.tools.schemas import RetrieveInput, ToolError
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.fixtures.phase_29a_fixtures import write_xlsx_search_regression_workbook

TARGET_PHRASE = "phase29a_row15_target_phrase_marker"


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


def _persist_xlsx(db_session, obj: Object, xlsx_path: Path) -> None:
    from app.content_extraction.constants import EXTRACTION_VERSION
    from app.content_extraction.mechanical_extractors import extract_from_path
    from app.content_extraction.mechanical_persistence import MechanicalRepresentationPersistence
    from app.content_extraction.metadata_keys import MECHANICAL_REPRESENTATION_COUNT

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


@pytest.mark.parametrize(
    "kind",
    [None, "", "all", "ALL", " any ", "Any", "*", "  *  "],
)
def test_normalize_retrieve_kind_wildcards_to_none(kind) -> None:
    normalized = normalize_assistant_tool_arguments(
        "retrieve",
        {"query": "test", "kind": kind, "time_scope": "all"},
    )
    assert normalized["kind"] is None


def test_normalize_retrieve_kind_preserves_real_kinds() -> None:
    for kind in ("file", "email", "event", "task"):
        normalized = normalize_assistant_tool_arguments(
            "retrieve",
            {"query": "test", "kind": kind, "time_scope": "all"},
        )
        assert normalized["kind"] == kind


def test_normalize_retrieve_kind_rejects_non_string() -> None:
    with pytest.raises(ToolError, match="retrieve kind must be a string"):
        normalize_assistant_tool_arguments(
            "retrieve",
            {"query": "test", "kind": 42, "time_scope": "all"},
        )


def test_assistant_retrieve_schema_kind_description() -> None:
    retrieve = next(d for d in ASSISTANT_TOOL_DEFINITIONS if d["name"] == "retrieve")
    kind = retrieve["parameters"]["properties"]["kind"]
    description = kind.get("description", "")
    assert "Object.kind" in description
    assert '"all" is not an Object.kind' in description
    assert len(ASSISTANT_TOOL_DEFINITIONS) == len({d["name"] for d in ASSISTANT_TOOL_DEFINITIONS})


def test_retrieve_kind_all_matches_unfiltered_xlsx_target(db_session, tmp_path: Path) -> None:
    target = _make_file_object(db_session, "Второе полугодие.xlsx")
    xlsx_path = tmp_path / "target.xlsx"
    write_xlsx_search_regression_workbook(xlsx_path, target_phrase=TARGET_PHRASE)
    _persist_xlsx(db_session, target, xlsx_path)

    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, embedding_service=None)
    unfiltered_args = normalize_assistant_tool_arguments(
        "retrieve",
        {"query": TARGET_PHRASE, "time_scope": "all", "limit": 5},
    )
    with_kind_all_args = normalize_assistant_tool_arguments(
        "retrieve",
        {"query": TARGET_PHRASE, "kind": "all", "time_scope": "all", "limit": 5},
    )
    unfiltered = tools.retrieve(RetrieveInput.model_validate(unfiltered_args))
    with_kind_all = tools.retrieve(RetrieveInput.model_validate(with_kind_all_args))

    assert unfiltered_args["kind"] is None
    assert with_kind_all_args["kind"] is None
    assert [h.object_id for h in unfiltered.hits[:5]] == [
        h.object_id for h in with_kind_all.hits[:5]
    ]
    assert target.id in [h.object_id for h in with_kind_all.hits[:5]]


def test_retrieve_kind_file_still_filters(db_session, tmp_path: Path) -> None:
    target = _make_file_object(db_session, "file_only.xlsx")
    event = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="event",
        provider="yandex_calendar",
        external_id=f"ycal-{uuid.uuid4().hex[:8]}",
        origin="sync",
        state="observed",
        title="phase29a_row15_target_phrase_marker event title",
        body="",
        metadata_={},
    )
    db_session.add(event)
    db_session.flush()

    xlsx_path = tmp_path / "target.xlsx"
    write_xlsx_search_regression_workbook(xlsx_path, target_phrase=TARGET_PHRASE)
    _persist_xlsx(db_session, target, xlsx_path)

    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, embedding_service=None)
    file_args = normalize_assistant_tool_arguments(
        "retrieve",
        {"query": TARGET_PHRASE, "kind": "file", "time_scope": "all", "limit": 5},
    )
    file_hits = tools.retrieve(RetrieveInput.model_validate(file_args))
    ids = [h.object_id for h in file_hits.hits]
    assert target.id in ids
    assert event.id not in ids


def test_assistant_tool_path_kind_all_finds_xlsx(db_session, tmp_path: Path) -> None:
    target = _make_file_object(db_session, "Второе полугодие.xlsx")
    xlsx_path = tmp_path / "target.xlsx"
    write_xlsx_search_regression_workbook(xlsx_path, target_phrase=TARGET_PHRASE)
    _persist_xlsx(db_session, target, xlsx_path)

    result = run_assistant_tool(
        BOOTSTRAP_USER_ID,
        "retrieve",
        {
            "query": TARGET_PHRASE,
            "kind": "all",
            "time_scope": "all",
            "limit": 5,
        },
    )
    assert result.success
    hits = result.output.get("hits", [])
    assert any(hit.get("object_id") == str(target.id) for hit in hits)
