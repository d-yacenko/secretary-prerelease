"""ObjectQueryService boundary tests for PHASE 26C closure."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.api.schemas import ObjectCreate
from app.db.models import User
from app.domain.task_lifecycle import (
    LEGACY_TASK_STATUS_COMPLETED,
    TASK_STATUS_DELETED,
    TASK_STATUS_OPEN,
)
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.object_query_service import ObjectQueryService
from app.services.provenance import PROPOSED_STATE, REJECTED_STATE
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _create_task(
    graph: GraphService,
    title: str,
    *,
    due_at: datetime | None = None,
    start_at: datetime | None = None,
    occurred_at: datetime | None = None,
    status: str | None = TASK_STATUS_OPEN,
    state: str = "confirmed",
    provider: str | None = None,
    kind: str = "task",
) -> object:
    obj = graph.create_object(
        ObjectCreate(
            kind=kind,
            title=title,
            origin="user",
            state=state,
            provider=provider,
        )
    )
    obj.kind = kind
    obj.status = status
    if due_at is not None:
        obj.due_at = due_at
    if start_at is not None:
        obj.start_at = start_at
    if occurred_at is not None:
        obj.occurred_at = occurred_at
    return obj


def test_legacy_null_status_matches_open_filter(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    null_task = _create_task(
        graph,
        "Null status",
        status=None,
        state=PROPOSED_STATE,
        due_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    db_session.flush()
    rows = ObjectQueryService(db_session, BOOTSTRAP_USER_ID).query(
        kinds=["task"], statuses=["open"], sort_by="due_at", sort_order="asc"
    )
    assert null_task.id in {row.id for row in rows}


def test_legacy_completed_matches_done_filter(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    completed = _create_task(
        graph,
        "Completed legacy",
        status=LEGACY_TASK_STATUS_COMPLETED,
    )
    db_session.flush()
    rows = ObjectQueryService(db_session, BOOTSTRAP_USER_ID).query(
        kinds=["task"], statuses=["done"]
    )
    assert completed.id in {row.id for row in rows}


def test_date_range_filters_inclusive(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    due = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    start = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
    occurred = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)
    task = _create_task(
        graph,
        "Ranges",
        due_at=due,
        start_at=start,
        occurred_at=occurred,
    )
    db_session.flush()
    service = ObjectQueryService(db_session, BOOTSTRAP_USER_ID)
    assert task.id in {
        row.id
        for row in service.query(
            kinds=["task"],
            due_from=due,
            due_to=due,
            start_from=start,
            start_to=start,
            occurred_from=occurred,
            occurred_to=occurred,
        )
    }


def test_multiple_kinds_and_provider_filter(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    email = _create_task(
        graph,
        "Mail",
        kind="email",
        provider="gmail",
        status=None,
    )
    _create_task(graph, "Other", kind="note", status=None)
    db_session.flush()
    rows = ObjectQueryService(db_session, BOOTSTRAP_USER_ID).query(
        kinds=["email", "task"],
        providers=["gmail"],
    )
    ids = {row.id for row in rows}
    assert email.id in ids


def test_state_filter_and_visibility(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    proposed = _create_task(graph, "Proposed", state=PROPOSED_STATE)
    rejected = _create_task(graph, "Rejected", state=REJECTED_STATE)
    deleted = _create_task(graph, "Deleted", status=TASK_STATUS_DELETED)
    db_session.flush()
    rows = ObjectQueryService(db_session, BOOTSTRAP_USER_ID).query(kinds=["task"])
    ids = {row.id for row in rows}
    assert proposed.id in ids
    assert rejected.id not in ids
    assert deleted.id not in ids


def test_cross_user_isolation(db_session, issue_bearer) -> None:
    other_user = uuid4()
    db_session.add(User(id=other_user, display_name="Other"))
    graph_a = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    graph_b = GraphService(db_session, other_user, None)
    mine = _create_task(graph_a, "Mine")
    theirs = _create_task(graph_b, "Theirs")
    db_session.flush()
    rows = ObjectQueryService(db_session, BOOTSTRAP_USER_ID).query(kinds=["task"])
    ids = {row.id for row in rows}
    assert mine.id in ids
    assert theirs.id not in ids


def test_nulls_last_and_deterministic_order(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    undated = _create_task(graph, "Undated", due_at=None)
    undated.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    early = _create_task(
        graph,
        "Early",
        due_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    early.created_at = datetime(2020, 1, 2, tzinfo=UTC)
    late = _create_task(
        graph,
        "Late",
        due_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    late.created_at = datetime(2020, 1, 3, tzinfo=UTC)
    db_session.flush()
    service = ObjectQueryService(db_session, BOOTSTRAP_USER_ID)
    asc_ids = [row.id for row in service.query(
        kinds=["task"], sort_by="due_at", sort_order="asc", limit=10
    )]
    assert asc_ids.index(early.id) < asc_ids.index(late.id)
    assert asc_ids.index(late.id) < asc_ids.index(undated.id)
    desc_ids = [row.id for row in service.query(
        kinds=["task"], sort_by="due_at", sort_order="desc", limit=10
    )]
    assert desc_ids.index(late.id) < desc_ids.index(early.id)
    assert desc_ids.index(early.id) < desc_ids.index(undated.id)


def test_limit_cap_and_invalid_sort(db_session) -> None:
    service = ObjectQueryService(db_session, BOOTSTRAP_USER_ID)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    for index in range(55):
        _create_task(graph, f"Bulk {index}")
    db_session.flush()
    rows = service.query(kinds=["task"], limit=50)
    assert len(rows) == 50
    with pytest.raises(ValidationError):
        service.query(sort_by="urgent")
