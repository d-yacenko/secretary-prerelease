"""Graph G1R: persisted edges among already admitted nodes are not traversal-optional."""

import uuid

from sqlalchemy import text

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import User
from app.services.graph_service import GraphService
from app.services.graph_workspace_service import GraphWorkspaceService
from app.services.provenance import CONFIRMED_STATE, PROPOSED_STATE, REJECTED_STATE


def _user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name=f"g1r-{user_id}"))
    db_session.flush()
    return user_id


def _graph(db_session, user_id, fake_embedding_service) -> GraphService:
    return GraphService(db_session, user_id, fake_embedding_service)


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


def _note(graph: GraphService, title: str):
    return graph.create_object(
        ObjectCreate(kind="note", title=title, origin="user", state=CONFIRMED_STATE)
    )


def _edge(graph: GraphService, source, target, edge_type: str, state: str = CONFIRMED_STATE):
    return graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type=edge_type,
            origin="user",
            state=state,
        )
    )


def _ids(result) -> set:
    return {node.id for node in result.nodes}


def _edge_ids(result) -> set:
    return {edge.id for edge in result.edges}


def test_overview_omits_persisted_edge_between_admitted_nodes_that_rooted_returns(
    db_session, fake_embedding_service
):
    """R1 traversal keeps only edges the walk inserted.

    A seed plus two ordinary neighbors admits all three nodes. A persisted
    eligible edge between those neighbors is absent from overview and present
    when the workspace is rooted at one endpoint.
    """
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    seed = _task(graph, "Seed")
    left = _note(graph, "Left")
    right = _note(graph, "Right")
    _edge(graph, seed, left, "references")
    _edge(graph, seed, right, "references")
    cross = _edge(graph, left, right, "related_to")
    db_session.flush()

    service = GraphWorkspaceService(db_session, user_id)
    overview = service.get_workspace()
    assert {seed.id, left.id, right.id} <= _ids(overview)
    rooted = service.get_workspace(root_id=left.id)
    assert cross.id in _edge_ids(rooted)
    assert cross.id in _edge_ids(overview)


def test_three_admitted_tasks_return_both_confirmed_part_of_edges(
    db_session, fake_embedding_service
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    grandchild = _task(graph, "Grandchild")
    child = _task(graph, "Child")
    parent = _task(graph, "Parent")
    lower = _edge(graph, grandchild, child, "part_of")
    upper = _edge(graph, child, parent, "part_of")
    db_session.flush()

    result = GraphWorkspaceService(db_session, user_id).get_workspace()
    assert {grandchild.id, child.id, parent.id} <= _ids(result)
    assert {lower.id, upper.id} <= _edge_ids(result)
    assert len(result.nodes) == 3


def test_related_to_between_admitted_tasks_does_not_change_node_membership(
    db_session, fake_embedding_service
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    hub = _task(graph, "Hub")
    child = _task(graph, "Child")
    parent = _task(graph, "Parent")
    _edge(graph, hub, child, "related_to")
    _edge(graph, hub, parent, "related_to")
    db_session.flush()

    service = GraphWorkspaceService(db_session, user_id)
    before = service.get_workspace()
    assert {hub.id, child.id, parent.id} <= _ids(before)
    before_ids = _ids(before)

    cross = _edge(graph, child, parent, "related_to")
    db_session.flush()
    after = service.get_workspace()
    assert _ids(after) == before_ids
    assert cross.id in _edge_ids(after)


def test_rejected_edge_between_admitted_nodes_is_not_returned(
    db_session, fake_embedding_service
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    seed = _task(graph, "Seed")
    left = _note(graph, "Left")
    right = _note(graph, "Right")
    _edge(graph, seed, left, "references")
    _edge(graph, seed, right, "references")
    rejected = _edge(graph, left, right, "related_to", state=REJECTED_STATE)
    proposed = _edge(graph, left, right, "references", state=PROPOSED_STATE)
    db_session.flush()

    edges = _edge_ids(GraphWorkspaceService(db_session, user_id).get_workspace())
    assert rejected.id not in edges
    assert proposed.id in edges


def test_other_users_edge_is_not_returned(db_session, fake_embedding_service):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    left = _task(graph, "Left")
    right = _task(graph, "Right")
    mine = _edge(graph, left, right, "related_to")
    other_id = _user(db_session)
    foreign_edge_id = uuid.uuid4()
    db_session.execute(
        text(
            """
            INSERT INTO edges (
                id, user_id, source_id, target_id, type, origin, state, metadata
            ) VALUES (
                :id, :user_id, :source_id, :target_id, 'related_to', 'user', 'confirmed', '{}'::jsonb
            )
            """
        ),
        {
            "id": foreign_edge_id,
            "user_id": other_id,
            "source_id": left.id,
            "target_id": right.id,
        },
    )
    db_session.flush()

    edges = _edge_ids(GraphWorkspaceService(db_session, user_id).get_workspace())
    assert mine.id in edges
    assert foreign_edge_id not in edges


def test_parallel_part_of_and_related_to_between_same_endpoints_are_both_returned(
    db_session, fake_embedding_service
):
    user_id = _user(db_session)
    graph = _graph(db_session, user_id, fake_embedding_service)
    hub = _task(graph, "Hub")
    child = _task(graph, "Child", status="done")
    parent = _task(graph, "Parent", status="open")
    _edge(graph, hub, child, "related_to")
    _edge(graph, hub, parent, "related_to")
    structural = _edge(graph, child, parent, "part_of")
    ordinary = _edge(graph, child, parent, "related_to")
    db_session.flush()

    service = GraphWorkspaceService(db_session, user_id)
    overview = service.get_workspace()
    assert {hub.id, child.id, parent.id} <= _ids(overview)
    rooted = service.get_workspace(root_id=child.id)
    assert structural.id in _edge_ids(rooted)
    assert ordinary.id in _edge_ids(rooted)
    assert structural.id in _edge_ids(overview)
    assert ordinary.id in _edge_ids(overview)
