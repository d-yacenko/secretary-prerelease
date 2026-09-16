import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.schemas import ObjectCreate
from app.db.models import Edge, Object
from app.services.domain_tool_service import DomainToolService
from app.services.graph_service import GraphService
from app.services.provenance import AGENT_ORIGIN, PROPOSED_STATE
from app.tools.executor import ToolExecutor
from app.tools.schemas import (
    MAX_CONTEXT_CHARS,
    CreateTaskInput,
    GetContextInput,
    GetObjectInput,
    LinkObjectsInput,
    ListNeighborsInput,
    SearchObjectsInput,
    ToolError,
    UpdateTaskInput,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture
def domain_tools(db_session, fake_embedding_service) -> DomainToolService:
    return DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)


def _create_task(graph: GraphService, title: str) -> Object:
    return graph.create_object(
        ObjectCreate(kind="task", title=title, origin="user")
    )


def test_search_objects_reads_existing_objects(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    _create_task(graph, "Find me unique alpha marker")

    result = domain_tools.search_objects(
        SearchObjectsInput(query="alpha marker", limit=10)
    )
    assert len(result.objects) >= 1
    assert any(obj.title == "Find me unique alpha marker" for obj in result.objects)


def test_get_object_returns_one_object(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = _create_task(graph, "Single object lookup")

    result = domain_tools.get_object(GetObjectInput(object_id=task.id))
    assert result.object.id == task.id
    assert result.object.title == "Single object lookup"


def test_get_context_returns_bounded_context(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = _create_task(graph, "Bounded context task")

    result = domain_tools.get_context(
        GetContextInput(object_id=task.id, max_chars=200)
    )
    assert result.total_chars <= 200
    assert len(result.items) >= 1


def test_list_neighbors_returns_graph_neighbors(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    left = _create_task(graph, "Neighbor left")
    right = _create_task(graph, "Neighbor right")
    from app.api.schemas import EdgeCreate

    graph.create_edge(
        EdgeCreate(
            source_id=left.id,
            target_id=right.id,
            type="related_to",
            origin="system",
            state="observed",
        )
    )

    result = domain_tools.list_neighbors(ListNeighborsInput(object_id=left.id))
    assert result.object_id == left.id
    assert len(result.neighbors) == 1
    assert result.neighbors[0].object.id == right.id


def test_create_task_creates_agent_proposed_task_with_confidence(
    db_session, domain_tools
) -> None:
    result = domain_tools.create_task(
        CreateTaskInput(title="Agent inferred task", confidence=0.77)
    )
    obj = result.object
    assert obj.kind == "task"
    assert obj.origin == AGENT_ORIGIN
    assert obj.state == PROPOSED_STATE
    assert obj.confidence == 0.77


def test_link_objects_creates_agent_proposed_edge_with_confidence(
    db_session, domain_tools
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _create_task(graph, "Link source")
    target = _create_task(graph, "Link target")

    result = domain_tools.link_objects(
        LinkObjectsInput(
            source_id=source.id,
            target_id=target.id,
            relation_type="related_to",
            confidence=0.66,
        )
    )
    edge = result.edge
    assert edge.origin == AGENT_ORIGIN
    assert edge.state == PROPOSED_STATE
    assert edge.confidence == 0.66


def test_link_objects_self_link_rejected(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = _create_task(graph, "Self link task")
    with pytest.raises(ToolError):
        domain_tools.link_objects(
            LinkObjectsInput(
                source_id=task.id,
                target_id=task.id,
                relation_type="related_to",
                confidence=0.5,
            )
        )


def test_link_objects_exact_duplicate_is_idempotent(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _create_task(graph, "Dup source")
    target = _create_task(graph, "Dup target")
    first = domain_tools.link_objects(
        LinkObjectsInput(
            source_id=source.id,
            target_id=target.id,
            relation_type="related_to",
            confidence=0.5,
        )
    )
    second = domain_tools.link_objects(
        LinkObjectsInput(
            source_id=source.id,
            target_id=target.id,
            relation_type="related_to",
            confidence=0.5,
        )
    )
    assert first.created is True
    assert second.created is False
    assert second.edge.id == first.edge.id
    count = db_session.scalar(
        select(func.count()).select_from(Edge).where(
            Edge.source_id == source.id,
            Edge.target_id == target.id,
            Edge.type == "related_to",
        )
    )
    assert count == 1


def test_update_task_cannot_rewrite_origin(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = _create_task(graph, "Immutable origin task")

    updated = domain_tools.update_task(
        UpdateTaskInput(object_id=task.id, title="Renamed task")
    )
    assert updated.object.title == "Renamed task"
    assert updated.object.origin == "user"
    assert "origin" not in UpdateTaskInput.model_fields


def test_read_tools_do_not_mutate_db_state(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = _create_task(graph, "Read only task")
    before_objects = db_session.scalar(select(func.count()).select_from(Object))
    before_edges = db_session.scalar(select(func.count()).select_from(Edge))

    domain_tools.search_objects(SearchObjectsInput(query="Read only"))
    domain_tools.get_object(GetObjectInput(object_id=task.id))
    domain_tools.get_context(GetContextInput(object_id=task.id, max_chars=500))
    domain_tools.list_neighbors(ListNeighborsInput(object_id=task.id))

    after_objects = db_session.scalar(select(func.count()).select_from(Object))
    after_edges = db_session.scalar(select(func.count()).select_from(Edge))
    assert before_objects == after_objects
    assert before_edges == after_edges


def test_invalid_object_id_returns_controlled_tool_error(db_session, domain_tools) -> None:
    missing_id = uuid.uuid4()
    executor = ToolExecutor(domain_tools, max_calls=5)
    result = executor.execute("get_object", {"object_id": str(missing_id)})
    assert not result.success
    assert result.error


def test_get_context_rejects_max_chars_above_cap() -> None:
    with pytest.raises(ValidationError):
        GetContextInput(object_id=uuid.uuid4(), max_chars=MAX_CONTEXT_CHARS + 1)


def test_create_task_normalizes_naive_due_at_timezone(db_session, domain_tools) -> None:
    naive_due = datetime(2026, 6, 15, 9, 30, 0)  # noqa: DTZ001
    result = domain_tools.create_task(
        CreateTaskInput(title="Due task", confidence=0.5, due_at=naive_due)
    )
    due_at = result.object.due_at
    assert due_at is not None
    assert due_at.tzinfo is not None


def test_independent_tool_executors_do_not_share_call_limit(
    db_session, fake_embedding_service
) -> None:
    tools_a = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    tools_b = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = _create_task(graph, "Executor isolation task")

    executor_a = ToolExecutor(tools_a, max_calls=5)
    executor_b = ToolExecutor(tools_b, max_calls=5)
    for _ in range(5):
        assert executor_a.execute("get_object", {"object_id": str(task.id)}).success
    assert not executor_a.execute("get_object", {"object_id": str(task.id)}).success
    assert executor_b.execute("get_object", {"object_id": str(task.id)}).success


def test_tool_call_limit_prevents_infinite_loop(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = _create_task(graph, "Limit task")
    executor = ToolExecutor(domain_tools, max_calls=5)

    for _ in range(5):
        ok = executor.execute("get_object", {"object_id": str(task.id)})
        assert ok.success

    blocked = executor.execute("get_object", {"object_id": str(task.id)})
    assert not blocked.success
    assert blocked.limit_reached
    assert executor.calls_made == 5
