"""Workflow Intelligence Pass B — label-aware search."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import ObjectCreate
from app.db.models import Edge, ExternalActionAttempt, Object, Representation, User
from app.domain.labels import EDGE_TYPE_LABELED_WITH
from app.domain.object_visibility import tombstone_object
from app.main import app
from app.proactive.constants import PROACTIVE_READ_TOOL_NAMES
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.label_service import LabelService
from app.services.provenance import REJECTED_STATE
from app.services.retrieval_constants import FTS_BRANCH_LIMIT, TIME_SCOPE_ALL
from app.services.retrieval_service import (
    RetrievalService,
    _build_atom_representation_russian_fts_sql,
    _build_atom_representation_simple_fts_sql,
    _build_atom_russian_fts_sql,
    _build_atom_simple_fts_sql,
    _build_atom_trigram_sql,
    _build_filter_suffix,
    _build_fts_candidate_sql,
    _build_representation_fts_candidate_sql,
    _build_trigram_candidate_sql,
)
from app.services.search_service import SEARCH_SORT_NEWEST, SEARCH_SORT_OLDEST, SearchService
from app.tools.registry import PROACTIVE_TOOL_DEFINITIONS
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient


@pytest.fixture
def search_client(db_session, auth_headers):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as raw:
        yield AuthTestClient(raw, auth_headers)
    app.dependency_overrides.clear()


def _svc(session: Session, user_id=BOOTSTRAP_USER_ID) -> LabelService:
    return LabelService(session, user_id)


def _graph(session: Session) -> GraphService:
    return GraphService(session, BOOTSTRAP_USER_ID, None)


def _note(session: Session, title: str, body: str | None = None, **kwargs) -> Object:
    return _graph(session).create_object(
        ObjectCreate(kind="note", title=title, body=body, origin="user", **kwargs)
    )


def _email(session: Session, title: str, *, provider: str, body: str | None = None) -> Object:
    return _graph(session).create_object(
        ObjectCreate(
            kind="email",
            title=title,
            body=body,
            origin="source",
            provider=provider,
            state="observed",
        )
    )


def test_search_without_label_id_is_unchanged(db_session) -> None:
    marker = "PassBUnfilteredMarker"
    labeled = _note(db_session, f"{marker} labeled")
    unlabeled = _note(db_session, f"{marker} unlabeled extra tokens")
    label = _svc(db_session).create_label("Work").label
    _svc(db_session).assign_label(labeled.id, label.id)
    search = SearchService(db_session, BOOTSTRAP_USER_ID)
    results = search.search(marker)
    ids = {item.id for item in results}
    assert labeled.id in ids
    assert unlabeled.id in ids


def test_search_with_active_label_returns_only_assigned(search_client, db_session) -> None:
    marker = "PassBAssignedOnlyMarker"
    labeled = _note(db_session, f"{marker} keep")
    _note(db_session, f"{marker} drop")
    label = _svc(db_session).create_label("Focus").label
    _svc(db_session).assign_label(labeled.id, label.id)
    response = search_client.get(
        "/search",
        params={"q": marker, "label_id": str(label.id)},
    )
    assert response.status_code == 200
    ids = {uuid.UUID(row["id"]) for row in response.json()}
    assert ids == {labeled.id}


def test_higher_relevance_unlabeled_is_excluded(db_session) -> None:
    marker = "PassBRelevanceExcludeMarker"
    unlabeled = _note(db_session, title=marker, body=f"{marker} extra matching body")
    labeled = _note(db_session, title="weak container", body="short")
    labeled.body = marker
    db_session.flush()
    label = _svc(db_session).create_label("Keep").label
    _svc(db_session).assign_label(labeled.id, label.id)
    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        marker, time_scope=TIME_SCOPE_ALL
    ).hits
    assert hits[0].object_id == unlabeled.id
    filtered = SearchService(db_session, BOOTSTRAP_USER_ID).search(marker, label_id=label.id)
    assert [item.id for item in filtered] == [labeled.id]
    assert unlabeled.id not in {item.id for item in filtered}


def test_label_filter_sql_applies_before_branch_limit() -> None:
    suffix = _build_filter_suffix(
        kind=None,
        provider=None,
        project_id=None,
        horizon_cutoff=None,
        date_from=None,
        date_to=None,
        apply_horizon=False,
        label_id=uuid.uuid4(),
    )
    builders = [
        _build_fts_candidate_sql,
        _build_trigram_candidate_sql,
        _build_atom_simple_fts_sql,
        _build_atom_russian_fts_sql,
        _build_atom_trigram_sql,
        _build_atom_representation_simple_fts_sql,
        _build_atom_representation_russian_fts_sql,
        lambda text: _build_representation_fts_candidate_sql(text, "simple"),
        lambda text: _build_representation_fts_candidate_sql(text, "russian"),
    ]
    for builder in builders:
        sql = builder(suffix)
        assert "labeled_with" in sql
        assert "EXISTS" in sql.upper()
        assert sql.upper().index("EXISTS") < sql.upper().rindex("LIMIT :BRANCH_LIMIT")


def test_label_filter_occurs_before_fts_branch_limit(db_session) -> None:
    marker = "PassBLimitMarkerUnique"
    label = _svc(db_session).create_label("Limit").label
    labeled = _note(db_session, title="unrelated title", body=marker)
    _svc(db_session).assign_label(labeled.id, label.id)
    for index in range(FTS_BRANCH_LIMIT + 10):
        _note(db_session, title=f"{marker} flood {index:03d}", body=marker)
    search = SearchService(db_session, BOOTSTRAP_USER_ID)
    unfiltered = search.search(marker, limit=20)
    assert labeled.id not in {item.id for item in unfiltered}
    filtered = search.search(marker, label_id=label.id, limit=20)
    assert [item.id for item in filtered] == [labeled.id]


def test_kind_and_provider_combine_with_label_filter(db_session) -> None:
    marker = "PassBKindProviderMarker"
    label = _svc(db_session).create_label("Mail").label
    gmail = _email(db_session, f"{marker} gmail", provider="gmail", body=marker)
    yandex = _email(db_session, f"{marker} yandex", provider="yandex_mail", body=marker)
    task = _graph(db_session).create_object(
        ObjectCreate(kind="task", title=f"{marker} task", origin="user")
    )
    service = _svc(db_session)
    service.assign_label(gmail.id, label.id)
    service.assign_label(yandex.id, label.id)
    service.assign_label(task.id, label.id)
    search = SearchService(db_session, BOOTSTRAP_USER_ID)
    results = search.search(marker, kind="email", provider="gmail", label_id=label.id)
    assert [item.id for item in results] == [gmail.id]


def test_sort_modes_remain_deterministic_with_label_filter(db_session) -> None:
    marker = "PassBSortMarker"
    label = _svc(db_session).create_label("Chrono").label
    older = _email(db_session, f"{marker} older", provider="gmail", body=marker)
    newer = _email(db_session, f"{marker} newer", provider="gmail", body=marker)
    older.occurred_at = datetime(2026, 1, 1, tzinfo=UTC)
    newer.occurred_at = datetime(2026, 2, 1, tzinfo=UTC)
    db_session.flush()
    service = _svc(db_session)
    service.assign_label(older.id, label.id)
    service.assign_label(newer.id, label.id)
    search = SearchService(db_session, BOOTSTRAP_USER_ID)
    newest = search.search(marker, sort=SEARCH_SORT_NEWEST, label_id=label.id)
    oldest = search.search(marker, sort=SEARCH_SORT_OLDEST, label_id=label.id)
    relevance = search.search(marker, label_id=label.id)
    assert [item.id for item in newest] == [newer.id, older.id]
    assert [item.id for item in oldest] == [older.id, newer.id]
    assert {item.id for item in relevance} == {older.id, newer.id}
    assert [item.id for item in newest] == [item.id for item in search.search(marker, sort=SEARCH_SORT_NEWEST, label_id=label.id)]


def test_foreign_label_fails_closed(search_client, db_session) -> None:
    marker = "PassBForeignMarker"
    _note(db_session, marker)
    other_user = uuid.uuid4()
    db_session.add(User(id=other_user, display_name="foreign-search-label"))
    db_session.flush()
    foreign = LabelService(db_session, other_user).create_label("Secret").label
    response = search_client.get("/search", params={"q": marker, "label_id": str(foreign.id)})
    assert response.status_code == 422


def test_tombstoned_label_fails_closed(search_client, db_session) -> None:
    marker = "PassBTombstoneLabelMarker"
    note = _note(db_session, marker)
    label = _svc(db_session).create_label("Gone").label
    _svc(db_session).assign_label(note.id, label.id)
    _svc(db_session).delete_label(label.id)
    response = search_client.get("/search", params={"q": marker, "label_id": str(label.id)})
    assert response.status_code == 422


def test_rejected_label_fails_closed(search_client, db_session) -> None:
    marker = "PassBRejectedLabelMarker"
    _note(db_session, marker)
    label = _svc(db_session).create_label("Rejected").label
    label.state = REJECTED_STATE
    db_session.flush()
    response = search_client.get("/search", params={"q": marker, "label_id": str(label.id)})
    assert response.status_code == 422


def test_kind_label_plus_label_id_fails_closed(search_client, db_session) -> None:
    label = _svc(db_session).create_label("Meta").label
    response = search_client.get(
        "/search",
        params={"q": "Meta", "kind": "label", "label_id": str(label.id)},
    )
    assert response.status_code == 422
    assert "cannot be labeled" in response.json()["detail"]


def test_rejected_labeled_with_edge_does_not_count(db_session) -> None:
    marker = "PassBRejectedEdgeMarker"
    note = _note(db_session, marker)
    label = _svc(db_session).create_label("Edge").label
    assigned = _svc(db_session).assign_label(note.id, label.id)
    assigned.edge.state = REJECTED_STATE
    db_session.flush()
    results = SearchService(db_session, BOOTSTRAP_USER_ID).search(marker, label_id=label.id)
    assert results == []


def test_tombstoned_content_object_does_not_return(db_session) -> None:
    marker = "PassBTombstoneContentMarker"
    note = _note(db_session, marker)
    label = _svc(db_session).create_label("Trash").label
    _svc(db_session).assign_label(note.id, label.id)
    tombstone_object(note)
    db_session.flush()
    results = SearchService(db_session, BOOTSTRAP_USER_ID).search(marker, label_id=label.id)
    assert results == []


def test_strict_title_body_fts_honors_label_filter(db_session) -> None:
    marker = "PassBStrictFtsMarker"
    labeled = _note(db_session, title=f"{marker} titled", body=f"{marker} body")
    _note(db_session, title=f"{marker} other", body=f"{marker} body")
    label = _svc(db_session).create_label("Strict").label
    _svc(db_session).assign_label(labeled.id, label.id)
    result = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        marker,
        time_scope=TIME_SCOPE_ALL,
        label_id=label.id,
    )
    assert [hit.object_id for hit in result.hits] == [labeled.id]
    assert result.retrieval_mode == "strict"


def test_representation_fts_honors_label_filter(db_session) -> None:
    marker = "PassBRepMarkerUNIQUE"
    labeled = _note(db_session, title="Neutral container", body="no unique terms here")
    unlabeled = _note(db_session, title="Other container", body="no unique terms here")
    db_session.add(
        Representation(object_id=labeled.id, kind="full", text=f"hidden {marker} content", metadata_={})
    )
    db_session.add(
        Representation(object_id=unlabeled.id, kind="full", text=f"hidden {marker} content", metadata_={})
    )
    db_session.flush()
    label = _svc(db_session).create_label("Rep").label
    _svc(db_session).assign_label(labeled.id, label.id)
    result = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        marker,
        time_scope=TIME_SCOPE_ALL,
        label_id=label.id,
    )
    assert [hit.object_id for hit in result.hits] == [labeled.id]


def test_relaxed_atom_path_honors_label_filter(db_session) -> None:
    unique_atom = "PASSB_RELAXED_ATOM_9911"
    labeled = _note(db_session, title="Neutral container title", body="Body without searchable unique terms here.")
    unlabeled = _note(db_session, title="Second container title", body="Body without searchable unique terms here.")
    db_session.add(
        Representation(object_id=labeled.id, kind="chunk", text=f"padding {unique_atom} padding", metadata_={})
    )
    db_session.add(
        Representation(object_id=unlabeled.id, kind="chunk", text=f"padding {unique_atom} padding", metadata_={})
    )
    db_session.flush()
    label = _svc(db_session).create_label("Relaxed").label
    _svc(db_session).assign_label(labeled.id, label.id)
    query = f"Найди мне {unique_atom}"
    result = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        query,
        time_scope=TIME_SCOPE_ALL,
        label_id=label.id,
    )
    assert labeled.id in {hit.object_id for hit in result.hits}
    assert unlabeled.id not in {hit.object_id for hit in result.hits}


def test_source_objects_keep_provider_fields_on_assign(db_session) -> None:
    before = db_session.scalar(select(func.count()).select_from(ExternalActionAttempt))
    email = _email(db_session, "Inbox item", provider="gmail", body="hello")
    email.external_id = "gmail-msg-1"
    db_session.flush()
    label = _svc(db_session).create_label("Inbox").label
    _svc(db_session).assign_label(email.id, label.id)
    db_session.refresh(email)
    assert email.provider == "gmail"
    assert email.external_id == "gmail-msg-1"
    assert db_session.scalar(select(func.count()).select_from(ExternalActionAttempt)) == before
    edges = list(
        db_session.scalars(
            select(Edge).where(Edge.source_id == email.id, Edge.type == EDGE_TYPE_LABELED_WITH)
        )
    )
    assert len(edges) == 1


def test_proactive_allowlist_unchanged() -> None:
    assert PROACTIVE_READ_TOOL_NAMES == (
        "retrieve",
        "query_objects",
        "get_object",
        "get_context",
        "list_neighbors",
        "list_notifications",
    )
    assert tuple(item["name"] for item in PROACTIVE_TOOL_DEFINITIONS) == PROACTIVE_READ_TOOL_NAMES
    assert "list_labels" not in PROACTIVE_READ_TOOL_NAMES


def test_search_validation_error_on_missing_label(db_session) -> None:
    with pytest.raises(ValidationError):
        SearchService(db_session, BOOTSTRAP_USER_ID).search(
            "x",
            label_id=uuid.uuid4(),
        )
