"""Graph G3A: overview pages are whole Task constellations."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import User
from app.services.errors import ConstellationTooLargeError, ValidationError
from app.services.graph_service import GraphService
from app.services.graph_workspace_service import GraphWorkspaceService
from app.services.provenance import CONFIRMED_STATE

_BASE = datetime(2020, 6, 1, tzinfo=UTC)


def _user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name=f"g3a-{user_id}"))
    db_session.flush()
    return user_id


def _graph(db_session, user_id, fake_embedding_service) -> GraphService:
    return GraphService(db_session, user_id, fake_embedding_service)


def _task(graph: GraphService, title: str, *, status: str | None = "open", due_at=None):
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


def _edge(graph: GraphService, source, target, edge_type: str, *, origin: str = "user"):
    return graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type=edge_type,
            origin=origin,
            state=CONFIRMED_STATE,
        )
    )


def _titles(result) -> set[str]:
    return {node.title for node in result.nodes}


def _set_updated_at(db_session, obj, when: datetime) -> None:
    db_session.execute(
        text("UPDATE objects SET updated_at = :updated_at WHERE id = :object_id"),
        {"updated_at": when, "object_id": obj.id},
    )


def test_part_of_tree_and_priority_flow_stay_in_one_window(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    parent = _task(graph, "Direction", due_at=_BASE)
    child = _task(graph, "Child")
    grandchild = _task(graph, "Grandchild", status="done")
    evidence = _note(graph, "Evidence")
    source = _note(graph, "Incidental")
    _edge(graph, child, parent, "part_of")
    _edge(graph, grandchild, child, "part_of")
    _edge(graph, child, evidence, "references", origin="agent")
    _edge(graph, parent, source, "references", origin="source")
    _task(graph, "Later direction")
    db_session.flush()

    service = GraphWorkspaceService(db_session, user_id)
    window = service.get_workspace(soft_window_target=4)
    assert _titles(window) == {"Direction", "Child", "Grandchild", "Evidence"}
    assert "Incidental" not in _titles(window)
    assert "Later direction" not in _titles(window)
    assert window.semantic_window_complete is True
    assert window.constellation_root_ids == (parent.id,)
    assert window.has_next_window is True

    nxt = service.get_workspace(window_index=1, soft_window_target=4)
    assert _titles(nxt) == {"Later direction"}
    assert window.truncated is True
    assert nxt.has_previous_window is True
    assert nxt.has_next_window is False


def test_standalone_tasks_are_separate_pages(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    _task(graph, "First", due_at=_BASE)
    _task(graph, "Second", due_at=_BASE + timedelta(days=2))
    done = _task(graph, "Finished", status="done")
    db_session.flush()

    service = GraphWorkspaceService(db_session, user_id)
    window = service.get_workspace(soft_window_target=1)
    assert _titles(window) == {"First"}
    assert service.get_workspace(window_index=1, soft_window_target=1).nodes[0].title == "Second"
    overview = service.get_workspace()
    assert done.title not in _titles(overview)
    assert "Finished" not in _titles(
        service.get_workspace(window_index=1, soft_window_target=1)
    )


def test_shared_flow_is_one_node_and_cross_window_edge_does_not_import(
    db_session, fake_embedding_service
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    left = _task(graph, "Left", due_at=_BASE)
    right = _task(graph, "Right", due_at=_BASE + timedelta(days=3))
    shared = _note(graph, "Shared")
    left_edge = _edge(graph, left, shared, "references")
    right_edge = _edge(graph, shared, right, "related_to")
    bridge = _edge(graph, left, right, "depends_on")
    db_session.flush()

    service = GraphWorkspaceService(db_session, user_id)
    together = service.get_workspace()
    assert len(together.nodes) == 3
    assert {left_edge.id, right_edge.id, bridge.id} <= {edge.id for edge in together.edges}

    first = service.get_workspace(soft_window_target=2)
    assert _titles(first) == {"Left", "Shared"}
    assert right.id not in {node.id for node in first.nodes}
    assert bridge.id not in {edge.id for edge in first.edges}
    second = service.get_workspace(window_index=1, soft_window_target=2)
    assert _titles(second) == {"Right", "Shared"}
    neighbors = {item.title for item, _edge, _direction in graph.get_neighbors(left.id)}
    assert "Right" in neighbors


def test_page_order_is_stable_when_a_later_constellation_is_added(
    db_session, fake_embedding_service
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    early = _task(graph, "Early", due_at=_BASE)
    middle = _task(graph, "Middle", due_at=_BASE + timedelta(days=1))
    db_session.flush()
    service = GraphWorkspaceService(db_session, user_id)
    before = [
        service.get_workspace(window_index=index, soft_window_target=1).constellation_root_ids
        for index in range(2)
    ]
    _task(graph, "Unrelated later")
    db_session.flush()
    after = [
        service.get_workspace(window_index=index, soft_window_target=1).constellation_root_ids
        for index in range(2)
    ]
    assert before == [(early.id,), (middle.id,)]
    assert after == before
    again = service.get_workspace(soft_window_target=1)
    assert again.constellation_root_ids == (early.id,)


def test_rooted_task_keeps_constellation_when_ordinary_context_is_truncated(
    db_session, fake_embedding_service
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    parent = _task(graph, "Parent")
    child = _task(graph, "Child")
    note = _note(graph, "Context")
    _edge(graph, child, parent, "part_of")
    _edge(graph, parent, note, "references", origin="source")
    db_session.flush()

    result = GraphWorkspaceService(db_session, user_id).get_workspace(
        root_id=parent.id,
        neighbor_limit=1,
        node_limit=2,
    )
    assert _titles(result) == {"Parent", "Child"}
    assert result.truncated is True
    assert result.semantic_window_complete is False


def test_rooted_non_task_does_not_pull_priority_flow_of_a_touched_task(
    db_session, fake_embedding_service
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    note = _note(graph, "Note root")
    parent = _task(graph, "Parent")
    child = _task(graph, "Child")
    evidence = _note(graph, "Task evidence")
    far = _task(graph, "Far")
    _edge(graph, note, parent, "references")
    _edge(graph, child, parent, "part_of")
    _edge(graph, parent, evidence, "references")
    _edge(graph, far, child, "part_of")
    db_session.flush()

    result = GraphWorkspaceService(db_session, user_id).get_workspace(
        root_id=note.id,
        node_limit=3,
    )
    assert "Task evidence" not in _titles(result)
    assert "Note root" in _titles(result)
    assert "Parent" in _titles(result)
    assert len(result.nodes) <= 3


def test_oversized_constellation_fails_instead_of_slicing(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    parent = _task(graph, "Huge")
    child = _task(graph, "Huge child")
    _edge(graph, child, parent, "part_of")
    db_session.flush()

    service = GraphWorkspaceService(db_session, user_id)
    with pytest.raises(ConstellationTooLargeError, match="too large for complete overview"):
        service.get_workspace(max_complete_window_nodes=1)
    with pytest.raises(ConstellationTooLargeError):
        service.get_workspace(root_id=parent.id, max_complete_window_nodes=1)


def test_window_flags_and_invalid_index(db_session, fake_embedding_service, auth_client):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    _task(graph, "Only")
    db_session.flush()
    service = GraphWorkspaceService(db_session, user_id)
    only = service.get_workspace()
    assert only.window_index == 0
    assert only.window_count == 1
    assert only.has_previous_window is False
    assert only.has_next_window is False
    with pytest.raises(ValidationError, match="graph window index is out of range"):
        service.get_workspace(window_index=2)

    response = auth_client.get("/graph/workspace", params={"window_index": 99999})
    assert response.status_code == 422
    assert "out of range" in response.json()["detail"]


def test_first_constellation_above_soft_target_is_kept_whole(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    parent = _task(graph, "Wide", due_at=_BASE)
    for index in range(3):
        child = _task(graph, f"Part-{index}")
        _edge(graph, child, parent, "part_of")
    _set_updated_at(db_session, parent, _BASE)
    db_session.flush()

    window = GraphWorkspaceService(db_session, user_id).get_workspace(soft_window_target=2)
    assert _titles(window) == {"Wide", "Part-0", "Part-1", "Part-2"}
    assert window.has_next_window is False
