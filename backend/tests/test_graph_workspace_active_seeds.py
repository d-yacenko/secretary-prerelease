"""PHASE 24 E2E corrective — graph workspace active seed compatibility tests."""

from datetime import UTC, datetime, timedelta

from app.api.schemas import EdgeCreate, ObjectCreate
from app.services.graph_service import GraphService
from app.services.graph_workspace_service import GraphWorkspaceService
from app.services.provenance import CONFIRMED_STATE, PROPOSED_STATE, REJECTED_STATE
from tests.conftest import BOOTSTRAP_USER_ID


def _task(
    graph: GraphService,
    title: str,
    status: str | None = "open",
    state: str = CONFIRMED_STATE,
    due_at=None,
) -> object:
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin="user",
            state=state,
            status=status,
            due_at=due_at,
        )
    )


def test_confirmed_open_is_default_seed(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _task(graph, "OPEN-SEED", status="open")
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace()
    titles = {node.title for node in result.nodes}
    assert task.title in titles


def test_confirmed_null_status_is_default_seed(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _task(graph, "NULL-STATUS", status=None)
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace()
    titles = {node.title for node in result.nodes}
    assert task.title in titles


def test_proposed_state_legacy_proposed_status_is_default_seed(
    db_session, fake_embedding_service,
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _task(graph, "LEGACY-PROPOSED", status="proposed", state=PROPOSED_STATE)
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace()
    titles = {node.title for node in result.nodes}
    assert task.title in titles


def test_proposed_state_open_status_is_default_seed(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _task(graph, "PROPOSED-OPEN", status="open", state=PROPOSED_STATE)
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace()
    titles = {node.title for node in result.nodes}
    assert task.title in titles


def test_rejected_state_open_excluded(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    _task(graph, "REJECTED-OPEN", status="open", state=REJECTED_STATE)
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace()
    titles = {node.title for node in result.nodes}
    assert "REJECTED-OPEN" not in titles


def test_terminal_statuses_excluded_from_default_seed(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    for status in ("done", "completed", "cancelled", "archived", "deleted"):
        _task(graph, f"TERM-{status}", status=status)
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(
        seed_limit=24,
    )
    titles = {node.title for node in result.nodes}
    for status in ("done", "completed", "cancelled", "archived", "deleted"):
        assert f"TERM-{status}" not in titles


def test_proposed_due_before_confirmed_no_due_in_seed_order(
    db_session, fake_embedding_service,
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    soon = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    _task(graph, "CONFIRMED-NO-DUE", status="open", state=CONFIRMED_STATE)
    proposed = _task(
        graph,
        "PROPOSED-SOON",
        status="proposed",
        state=PROPOSED_STATE,
        due_at=soon,
    )
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(
        seed_limit=12,
    )
    seed_ids = [node.id for node in result.nodes]
    assert proposed.id in seed_ids
    assert seed_ids.index(proposed.id) < seed_ids.index(
        next(node.id for node in result.nodes if node.title == "CONFIRMED-NO-DUE")
    )


def test_active_seed_caps_still_apply(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    for index in range(8):
        _task(graph, f"CAP-{index}")
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(
        seed_limit=12,
        node_limit=3,
    )
    assert len(result.nodes) <= 3
    assert result.truncated is True
