"""Graph G1: structural closure and ordinary-neighbor ordering stay inside the node bound."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.api.schemas import EdgeCreate, ObjectCreate
from app.services.graph_service import GraphService
from app.services.graph_workspace_service import GraphWorkspaceService
from app.services.provenance import CONFIRMED_STATE
from tests.conftest import BOOTSTRAP_USER_ID

_BASE = datetime(2020, 1, 1, tzinfo=UTC)


def _task(graph: GraphService, title: str):
    return graph.create_object(
        ObjectCreate(kind="task", title=title, origin="user", state=CONFIRMED_STATE, status="open")
    )


def _note(graph: GraphService, title: str):
    return graph.create_object(
        ObjectCreate(kind="note", title=title, origin="user", state=CONFIRMED_STATE)
    )


def _edge(graph: GraphService, source, target, edge_type: str):
    return graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type=edge_type,
            origin="user",
            state=CONFIRMED_STATE,
        )
    )


def _titles(result) -> set[str]:
    return {node.title for node in result.nodes}


def _set_created_at(db_session, edge, when: datetime) -> None:
    db_session.execute(
        text("UPDATE edges SET created_at = :created_at WHERE id = :edge_id"),
        {"created_at": when, "edge_id": edge.id},
    )


def _set_edge_id(db_session, edge, new_id: uuid.UUID) -> None:
    db_session.execute(
        text("UPDATE edges SET id = :new_id WHERE id = :old_id"),
        {"new_id": new_id, "old_id": edge.id},
    )
    db_session.expire_all()


def test_confirmed_part_of_survives_ordinary_neighbor_truncation(
    db_session, fake_embedding_service
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    parent = _task(graph, "Parent")
    child = _task(graph, "Child")
    part_of = _edge(graph, child, parent, "part_of")
    omitted = None
    omitted_edge = None
    for index in range(5):
        note = _note(graph, f"Note-{index}")
        edge = _edge(graph, parent, note, "related_to")
        _set_created_at(db_session, edge, _BASE + timedelta(days=index))
        if index == 4:
            omitted = note
            omitted_edge = edge
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(
        root_id=parent.id,
        neighbor_limit=2,
        node_limit=80,
    )
    assert "Child" in _titles(result)
    assert part_of.id in {edge.id for edge in result.edges}
    assert omitted.title not in _titles(result)
    assert result.truncated is True

    neighbor_edge_ids = {edge.id for _neighbor, edge, _direction in graph.get_neighbors(parent.id)}
    assert part_of.id in neighbor_edge_ids
    assert omitted_edge.id in neighbor_edge_ids


def test_task_admitted_as_ordinary_neighbor_closes_part_of_before_later_neighbors(
    db_session, fake_embedding_service
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    root = _task(graph, "Root")
    admitted = _task(graph, "Admitted")
    structural_parent = _task(graph, "Structural parent")
    later = _note(graph, "Later note")
    admitted_edge = _edge(graph, root, admitted, "related_to")
    later_edge = _edge(graph, root, later, "related_to")
    _edge(graph, admitted, structural_parent, "part_of")
    _set_created_at(db_session, admitted_edge, _BASE)
    _set_created_at(db_session, later_edge, _BASE + timedelta(days=1))
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(
        root_id=root.id,
        neighbor_limit=2,
        node_limit=3,
    )
    assert _titles(result) == {"Root", "Admitted", "Structural parent"}
    assert result.truncated is True


def test_newer_ordinary_edge_does_not_evict_older_visible_edge(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    root = _task(graph, "Root")
    older = _note(graph, "Older note")
    newer = _note(graph, "Newer note")
    older_edge = _edge(graph, root, older, "references")
    newer_edge = _edge(graph, root, newer, "references")
    _set_created_at(db_session, older_edge, _BASE)
    _set_created_at(db_session, newer_edge, _BASE + timedelta(days=1))
    _set_edge_id(db_session, older_edge, uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"))
    _set_edge_id(db_session, newer_edge, uuid.UUID("00000000-0000-0000-0000-000000000001"))
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(
        root_id=root.id,
        neighbor_limit=1,
        node_limit=80,
    )
    assert "Older note" in _titles(result)
    assert "Newer note" not in _titles(result)
    assert result.truncated is True
    direct = graph.get_neighbors(root.id)
    assert {neighbor.title for neighbor, _edge, _direction in direct} == {
        "Older note",
        "Newer note",
    }
