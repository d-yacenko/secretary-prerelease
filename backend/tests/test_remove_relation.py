"""PHASE 28D-B-R1 — remove_relation tool contract tests."""

import uuid

import pytest
from sqlalchemy import func, select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.assistant.execution_effects import (
    classify_tool_execution_effect,
    describe_execution_effect,
)
from app.assistant.reference_ids import collect_seen_edge_ids_from_bounded_tool
from app.assistant.tool_runner import BoundAssistantToolRunner, PerTurnToolBudget
from app.db.models import Edge, Object, User
from app.llm.openai_assistant_provider import FINALIZATION_INSTRUCTIONS, SYSTEM_INSTRUCTIONS
from app.services.domain_tool_service import DomainToolService
from app.services.domain_write_mode import DomainWriteMode
from app.services.graph_service import GraphService
from app.services.provenance import (
    AGENT_ORIGIN,
    CONFIRMED_STATE,
    PROPOSED_STATE,
    REJECTED_STATE,
    SOURCE_ORIGIN,
    USER_ORIGIN,
)
from app.tools.assistant_contracts import ASSISTANT_FUNCTION_SCHEMAS
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.policy import PolicyDecision, ToolPermission, evaluate_policy
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import RemoveRelationInput, ToolError, UpdateTaskInput
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture
def domain_tools(db_session, fake_embedding_service) -> DomainToolService:
    return DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)


def _create_task(graph: GraphService, title: str, origin: str = USER_ORIGIN) -> Object:
    return graph.create_object(ObjectCreate(kind="task", title=title, origin=origin))


def _create_email(graph: GraphService, title: str) -> Object:
    return graph.create_object(ObjectCreate(kind="email", title=title, origin=SOURCE_ORIGIN))


def test_remove_relation_active_edge_becomes_rejected(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = _create_task(graph, "Task with evidence")
    evidence = _create_email(graph, "Evidence mail")
    edge = graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=evidence.id,
            type="references",
            origin=AGENT_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    result = domain_tools.remove_relation(RemoveRelationInput(edge_id=edge.id))
    assert result.changed is True
    assert result.previous_state == CONFIRMED_STATE
    assert result.new_state == REJECTED_STATE
    assert result.edge.state == REJECTED_STATE
    db_session.expire_all()
    persisted = db_session.get(Edge, edge.id)
    assert persisted is not None
    assert persisted.state == REJECTED_STATE


def test_remove_relation_already_rejected_is_no_op(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = _create_task(graph, "Task")
    other = _create_task(graph, "Related")
    edge = graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=other.id,
            type="related_to",
            origin=USER_ORIGIN,
            state=REJECTED_STATE,
        )
    )
    result = domain_tools.remove_relation(RemoveRelationInput(edge_id=edge.id))
    assert result.changed is False
    assert result.previous_state == REJECTED_STATE
    assert result.new_state == REJECTED_STATE


def test_remove_relation_cross_user_edge_rejected(db_session, fake_embedding_service) -> None:
    other_user = uuid.uuid4()
    db_session.add(User(id=other_user, display_name="other"))
    db_session.flush()
    owner_tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    other_graph = GraphService(db_session, other_user)
    left = _create_task(other_graph, "Other task")
    right = _create_task(other_graph, "Other neighbor")
    edge = other_graph.create_edge(
        EdgeCreate(
            source_id=left.id,
            target_id=right.id,
            type="related_to",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    with pytest.raises(ToolError, match="edge not found"):
        owner_tools.remove_relation(RemoveRelationInput(edge_id=edge.id))


def test_remove_relation_protected_contains_edge(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    parent = _create_task(graph, "Thread parent")
    child = _create_task(graph, "Thread child")
    edge = graph.create_edge(
        EdgeCreate(
            source_id=parent.id,
            target_id=child.id,
            type="contains",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    with pytest.raises(ToolError, match="protected"):
        domain_tools.remove_relation(RemoveRelationInput(edge_id=edge.id))


def test_remove_relation_source_origin_semantic_edge_blocked(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = _create_task(graph, "Task")
    evidence = _create_email(graph, "Mail")
    edge = graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=evidence.id,
            type="references",
            origin=SOURCE_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    with pytest.raises(ToolError, match="source structural"):
        domain_tools.remove_relation(RemoveRelationInput(edge_id=edge.id))


def test_update_task_evidence_omission_does_not_remove_edge(db_session, domain_tools) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = _create_task(graph, "Evidence task")
    keep = _create_email(graph, "Keep evidence")
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=keep.id,
            type="references",
            origin=AGENT_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    result = domain_tools.update_task(
        UpdateTaskInput(object_id=task.id, title="Evidence task retitled")
    )
    assert result.changed is True
    edge_count = db_session.scalar(
        select(func.count()).select_from(Edge).where(
            Edge.source_id == task.id,
            Edge.state != REJECTED_STATE,
        )
    )
    assert edge_count == 1


def test_remove_relation_requires_approval_in_interactive_assistant() -> None:
    assert (
        evaluate_policy(
            ToolPermission.DESTRUCTIVE_INTERNAL_WRITE,
            ExecutionContext.INTERACTIVE_ASSISTANT,
        )
        == PolicyDecision.REQUIRE_APPROVAL
    )


def test_gateway_remove_relation_stages_without_execution(db_session, fake_embedding_service) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _create_task(graph, "Stage remove")
    other = _create_task(graph, "Neighbor")
    edge = graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=other.id,
            type="related_to",
            origin=USER_ORIGIN,
            state=PROPOSED_STATE,
        )
    )
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    gateway = ToolExecutionGateway()
    result = gateway.execute(
        tools,
        "remove_relation",
        {"edge_id": str(edge.id)},
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    db_session.expire_all()
    assert db_session.get(Edge, edge.id).state == PROPOSED_STATE


def test_approved_remove_relation_executes_exact_edge_id(
    db_session, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _create_task(graph, "Approved remove")
    other = _create_task(graph, "To unlink")
    edge = graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=other.id,
            type="related_to",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    tools = DomainToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        fake_embedding_service,
        write_mode=DomainWriteMode.APPROVED_CONFIRMED,
    )
    gateway = ToolExecutionGateway()
    result = gateway.execute(
        tools,
        "remove_relation",
        {"edge_id": str(edge.id)},
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert result.success is True
    assert result.output["changed"] is True
    db_session.expire_all()
    assert db_session.get(Edge, edge.id).state == REJECTED_STATE


def test_assistant_edge_id_allowlist_requires_list_neighbors(
    db_session, fake_embedding_service, monkeypatch
) -> None:
    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(db_session, name)

    import app.assistant.session as assistant_session_module

    monkeypatch.setattr(assistant_session_module, "SessionLocal", lambda: _TestSession())
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = _create_task(graph, "Allowlist task")
    other = _create_task(graph, "Allowlist neighbor")
    edge = graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=other.id,
            type="related_to",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    db_session.flush()
    budget = PerTurnToolBudget()
    runner = BoundAssistantToolRunner(budget, BOOTSTRAP_USER_ID)
    blocked = runner("remove_relation", {"edge_id": str(edge.id)})
    assert blocked.success is False
    assert "list_neighbors" in (blocked.error or "")

    runner("list_neighbors", {"object_id": str(task.id)})
    budget.commit_model_visible_outputs()
    allowed = runner("remove_relation", {"edge_id": str(edge.id)})
    assert allowed.status == ToolExecutionStatus.APPROVAL_REQUIRED


def test_list_neighbors_exposes_edge_ids_for_allowlist() -> None:
    bounded = {
        "neighbors": [
            {
                "object": {"id": "00000000-0000-0000-0000-000000000001"},
                "edge": {"id": "00000000-0000-0000-0000-0000000000aa"},
            }
        ]
    }
    edge_ids = collect_seen_edge_ids_from_bounded_tool("list_neighbors", bounded)
    assert len(edge_ids) == 1


def test_execution_effect_classification() -> None:
    assert classify_tool_execution_effect(
        "update_task",
        {"changed": False, "object": {"id": "1"}},
    ) == "no_op"
    assert classify_tool_execution_effect(
        "remove_relation",
        {"changed": True, "edge": {"id": "e1", "type": "related_to"}},
    ) == "removed"
    assert classify_tool_execution_effect(
        "remove_relation",
        {"changed": False},
    ) == "no_op"
    no_op_desc = describe_execution_effect(
        "update_task",
        {"changed": False, "evidence_already_linked_object_ids": ["a"]},
    )
    assert "changed=false" in no_op_desc
    removed_desc = describe_execution_effect(
        "remove_relation",
        {
            "changed": True,
            "edge": {"id": "e1", "type": "references"},
            "previous_state": "confirmed",
        },
    )
    assert "deactivated" in removed_desc


def test_assistant_contracts_distinguish_add_vs_remove() -> None:
    update = ASSISTANT_FUNCTION_SCHEMAS["update_task"]["description"].lower()
    remove = ASSISTANT_FUNCTION_SCHEMAS["remove_relation"]["description"].lower()
    assert "additive" in update
    assert "never removes" in update or "does not" in update
    assert "edge_id" in remove
    assert "additive" in remove or "do not use update_task" in remove


def test_system_instructions_include_unsupported_mutation_rule() -> None:
    lowered = SYSTEM_INSTRUCTIONS.lower()
    assert "unsupported mutation" in lowered
    assert "do not approximate" in lowered


def test_finalization_instructions_distinguish_success_from_changed() -> None:
    lowered = FINALIZATION_INSTRUCTIONS.lower()
    assert "already been executed successfully" not in lowered
    assert "authoritative record" in lowered
    assert "changed=false" in lowered or "success=true does not mean changed=true" in lowered
