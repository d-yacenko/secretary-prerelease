"""PHASE 22.6 — task evidence binding and retrieval lifecycle fields."""

import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import Edge, Object, User
from app.services.context_service import ContextService
from app.services.domain_tool_service import DomainToolService
from app.services.graph_service import GraphService
from app.services.provenance import AGENT_ORIGIN, PROPOSED_STATE
from app.tools.schemas import (
    MAX_TASK_EVIDENCE_IDS,
    CreateTaskInput,
    ListNeighborsInput,
    RetrieveInput,
    ToolError,
    UpdateTaskInput,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def domain_tools(db_session, fake_embedding_service) -> DomainToolService:
    return DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)


@pytest.fixture
def user_b_id(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="User B"))
    db_session.flush()
    return user_id


def _create_evidence(
    graph: GraphService,
    *,
    kind: str = "email",
    title: str,
    provider: str = "gmail",
) -> Object:
    return graph.create_object(
        ObjectCreate(
            kind=kind,
            title=title,
            body=f"body for {title}",
            origin="source",
            provider=provider,
        )
    )


def test_retrieve_hit_includes_task_state_and_status(db_session, fake_embedding_service) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Lifecycle marker task",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            status="pending",
            confidence=0.7,
        )
    )
    db_session.flush()

    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    result = tools.retrieve(
        RetrieveInput(query="Lifecycle marker", kind="task", limit=5)
    )
    matched = next(hit for hit in result.hits if hit.object_id == task.id)
    assert matched.state == PROPOSED_STATE
    assert matched.status == "pending"


def test_create_task_with_evidence_edges(db_session, domain_tools, fake_embedding_service) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    event = _create_evidence(graph, kind="event", title="Evidence event marker", provider="google_calendar")
    email = _create_evidence(graph, title="Evidence email marker")

    result = domain_tools.create_task(
        CreateTaskInput(
            title="Task with structural evidence",
            confidence=0.82,
            evidence_object_ids=[email.id, event.id],
        )
    )
    assert result.object.kind == "task"
    assert result.object.origin == AGENT_ORIGIN
    assert result.object.state == PROPOSED_STATE

    edges = db_session.scalars(
        select(Edge).where(
            Edge.source_id == result.object.id,
            Edge.type == "references",
        )
    ).all()
    assert len(edges) == 2
    target_ids = {edge.target_id for edge in edges}
    assert email.id in target_ids
    assert event.id in target_ids
    for edge in edges:
        assert edge.origin == AGENT_ORIGIN
        assert edge.state == PROPOSED_STATE
        assert edge.user_id == BOOTSTRAP_USER_ID


def test_create_task_dedupes_evidence_ids(db_session, domain_tools, fake_embedding_service) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    email = _create_evidence(graph, title="Duplicate evidence marker")

    result = domain_tools.create_task(
        CreateTaskInput(
            title="Deduped evidence task",
            confidence=0.7,
            evidence_object_ids=[email.id, email.id],
        )
    )
    edges = db_session.scalars(
        select(Edge).where(Edge.source_id == result.object.id, Edge.type == "references")
    ).all()
    assert len(edges) == 1


def test_create_task_rejects_too_many_evidence_ids() -> None:
    ids = [uuid.uuid4() for _ in range(MAX_TASK_EVIDENCE_IDS + 1)]
    with pytest.raises(ValidationError):
        CreateTaskInput(title="Too much evidence", confidence=0.5, evidence_object_ids=ids)


def test_create_task_rejects_cross_user_evidence(
    db_session, domain_tools, fake_embedding_service, user_b_id
) -> None:
    graph_b = GraphService(db_session, user_b_id, fake_embedding_service)
    foreign = graph_b.create_object(
        ObjectCreate(kind="email", title="Foreign evidence", origin="source", provider="gmail")
    )

    before = db_session.scalar(select(func.count()).select_from(Object))
    before_edges = db_session.scalar(select(func.count()).select_from(Edge))
    with pytest.raises(ToolError, match="evidence object not found"):
        domain_tools.create_task(
            CreateTaskInput(
                title="Should not create",
                confidence=0.5,
                evidence_object_ids=[foreign.id],
            )
        )
    after = db_session.scalar(select(func.count()).select_from(Object))
    assert before == after
    after_edges = db_session.scalar(select(func.count()).select_from(Edge))
    assert before_edges == after_edges


def test_create_task_evidence_failure_leaves_no_task(
    db_session, domain_tools, fake_embedding_service, user_b_id
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    local = _create_evidence(graph, title="Valid local evidence")
    graph_b = GraphService(db_session, user_b_id, fake_embedding_service)
    foreign = graph_b.create_object(
        ObjectCreate(kind="email", title="Foreign mix evidence", origin="source", provider="gmail")
    )

    before_tasks = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.kind == "task")
    )
    with pytest.raises(ToolError):
        domain_tools.create_task(
            CreateTaskInput(
                title="Partial evidence should fail",
                confidence=0.6,
                evidence_object_ids=[local.id, foreign.id],
            )
        )
    after_tasks = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.kind == "task")
    )
    assert before_tasks == after_tasks


def test_list_neighbors_shows_evidence_relations(
    db_session, domain_tools, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    email = _create_evidence(graph, title="Neighbor evidence email")
    created = domain_tools.create_task(
        CreateTaskInput(
            title="Neighbor evidence task",
            confidence=0.75,
            evidence_object_ids=[email.id],
        )
    )

    neighbors = domain_tools.list_neighbors(
        ListNeighborsInput(object_id=created.object.id, limit=20)
    )
    neighbor_ids = {item.object.id for item in neighbors.neighbors}
    assert email.id in neighbor_ids


def test_context_includes_referenced_evidence(db_session, fake_embedding_service) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    email = _create_evidence(graph, title="Context evidence email")
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    created = tools.create_task(
        CreateTaskInput(
            title="Context evidence task",
            confidence=0.8,
            evidence_object_ids=[email.id],
        )
    )

    context = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    result = context.build_context(object_id=created.object.id, max_chars=4000)
    included_ids = {item.object_id for item in result.items}
    assert email.id in included_ids


def test_update_task_attaches_missing_evidence_only(
    db_session, domain_tools, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    existing_task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Existing task for evidence update",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.7,
        )
    )
    first_email = _create_evidence(graph, title="First evidence email")
    second_email = _create_evidence(graph, title="Second evidence email")
    graph.create_edge(
        EdgeCreate(
            source_id=existing_task.id,
            target_id=first_email.id,
            type="references",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.7,
        )
    )

    updated = domain_tools.update_task(
        UpdateTaskInput(
            object_id=existing_task.id,
            evidence_object_ids=[first_email.id, second_email.id],
        )
    )
    assert updated.object.id == existing_task.id
    edges = db_session.scalars(
        select(Edge).where(
            Edge.source_id == existing_task.id,
            Edge.type == "references",
        )
    ).all()
    assert len(edges) == 2


def test_update_task_evidence_only_without_field_changes(
    db_session, domain_tools, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Evidence-only update task",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.65,
        )
    )
    email = _create_evidence(graph, title="Attach on update email")

    updated = domain_tools.update_task(
        UpdateTaskInput(object_id=task.id, evidence_object_ids=[email.id])
    )
    assert updated.object.title == "Evidence-only update task"
    edge = db_session.scalar(
        select(Edge).where(
            Edge.source_id == task.id,
            Edge.target_id == email.id,
            Edge.type == "references",
        )
    )
    assert edge is not None


def test_task_taxonomy_documented_in_decisions() -> None:
    decisions = (REPO_ROOT / "DECISIONS.md").read_text(encoding="utf-8")
    assert "kind=task" in decisions
    assert "todo_item" in decisions
    assert "Google Tasks" in decisions or "google_tasks" in decisions
