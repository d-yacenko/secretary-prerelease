"""GR1: proposed Task evidence stays on the same overview component."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import User
from app.services.errors import ConstellationTooLargeError
from app.services.graph_service import GraphService
from app.services.graph_workspace_service import GraphWorkspaceService
from app.services.provenance import CONFIRMED_STATE, PROPOSED_STATE, REJECTED_STATE

_BASE = datetime(2020, 8, 1, tzinfo=UTC)


def _user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name=f"gr1-{user_id}"))
    db_session.flush()
    return user_id


def _graph(db_session, user_id, fake_embedding_service) -> GraphService:
    return GraphService(db_session, user_id, fake_embedding_service)


def _task(graph: GraphService, title: str, *, due_at=None):
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin="user",
            state=CONFIRMED_STATE,
            status="open",
            due_at=due_at,
        )
    )


def _object(graph: GraphService, title: str, *, kind: str = "note"):
    return graph.create_object(
        ObjectCreate(kind=kind, title=title, origin="user", state=CONFIRMED_STATE)
    )


def _edge(graph, source, target, edge_type, *, origin="agent", state=PROPOSED_STATE):
    return graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type=edge_type,
            origin=origin,
            state=state,
            confidence=0.8 if origin == "agent" and state == PROPOSED_STATE else None,
        )
    )


def _titles(result) -> set[str]:
    return {node.title for node in result.nodes}


@pytest.mark.parametrize("edge_type", ["references", "related_to", "depends_on"])
def test_proposed_agent_endpoint_stays_with_its_task(db_session, fake_embedding_service, edge_type):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    publication = _task(graph, "Publication", due_at=_BASE)
    pdf = _object(graph, "Program_DYSC.pdf")
    edge = _edge(graph, publication, pdf, edge_type)
    _task(graph, "Later", due_at=_BASE + timedelta(days=3))
    db_session.flush()

    window = GraphWorkspaceService(db_session, user_id).get_workspace(soft_window_target=1)
    assert _titles(window) == {"Publication", "Program_DYSC.pdf"}
    assert edge.id in {item.id for item in window.edges}
    assert window.semantic_window_complete is True
    assert window.has_next_window is True


def test_confirmed_evidence_stays_and_rejected_or_foreign_edges_do_not_admit(
    db_session, fake_embedding_service
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    task = _task(graph, "Publication", due_at=_BASE)
    kept = _object(graph, "Kept note")
    rejected = _object(graph, "Rejected note")
    sourced = _object(graph, "Source note")
    labeled = _object(graph, "Temporal")
    _edge(graph, task, kept, "references", origin="user", state=CONFIRMED_STATE)
    _edge(graph, task, rejected, "references", state=REJECTED_STATE)
    _edge(graph, task, sourced, "references", origin="source", state="observed")
    _edge(graph, task, labeled, "temporal_evidence", origin="agent", state=PROPOSED_STATE)
    db_session.flush()

    window = GraphWorkspaceService(db_session, user_id).get_workspace()
    assert "Kept note" in _titles(window)
    assert "Rejected note" not in _titles(window)
    assert "Source note" not in _titles(window)
    assert "Temporal" not in _titles(window)


def test_proposed_endpoint_does_not_glue_task_components(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    left = _task(graph, "Left", due_at=_BASE)
    right = _task(graph, "Right", due_at=_BASE + timedelta(days=2))
    shared = _object(graph, "Shared pdf")
    _edge(graph, left, shared, "references")
    _edge(graph, right, shared, "references")
    db_session.flush()

    service = GraphWorkspaceService(db_session, user_id)
    first = service.get_workspace(soft_window_target=1)
    second = service.get_workspace(window_index=1, soft_window_target=1)
    assert first.window_count == 2
    assert _titles(first) == {"Left", "Shared pdf"}
    assert _titles(second) == {"Right", "Shared pdf"}


def test_soft_target_keeps_proposed_endpoint_with_its_component(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    task = _task(graph, "Publication", due_at=_BASE)
    pdf = _object(graph, "Program_DYSC.pdf")
    _edge(graph, task, pdf, "references")
    _task(graph, "Other", due_at=_BASE + timedelta(days=4))
    db_session.flush()

    window = GraphWorkspaceService(db_session, user_id).get_workspace(soft_window_target=1)
    assert _titles(window) == {"Publication", "Program_DYSC.pdf"}
    nxt = GraphWorkspaceService(db_session, user_id).get_workspace(
        window_index=1,
        soft_window_target=1,
    )
    assert _titles(nxt) == {"Other"}


def test_emergency_ceiling_still_includes_proposed_endpoints(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    task = _task(graph, "Publication")
    pdf = _object(graph, "Program_DYSC.pdf")
    _edge(graph, task, pdf, "references")
    db_session.flush()

    with pytest.raises(ConstellationTooLargeError):
        GraphWorkspaceService(db_session, user_id).get_workspace(max_complete_window_nodes=1)


def test_rooted_task_keeps_proposed_endpoint_and_truncates_ordinary_neighbors(
    db_session, fake_embedding_service
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    task = _task(graph, "Publication")
    pdf = _object(graph, "Program_DYSC.pdf")
    extra = _object(graph, "Incidental")
    _edge(graph, task, pdf, "references")
    _edge(graph, task, extra, "references", origin="source", state="observed")
    db_session.flush()

    result = GraphWorkspaceService(db_session, user_id).get_workspace(
        root_id=task.id,
        neighbor_limit=1,
        node_limit=2,
    )
    assert _titles(result) == {"Publication", "Program_DYSC.pdf"}
    assert result.truncated is True
