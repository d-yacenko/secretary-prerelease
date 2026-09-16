"""PHASE 24 closure — graph workspace cap and batch neighbor tests."""

from datetime import UTC, datetime

from app.api.schemas import EdgeCreate, ObjectCreate
from app.services.graph_service import GraphService
from app.services.graph_workspace_service import GraphWorkspaceService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE
from tests.conftest import BOOTSTRAP_USER_ID


def _task(graph: GraphService, title: str, status: str | None = "open") -> object:
    return graph.create_object(
        ObjectCreate(
            kind="task",
            title=title,
            origin="user",
            state=CONFIRMED_STATE,
            status=status,
            due_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        )
    )


def test_overview_node_limit_wins_over_seed_limit(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    for index in range(12):
        _task(graph, f"ACTIVE-{index}")
    db_session.flush()

    service = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID)
    result = service.get_workspace(seed_limit=12, node_limit=5)
    assert len(result.nodes) <= 5
    assert result.truncated is True


def test_twelve_active_tasks_with_node_limit_five(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    for index in range(12):
        _task(graph, f"CAP-{index}")
    db_session.flush()

    service = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID)
    result = service.get_workspace(seed_limit=12, neighbor_limit=12, node_limit=5)
    assert len(result.nodes) == 5
    assert result.truncated is True
    node_ids = {node.id for node in result.nodes}
    for edge in result.edges:
        assert edge.source_id in node_ids
        assert edge.target_id in node_ids


def test_neighbor_limit_enforced(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    root = _task(graph, "ROOT")
    for index in range(8):
        neighbor = graph.create_object(
            ObjectCreate(kind="note", title=f"N-{index}", origin="user", state=CONFIRMED_STATE)
        )
        graph.create_edge(
            EdgeCreate(
                source_id=root.id,
                target_id=neighbor.id,
                type="references",
                origin="user",
                state=CONFIRMED_STATE,
            )
        )
    db_session.flush()

    service = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID)
    result = service.get_workspace(
        root_id=root.id,
        neighbor_limit=3,
        node_limit=80,
    )
    assert len(result.nodes) <= 4
    assert result.truncated is True


def test_cycle_bounded_unique_ids(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    a = _task(graph, "A")
    b = _task(graph, "B")
    c = _task(graph, "C")
    graph.create_edge(
        EdgeCreate(
            source_id=a.id,
            target_id=b.id,
            type="related_to",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=b.id,
            target_id=c.id,
            type="depends_on",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=c.id,
            target_id=a.id,
            type="references",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    db_session.flush()

    service = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID)
    result = service.get_workspace(root_id=a.id, neighbor_limit=12, node_limit=80)
    node_ids = [node.id for node in result.nodes]
    edge_ids = [edge.id for edge in result.edges]
    assert len(node_ids) == len(set(node_ids))
    assert len(edge_ids) == len(set(edge_ids))


def test_duplicate_neighbor_edges_do_not_exceed_node_cap(db_session, fake_embedding_service):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    seeds = [_task(graph, f"SEED-{index}") for index in range(6)]
    shared = graph.create_object(
        ObjectCreate(kind="note", title="SHARED", origin="user", state=CONFIRMED_STATE)
    )
    for seed in seeds:
        graph.create_edge(
            EdgeCreate(
                source_id=seed.id,
                target_id=shared.id,
                type="references",
                origin="user",
                state=CONFIRMED_STATE,
            )
        )
    db_session.flush()

    service = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID)
    result = service.get_workspace(seed_limit=6, neighbor_limit=6, node_limit=4)
    assert len(result.nodes) <= 4
    assert result.truncated is True


def test_rooted_zero_node_budget_with_hidden_neighbors_truncated(
    db_session, fake_embedding_service,
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    root = _task(graph, "ROOT")
    for index in range(3):
        neighbor = graph.create_object(
            ObjectCreate(kind="note", title=f"N-{index}", origin="user", state=CONFIRMED_STATE)
        )
        graph.create_edge(
            EdgeCreate(
                source_id=root.id,
                target_id=neighbor.id,
                type="references",
                origin="user",
                state=CONFIRMED_STATE,
            )
        )
    db_session.flush()

    service = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID)
    result = service.get_workspace(root_id=root.id, neighbor_limit=12, node_limit=1)
    assert len(result.nodes) == 1
    assert result.truncated is True


def test_overview_zero_node_budget_with_hidden_neighbor_truncated(
    db_session, fake_embedding_service,
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    seed = _task(graph, "ONLY-SEED")
    neighbor = graph.create_object(
        ObjectCreate(kind="note", title="NEIGHBOR", origin="user", state=CONFIRMED_STATE)
    )
    graph.create_edge(
        EdgeCreate(
            source_id=seed.id,
            target_id=neighbor.id,
            type="references",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    db_session.flush()

    service = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID)
    result = service.get_workspace(seed_limit=1, neighbor_limit=12, node_limit=1)
    assert len(result.nodes) == 1
    assert result.truncated is True


def test_rooted_no_eligible_neighbors_not_truncated(
    db_session, fake_embedding_service,
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    root = _task(graph, "ALONE")
    db_session.flush()

    service = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID)
    result = service.get_workspace(root_id=root.id, neighbor_limit=12, node_limit=1)
    assert len(result.nodes) == 1
    assert result.truncated is False


def test_rejected_neighbor_does_not_force_truncated_at_zero_budget(
    db_session, fake_embedding_service,
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    root = _task(graph, "ROOT")
    rejected = graph.create_object(
        ObjectCreate(
            kind="note",
            title="Rejected",
            origin="user",
            state=REJECTED_STATE,
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=root.id,
            target_id=rejected.id,
            type="references",
            origin="user",
            state=CONFIRMED_STATE,
        )
    )
    db_session.flush()

    service = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID)
    result = service.get_workspace(root_id=root.id, neighbor_limit=12, node_limit=1)
    assert len(result.nodes) == 1
    assert result.truncated is False


def test_overview_per_seed_neighbor_limit_with_high_degree_seed(
    db_session, fake_embedding_service,
):
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    hub = _task(graph, "HUB")
    other_seeds = [_task(graph, f"SEED-{index}") for index in range(2)]
    for index in range(8):
        neighbor = graph.create_object(
            ObjectCreate(kind="note", title=f"HUB-N-{index}", origin="user", state=CONFIRMED_STATE)
        )
        graph.create_edge(
            EdgeCreate(
                source_id=hub.id,
                target_id=neighbor.id,
                type="references",
                origin="user",
                state=CONFIRMED_STATE,
            )
        )
    db_session.flush()

    service = GraphWorkspaceService(db_session, BOOTSTRAP_USER_ID)
    result = service.get_workspace(
        seed_limit=3,
        neighbor_limit=2,
        node_limit=80,
    )
    hub_neighbors = [
        node
        for node in result.nodes
        if node.id != hub.id and node.title.startswith("HUB-N-")
    ]
    assert len(hub_neighbors) <= 2
    assert result.truncated is True
