"""V8E1: confirmed part_of closure inside the graph workspace read model."""

import uuid

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import User
from app.services.graph_service import GraphService
from app.services.graph_workspace_service import GraphWorkspaceService
from app.services.provenance import CONFIRMED_STATE, PROPOSED_STATE, REJECTED_STATE
from tests.conftest import BOOTSTRAP_USER_ID


def _task(graph: GraphService, title: str, status: str | None = "open"):
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin="user",
            state=CONFIRMED_STATE,
            status=status,
        )
    )


def _part_of(graph: GraphService, child, parent, state: str = CONFIRMED_STATE):
    return graph.create_edge(
        EdgeCreate(
            source_id=child.id,
            target_id=parent.id,
            type="part_of",
            origin="user",
            state=state,
        )
    )


def _titles(result) -> set[str]:
    return {node.title for node in result.nodes}


def test_rooted_root_includes_child_and_grandchild(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    parent = _task(graph, "Parent")
    child = _task(graph, "Child")
    grandchild = _task(graph, "Grandchild")
    _part_of(graph, child, parent)
    _part_of(graph, grandchild, child)
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(
        root_id=parent.id,
        neighbor_limit=1,
    )
    assert _titles(result) == {"Parent", "Child", "Grandchild"}
    assert result.truncated is False
    node_ids = [node.id for node in result.nodes]
    edge_ids = [edge.id for edge in result.edges]
    assert len(node_ids) == len(set(node_ids))
    assert len(edge_ids) == len(set(edge_ids))
    assert all(
        edge.source_id in set(node_ids) and edge.target_id in set(node_ids) for edge in result.edges
    )


def test_rooted_descendant_reaches_ancestors_and_the_rest_of_the_tree(
    db_session, fake_embedding_service
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    parent = _task(graph, "Parent")
    child = _task(graph, "Child")
    grandchild = _task(graph, "Grandchild")
    sibling = _task(graph, "Sibling")
    _part_of(graph, child, parent)
    _part_of(graph, grandchild, child)
    _part_of(graph, sibling, parent)
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(
        root_id=grandchild.id
    )
    assert _titles(result) == {"Parent", "Child", "Grandchild", "Sibling"}


def test_overview_seed_includes_depth_two_descendants_that_are_not_seeds(
    db_session, fake_embedding_service
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    parent = _task(graph, "Parent")
    child = _task(graph, "Child", status="done")
    grandchild = _task(graph, "Grandchild", status="done")
    note = graph.create_object(
        ObjectCreate(kind="note", title="Child note", origin="user", state=CONFIRMED_STATE)
    )
    _part_of(graph, child, parent)
    _part_of(graph, grandchild, child)
    graph.create_edge(
        EdgeCreate(
            source_id=child.id,
            target_id=note.id,
            type="references",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace()
    assert result.seed_ids == [parent.id]
    assert _titles(result) == {"Parent", "Child", "Grandchild"}
    assert "Child note" not in _titles(result)


def test_hierarchy_closure_ignores_small_neighbor_limit(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    parent = _task(graph, "Parent")
    children = [_task(graph, f"Child-{index}") for index in range(3)]
    for child in children:
        _part_of(graph, child, parent)
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(
        root_id=parent.id,
        neighbor_limit=1,
        node_limit=80,
    )
    assert _titles(result) == {"Parent", "Child-0", "Child-1", "Child-2"}
    assert len(result.nodes) == 4
    assert result.truncated is False


def test_proposed_part_of_does_not_expand_beyond_one_hop(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    parent = _task(graph, "Parent")
    proposed_child = _task(graph, "Proposed child")
    proposed_grandchild = _task(graph, "Proposed grandchild")
    _part_of(graph, proposed_child, parent, state=PROPOSED_STATE)
    _part_of(graph, proposed_grandchild, proposed_child, state=PROPOSED_STATE)
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(root_id=parent.id)
    assert "Proposed child" in _titles(result)
    assert "Proposed grandchild" not in _titles(result)


def test_rejected_part_of_does_not_expand_hierarchy(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    parent = _task(graph, "Parent")
    rejected_child = _task(graph, "Rejected child")
    _part_of(graph, rejected_child, parent, state=REJECTED_STATE)
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(root_id=parent.id)
    assert _titles(result) == {"Parent"}
    assert result.edges == []


def test_non_task_root_stays_one_hop(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    note = graph.create_object(
        ObjectCreate(kind="note", title="Note root", origin="user", state=CONFIRMED_STATE)
    )
    near = graph.create_object(
        ObjectCreate(kind="note", title="Near", origin="user", state=CONFIRMED_STATE)
    )
    far = graph.create_object(
        ObjectCreate(kind="note", title="Far", origin="user", state=CONFIRMED_STATE)
    )
    parent = _task(graph, "Parent")
    child = _task(graph, "Child")
    graph.create_edge(
        EdgeCreate(
            source_id=note.id,
            target_id=near.id,
            type="related_to",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=near.id,
            target_id=far.id,
            type="related_to",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=note.id,
            target_id=parent.id,
            type="references",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    _part_of(graph, child, parent)
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(root_id=note.id)
    assert _titles(result) == {"Note root", "Near", "Parent"}


def test_ordinary_neighbors_follow_hierarchy_when_budget_remains(
    db_session, fake_embedding_service
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    parent = _task(graph, "Parent")
    child = _task(graph, "Child")
    note = graph.create_object(
        ObjectCreate(kind="note", title="Evidence", origin="user", state=CONFIRMED_STATE)
    )
    _part_of(graph, child, parent)
    graph.create_edge(
        EdgeCreate(
            source_id=parent.id,
            target_id=note.id,
            type="references",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(
        root_id=parent.id,
        neighbor_limit=1,
    )
    assert _titles(result) == {"Parent", "Child", "Evidence"}
    assert [node.title for node in result.nodes] == ["Parent", "Child", "Evidence"]


def test_node_limit_bounds_hierarchy_and_sets_truncated(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    parent = _task(graph, "Parent")
    child = _task(graph, "Child")
    grandchild = _task(graph, "Grandchild")
    _part_of(graph, child, parent)
    _part_of(graph, grandchild, child)
    db_session.flush()

    service = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID)
    result = service.get_workspace(root_id=parent.id, node_limit=2)
    assert len(result.nodes) == 2
    assert len(result.nodes) <= 2
    assert _titles(result) == {"Parent", "Child"}
    assert result.truncated is True
    again = service.get_workspace(root_id=parent.id, node_limit=2)
    assert [node.id for node in again.nodes] == [node.id for node in result.nodes]
    assert [edge.id for edge in again.edges] == [edge.id for edge in result.edges]


def test_user_isolation_keeps_other_user_hierarchy_out(db_session, fake_embedding_service):
    other_id = uuid.uuid4()
    db_session.add(User(id=other_id, display_name="other-graph-user"))
    db_session.flush()
    other = GraphService(db_session, other_id, fake_embedding_service)
    parent = _task(other, "Foreign parent")
    child = _task(other, "Foreign child")
    _part_of(other, child, parent)
    db_session.flush()

    mine = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    local = _task(mine, "Local")
    db_session.flush()

    result = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace()
    assert _titles(result) == {"Local"}
    rooted = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(root_id=local.id)
    assert "Foreign parent" not in _titles(rooted)
    assert "Foreign child" not in _titles(rooted)
