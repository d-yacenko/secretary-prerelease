"""Graph G2: confirmed Task-Flow evidence is admitted fairly before incidental neighbors."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import User
from app.services.graph_service import GraphService
from app.services.graph_workspace_service import GraphWorkspaceService
from app.services.provenance import CONFIRMED_STATE, PROPOSED_STATE, REJECTED_STATE

_BASE = datetime(2020, 1, 1, tzinfo=UTC)


def _user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name=f"g2-{user_id}"))
    db_session.flush()
    return user_id


def _graph(db_session, user_id, fake_embedding_service) -> GraphService:
    return GraphService(db_session, user_id, fake_embedding_service)


def _task(graph: GraphService, title: str, status: str | None = "open"):
    return graph.create_object(
        ObjectCreate(kind="task", title=title, origin="user", state=CONFIRMED_STATE, status=status)
    )


def _note(graph: GraphService, title: str):
    return graph.create_object(
        ObjectCreate(kind="note", title=title, origin="user", state=CONFIRMED_STATE)
    )


def _edge(
    graph: GraphService,
    source,
    target,
    edge_type: str,
    *,
    origin: str = "user",
    state: str = CONFIRMED_STATE,
):
    return graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type=edge_type,
            origin=origin,
            state=state,
        )
    )


def _set_created_at(db_session, edge, when: datetime) -> None:
    db_session.execute(
        text("UPDATE edges SET created_at = :created_at WHERE id = :edge_id"),
        {"created_at": when, "edge_id": edge.id},
    )


def _titles(result) -> set[str]:
    return {node.title for node in result.nodes}


def test_confirmed_flow_beats_older_incidental_neighbors(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    task = _task(graph, "Article")
    for index in range(4):
        note = _note(graph, f"Source-{index}")
        edge = _edge(graph, task, note, "references", origin="source")
        _set_created_at(db_session, edge, _BASE + timedelta(days=index))
    user_flow = _note(graph, "User evidence")
    agent_flow = _note(graph, "Agent evidence")
    user_edge = _edge(graph, task, user_flow, "references", origin="user")
    agent_edge = _edge(graph, agent_flow, task, "references", origin="agent")
    _set_created_at(db_session, user_edge, _BASE + timedelta(days=20))
    _set_created_at(db_session, agent_edge, _BASE + timedelta(days=21))
    db_session.flush()

    result = GraphWorkspaceService(db_session, user_id).get_workspace(
        neighbor_limit=1,
        node_limit=3,
    )
    assert _titles(result) == {"Article", "User evidence", "Agent evidence"}
    assert result.truncated is False
    assert result.semantic_window_complete is True


def test_priority_flow_is_round_robin_across_tasks(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    tasks = [_task(graph, f"Task-{index}") for index in range(3)]
    tasks.sort(key=lambda item: item.id)
    for task_index, task in enumerate(tasks):
        for flow_index in range(2):
            note = _note(graph, f"Flow-{task_index}-{flow_index}")
            edge = _edge(graph, task, note, "related_to")
            _set_created_at(
                db_session,
                edge,
                _BASE + timedelta(days=task_index * 10 + flow_index),
            )
    db_session.flush()

    for index, task in enumerate(tasks):
        db_session.execute(
            text("UPDATE objects SET updated_at = :updated_at WHERE id = :object_id"),
            {"updated_at": _BASE + timedelta(days=30 - index), "object_id": task.id},
        )
    db_session.expire_all()
    db_session.flush()

    service = GraphWorkspaceService(db_session, user_id)
    first = service.get_workspace(soft_window_target=4)
    assert _titles(first) == {tasks[0].title, "Flow-0-0", "Flow-0-1"}
    assert first.has_next_window is True
    second = service.get_workspace(window_index=1, soft_window_target=4)
    assert _titles(second) == {tasks[1].title, "Flow-1-0", "Flow-1-1"}
    assert tasks[0].title not in _titles(second)


def test_part_of_added_task_receives_priority_flow(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    parent = _task(graph, "Parent")
    child = _task(graph, "Child", status="done")
    evidence = _note(graph, "Child evidence")
    _edge(graph, child, parent, "part_of")
    _edge(graph, child, evidence, "depends_on", origin="agent")
    db_session.flush()

    result = GraphWorkspaceService(db_session, user_id).get_workspace()
    assert _titles(result) == {"Parent", "Child", "Child evidence"}


def test_shared_flow_uses_one_slot_and_keeps_both_edges(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    left = _task(graph, "Left")
    right = _task(graph, "Right")
    shared = _note(graph, "Shared")
    left_edge = _edge(graph, left, shared, "references")
    right_edge = _edge(graph, shared, right, "related_to")
    db_session.flush()

    result = GraphWorkspaceService(db_session, user_id).get_workspace(node_limit=3)
    assert _titles(result) == {"Left", "Right", "Shared"}
    assert {left_edge.id, right_edge.id} <= {edge.id for edge in result.edges}
    assert len(result.nodes) == 3


def test_rejected_and_source_do_not_take_priority_slots(
    db_session, fake_embedding_service
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    task = _task(graph, "Task")
    rejected = _note(graph, "Rejected flow")
    source = _note(graph, "Source flow")
    proposed = _note(graph, "Proposed flow")
    confirmed = _note(graph, "Confirmed flow")
    _edge(graph, task, rejected, "references", state=REJECTED_STATE)
    source_edge = _edge(graph, task, source, "references", origin="source")
    proposed_edge = _edge(graph, task, proposed, "references", state=PROPOSED_STATE)
    confirmed_edge = _edge(graph, task, confirmed, "references", origin="user")
    _set_created_at(db_session, source_edge, _BASE)
    _set_created_at(db_session, proposed_edge, _BASE + timedelta(days=1))
    _set_created_at(db_session, confirmed_edge, _BASE + timedelta(days=2))
    db_session.flush()

    result = GraphWorkspaceService(db_session, user_id).get_workspace(
        neighbor_limit=12,
        node_limit=2,
    )
    assert _titles(result) == {"Task", "Confirmed flow", "Proposed flow"}
    assert "Rejected flow" not in _titles(result)
    assert "Source flow" not in _titles(result)
    assert result.truncated is False

    ordinary = GraphWorkspaceService(db_session, user_id).get_workspace(
        root_id=task.id,
        neighbor_limit=12,
        node_limit=80,
    )
    assert "Source flow" in _titles(ordinary)
    assert "Proposed flow" in _titles(ordinary)
    assert "Rejected flow" not in _titles(ordinary)


def test_priority_flow_respects_node_limit_and_marks_truncated(
    db_session, fake_embedding_service
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    task = _task(graph, "Task")
    for index in range(5):
        note = _note(graph, f"Flow-{index}")
        edge = _edge(graph, task, note, "references")
        _set_created_at(db_session, edge, _BASE + timedelta(days=index))
    db_session.flush()

    result = GraphWorkspaceService(db_session, user_id).get_workspace(node_limit=3)
    assert len(result.nodes) == 6
    assert "Flow-0" in _titles(result)
    assert "Flow-1" in _titles(result)
    assert "Flow-4" in _titles(result)
    assert result.truncated is False


def test_newer_explicit_relation_does_not_evict_older_one(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    task = _task(graph, "Task")
    older = _note(graph, "Older evidence")
    newer = _note(graph, "Newer evidence")
    older_edge = _edge(graph, task, older, "references")
    newer_edge = _edge(graph, task, newer, "references")
    _set_created_at(db_session, older_edge, _BASE)
    _set_created_at(db_session, newer_edge, _BASE + timedelta(days=5))
    db_session.execute(
        text("UPDATE edges SET id = :new_id WHERE id = :old_id"),
        {"new_id": uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"), "old_id": older_edge.id},
    )
    db_session.execute(
        text("UPDATE edges SET id = :new_id WHERE id = :old_id"),
        {"new_id": uuid.UUID("00000000-0000-0000-0000-000000000001"), "old_id": newer_edge.id},
    )
    db_session.expire_all()
    db_session.flush()

    result = GraphWorkspaceService(db_session, user_id).get_workspace(node_limit=2)
    assert _titles(result) == {"Task", "Older evidence", "Newer evidence"}
    assert result.truncated is False


def test_non_task_root_does_not_expand_task_flow_evidence(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    root = _note(graph, "Note root")
    task = _task(graph, "Linked task")
    evidence = _note(graph, "Task evidence")
    _edge(graph, root, task, "references")
    _edge(graph, task, evidence, "references")
    db_session.flush()

    result = GraphWorkspaceService(db_session, user_id).get_workspace(root_id=root.id)
    assert _titles(result) == {"Note root", "Linked task"}
    assert "Task evidence" not in _titles(result)
