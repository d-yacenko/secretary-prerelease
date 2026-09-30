"""SW2-A: overview pages keep confirmed Task-map components whole."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import User
from app.domain.task_map_topology import confirmed_task_relation_joins_overview_component
from app.services.errors import ConstellationTooLargeError
from app.services.graph_service import GraphService
from app.services.graph_workspace_service import GraphWorkspaceService
from app.services.provenance import CONFIRMED_STATE, PROPOSED_STATE, REJECTED_STATE

_BASE = datetime(2020, 7, 1, tzinfo=UTC)


def _user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name=f"sw2a-{user_id}"))
    db_session.flush()
    return user_id


def _graph(db_session, user_id, fake_embedding_service) -> GraphService:
    return GraphService(db_session, user_id, fake_embedding_service)


def _task(graph: GraphService, title: str, *, due_at=None, status: str | None = "open"):
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin="user",
            state=CONFIRMED_STATE,
            status=status,
            due_at=due_at,
        )
    )


def _note(graph: GraphService, title: str):
    return graph.create_object(
        ObjectCreate(kind="note", title=title, origin="user", state=CONFIRMED_STATE)
    )


def _edge(graph: GraphService, source, target, edge_type: str, *, state: str = CONFIRMED_STATE):
    return graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type=edge_type,
            origin="user",
            state=state,
        )
    )


def _titles(result) -> set[str]:
    return {node.title for node in result.nodes}


def _window_edges_stay_inside(result) -> None:
    present = {node.id for node in result.nodes}
    for edge in result.edges:
        assert edge.source_id in present
        assert edge.target_id in present


def test_publication_flower_stays_on_one_overview_window(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    direction = _task(graph, "Publications", due_at=_BASE)
    petals = [_task(graph, f"Paper-{index}") for index in range(5)]
    for petal in petals:
        _edge(graph, direction, petal, "related_to")
    _task(graph, "Unrelated", due_at=_BASE + timedelta(days=9))
    db_session.flush()

    service = GraphWorkspaceService(db_session, user_id)
    window = service.get_workspace(soft_window_target=1)
    assert _titles(window) == {"Publications", *(petal.title for petal in petals)}
    assert "Unrelated" not in _titles(window)
    assert window.semantic_window_complete is True
    assert window.constellation_root_ids == (direction.id,)
    assert window.has_next_window is True
    _window_edges_stay_inside(window)

    nxt = service.get_workspace(window_index=1, soft_window_target=1)
    assert _titles(nxt) == {"Unrelated"}
    assert not any(petal.title in _titles(nxt) for petal in petals)
    _window_edges_stay_inside(nxt)


def test_mixed_academic_component_is_one_soft_page(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    academic = _task(graph, "Academic", due_at=_BASE)
    publications = _task(graph, "Publications")
    teaching = _task(graph, "Teaching")
    courses = _task(graph, "Courses")
    paper = _task(graph, "Paper")
    lecture = _task(graph, "Lecture")
    _edge(graph, publications, academic, "part_of")
    _edge(graph, teaching, academic, "part_of")
    _edge(graph, courses, academic, "part_of")
    _edge(graph, publications, paper, "related_to")
    _edge(graph, teaching, lecture, "depends_on")
    later = _task(graph, "Inbox", due_at=_BASE + timedelta(days=4))
    db_session.flush()

    service = GraphWorkspaceService(db_session, user_id)
    window = service.get_workspace(soft_window_target=3)
    assert _titles(window) == {
        "Academic",
        "Publications",
        "Teaching",
        "Courses",
        "Paper",
        "Lecture",
    }
    assert window.constellation_root_ids == (academic.id,)
    assert window.semantic_window_complete is True
    nxt = service.get_workspace(window_index=1, soft_window_target=3)
    assert _titles(nxt) == {"Inbox"}
    assert later.title == "Inbox"


@pytest.mark.parametrize("edge_type", ["depends_on", "references", "related_to"])
def test_only_confirmed_secondary_edges_merge_overview_components(
    db_session, fake_embedding_service, edge_type: str
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    left = _task(graph, "Left", due_at=_BASE)
    right = _task(graph, "Right", due_at=_BASE + timedelta(days=1))
    db_session.flush()
    service = GraphWorkspaceService(db_session, user_id)

    absent = service.get_workspace(soft_window_target=1)
    assert absent.window_count == 2
    assert _titles(absent) == {"Left"}

    _edge(graph, left, right, edge_type, state=PROPOSED_STATE)
    db_session.flush()
    proposed = service.get_workspace(soft_window_target=1)
    assert proposed.window_count == 2

    proposed_edge = graph.get_neighbors(left.id, include_rejected=True)
    edge = next(item[1] for item in proposed_edge if item[1].type == edge_type)
    graph.set_edge_state(edge.id, REJECTED_STATE)
    db_session.flush()
    rejected = service.get_workspace(soft_window_target=1)
    assert rejected.window_count == 2

    graph.delete_edge(edge.id)
    _edge(graph, left, right, edge_type, state=CONFIRMED_STATE)
    db_session.flush()
    confirmed = service.get_workspace(soft_window_target=1)
    assert confirmed.window_count == 1
    assert _titles(confirmed) == {"Left", "Right"}
    assert confirmed.semantic_window_complete is True


@pytest.mark.parametrize("edge_type", ["requested_by", "temporal_evidence"])
def test_hidden_task_relations_do_not_merge_overview_components(
    db_session, fake_embedding_service, edge_type: str
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    left = _task(graph, "Left", due_at=_BASE)
    right = _task(graph, "Right", due_at=_BASE + timedelta(days=1))
    _edge(graph, left, right, edge_type)
    db_session.flush()

    window = GraphWorkspaceService(db_session, user_id).get_workspace(soft_window_target=1)
    assert window.window_count == 2
    assert _titles(window) == {"Left"}
    nxt = GraphWorkspaceService(db_session, user_id).get_workspace(
        window_index=1, soft_window_target=1
    )
    assert _titles(nxt) == {"Right"}


def test_shared_flow_does_not_glue_task_components(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    left = _task(graph, "Left", due_at=_BASE)
    right = _task(graph, "Right", due_at=_BASE + timedelta(days=2))
    shared = _note(graph, "Shared")
    _edge(graph, left, shared, "references")
    _edge(graph, right, shared, "references")
    db_session.flush()

    service = GraphWorkspaceService(db_session, user_id)
    first = service.get_workspace(soft_window_target=1)
    second = service.get_workspace(window_index=1, soft_window_target=1)
    assert first.window_count == 2
    assert _titles(first) == {"Left", "Shared"}
    assert _titles(second) == {"Right", "Shared"}
    assert len([node for node in first.nodes if node.id == shared.id]) == 1
    _window_edges_stay_inside(first)
    _window_edges_stay_inside(second)


def test_component_above_soft_target_stays_whole(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    hub = _task(graph, "Hub", due_at=_BASE)
    for index in range(3):
        leaf = _task(graph, f"Leaf-{index}")
        _edge(graph, hub, leaf, "references")
    _task(graph, "Later", due_at=_BASE + timedelta(days=3))
    db_session.flush()

    service = GraphWorkspaceService(db_session, user_id)
    window = service.get_workspace(soft_window_target=2)
    assert _titles(window) == {"Hub", "Leaf-0", "Leaf-1", "Leaf-2"}
    nxt = service.get_workspace(window_index=1, soft_window_target=2)
    assert _titles(nxt) == {"Later"}


def test_oversized_semantic_component_fails_closed(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    hub = _task(graph, "Hub")
    leaf = _task(graph, "Leaf")
    _edge(graph, hub, leaf, "related_to")
    db_session.flush()

    with pytest.raises(ConstellationTooLargeError, match="too large for complete overview"):
        GraphWorkspaceService(db_session, user_id).get_workspace(max_complete_window_nodes=1)


def test_two_part_of_roots_use_one_seed_representative(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    early = _task(graph, "Early root", due_at=_BASE)
    late = _task(graph, "Late root", due_at=_BASE + timedelta(days=5))
    early_leaf = _task(graph, "Early leaf")
    late_leaf = _task(graph, "Late leaf")
    _edge(graph, early_leaf, early, "part_of")
    _edge(graph, late_leaf, late, "part_of")
    _edge(graph, early_leaf, late_leaf, "related_to")
    db_session.flush()

    window = GraphWorkspaceService(db_session, user_id).get_workspace(soft_window_target=1)
    assert window.window_count == 1
    assert _titles(window) == {"Early root", "Late root", "Early leaf", "Late leaf"}
    assert window.constellation_root_ids == (early.id,)


def test_predicate_requires_confirmed_visible_task_edges():
    assert confirmed_task_relation_joins_overview_component(
        edge_type="related_to",
        state=CONFIRMED_STATE,
        source_kind="task",
        target_kind="task",
    )
    assert not confirmed_task_relation_joins_overview_component(
        edge_type="related_to",
        state=PROPOSED_STATE,
        source_kind="task",
        target_kind="task",
    )
    assert not confirmed_task_relation_joins_overview_component(
        edge_type="requested_by",
        state=CONFIRMED_STATE,
        source_kind="task",
        target_kind="task",
    )
    assert not confirmed_task_relation_joins_overview_component(
        edge_type="references",
        state=CONFIRMED_STATE,
        source_kind="task",
        target_kind="note",
    )
