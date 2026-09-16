"""PHASE 22.6 final provenance closure — model-visible serialization and effective updates."""

import json
import uuid

import pytest
from sqlalchemy import func, select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.assistant.constants import MAX_UI_CONTEXT_CHARS
from app.assistant.reference_ids import (
    collect_object_ids_from_bounded_tool,
    collect_seen_object_ids_from_bounded_tool,
)
from app.assistant.tool_output import (
    AssistantToolModelOutput,
    serialize_tool_output_for_assistant,
    serialize_tool_output_for_model,
)
from app.assistant.tool_runner import PerTurnToolBudget
from app.db.models import Job
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT
from app.llm.fake_assistant_provider import FakeAssistantProvider
from app.services.assistant_service import AssistantService
from app.services.domain_tool_service import DomainToolService
from app.services.graph_service import GraphService
from app.services.notification_service import NotificationService
from app.services.provenance import AGENT_ORIGIN, PROPOSED_STATE
from app.tools.schemas import ToolError, UpdateTaskInput
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture
def domain_tools(db_session, fake_embedding_service) -> DomainToolService:
    return DomainToolService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)


@pytest.fixture(autouse=True)
def patch_assistant_tool_session(db_session, fake_embedding_service, monkeypatch):
    from app.assistant.tool_args import normalize_assistant_tool_arguments
    from app.tools.executor import ToolExecutionResult, _dispatch
    from app.tools.results import ToolExecutionStatus

    def _run(user_id, tool_name, arguments):
        try:
            normalized_arguments = normalize_assistant_tool_arguments(tool_name, arguments)
        except ToolError as exc:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error=exc.message,
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        nested = db_session.begin_nested()
        tools = DomainToolService(
            db_session,
            user_id,
            fake_embedding_service,
            defer_write_embeddings=True,
        )
        try:
            output = _dispatch(tools, tool_name, normalized_arguments)
            nested.commit()
            return ToolExecutionResult(
                success=True,
                tool_name=tool_name,
                output=output.model_dump(mode="json"),
            )
        except ToolError as exc:
            nested.rollback()
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error=exc.message,
                status=ToolExecutionStatus.TOOL_ERROR,
            )
        except Exception as exc:  # noqa: BLE001
            nested.rollback()
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                error=f"tool execution failed: {type(exc).__name__}",
                status=ToolExecutionStatus.EXECUTION_FAILED,
            )

    monkeypatch.setattr("app.assistant.session.run_assistant_tool", _run)

    class _TestSession:
        def __init__(self) -> None:
            self._session = db_session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    monkeypatch.setattr(
        "app.services.assistant_service.SessionLocal",
        lambda: _TestSession(),
    )


def test_model_visible_payload_matches_json_not_intermediate_bounded(
    monkeypatch, db_session, domain_tools, fake_embedding_service
) -> None:
    monkeypatch.setattr("app.assistant.tool_output.MAX_ASSISTANT_TOOL_OUTPUT_CHARS", 400)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    center = graph.create_object(
        ObjectCreate(kind="task", title="Neighbor center task", origin="user")
    )
    visible_neighbor = graph.create_object(
        ObjectCreate(
            kind="email",
            title="VISIBLE_NEIGHBOR_MARKER",
            body="x" * 300,
            origin="source",
            provider="gmail",
        )
    )
    hidden_neighbor = graph.create_object(
        ObjectCreate(
            kind="email",
            title="HIDDEN_NEIGHBOR_MARKER",
            body="y" * 300,
            origin="source",
            provider="gmail",
        )
    )
    for neighbor in (visible_neighbor, hidden_neighbor):
        graph.create_edge(
            EdgeCreate(
                source_id=center.id,
                target_id=neighbor.id,
                type="references",
                origin=AGENT_ORIGIN,
                state=PROPOSED_STATE,
                confidence=0.7,
            )
        )
    db_session.flush()

    raw = domain_tools.list_neighbors(
        __import__("app.tools.schemas", fromlist=["ListNeighborsInput"]).ListNeighborsInput(
            object_id=center.id, limit=20
        )
    ).model_dump(mode="json")
    intermediate = serialize_tool_output_for_model("list_neighbors", raw)
    model_output = serialize_tool_output_for_assistant("list_neighbors", raw)
    parsed = json.loads(model_output.model_output_json)
    assert parsed == model_output.model_visible_payload
    assert model_output.model_visible_payload.get("truncated") is True
    assert "preview_chars" in model_output.model_visible_payload

    hidden_in_intermediate = any(
        neighbor.get("object", {}).get("id") == str(hidden_neighbor.id)
        for neighbor in intermediate.get("neighbors", [])
    )
    assert hidden_in_intermediate
    assert not collect_seen_object_ids_from_bounded_tool(
        "list_neighbors", model_output.model_visible_payload
    )

    budget = PerTurnToolBudget()
    budget.run(
        BOOTSTRAP_USER_ID,
        "list_neighbors",
        {"object_id": str(center.id), "limit": 20},
    )
    assert hidden_neighbor.id not in budget.seen_object_ids
    create = budget.run(
        BOOTSTRAP_USER_ID,
        "create_task",
        {
            "title": "Should fail hidden evidence",
            "confidence": 0.7,
            "evidence_object_ids": [str(hidden_neighbor.id)],
        },
    )
    assert not create.success
    assert create.error == "evidence object was not exposed in this Assistant turn"


def test_retrieve_and_get_context_ids_still_seen(
    db_session, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    email = graph.create_object(
        ObjectCreate(
            kind="email",
            title="PROVENANCE_RETRIEVE_MARKER",
            body="retrieve body",
            origin="source",
            provider="gmail",
        )
    )
    db_session.flush()

    budget = PerTurnToolBudget()
    budget.run(
        BOOTSTRAP_USER_ID,
        "retrieve",
        {"query": "PROVENANCE_RETRIEVE_MARKER", "limit": 5},
    )
    assert email.id in budget.pending_seen_object_ids
    assert email.id not in budget.seen_object_ids
    budget.commit_model_visible_outputs()
    assert email.id in budget.seen_object_ids

    budget.run(
        BOOTSTRAP_USER_ID,
        "get_context",
        {"object_id": str(email.id), "max_chars": 2000},
    )
    assert email.id in budget.pending_seen_object_ids
    budget.commit_model_visible_outputs()
    assert email.id in budget.seen_object_ids


def test_ui_context_truncation_drops_unexposed_notification_source_id(
    db_session, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    source = graph.create_object(
        ObjectCreate(
            kind="email",
            title="Truncated source email",
            body="source",
            origin="source",
            provider="gmail",
        )
    )
    notifications = NotificationService(db_session, BOOTSTRAP_USER_ID)
    notification = notifications.create(
        title="T" * 600,
        body="B" * 500,
        priority="normal",
        proposal={"detail": "P" * 2000},
        source_object_id=source.id,
    )
    db_session.flush()

    service = AssistantService(BOOTSTRAP_USER_ID, FakeAssistantProvider())
    result = service._build_ui_context(None, notification.id)
    assert len(result.text) <= MAX_UI_CONTEXT_CHARS
    assert str(source.id) not in result.text
    assert source.id not in result.exposed_object_ids


def test_update_task_same_title_not_changed(
    db_session, domain_tools, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Stable title task",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.7,
        )
    )
    jobs_before = db_session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.type == JOB_TYPE_EMBED_OBJECT)
    )

    updated = domain_tools.update_task(
        UpdateTaskInput(object_id=task.id, title="Stable title task")
    )
    assert updated.changed is False
    jobs_after = db_session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.type == JOB_TYPE_EMBED_OBJECT)
    )
    assert jobs_after == jobs_before

    raw_output = updated.model_dump(mode="json")
    bounded = serialize_tool_output_for_assistant("update_task", raw_output).model_visible_payload
    candidate_ids: list[uuid.UUID] = []
    affected_ids: list[uuid.UUID] = []
    collect_object_ids_from_bounded_tool(
        "update_task", bounded, candidate_ids, affected_ids
    )
    assert task.id in candidate_ids
    assert not affected_ids


def test_update_task_same_status_and_existing_evidence_not_changed(
    db_session, domain_tools, fake_embedding_service
) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Status noop task",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            status="pending",
            confidence=0.65,
        )
    )
    email = graph.create_object(
        ObjectCreate(
            kind="email",
            title="Already linked email",
            origin="source",
            provider="gmail",
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=email.id,
            type="references",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.65,
        )
    )

    updated = domain_tools.update_task(
        UpdateTaskInput(
            object_id=task.id,
            status="pending",
            evidence_object_ids=[email.id],
        )
    )
    assert updated.changed is False
    assert updated.evidence_edges_created == 0


def test_update_task_new_title_changed_and_embed(
    db_session, fake_embedding_service
) -> None:
    tools = DomainToolService(
        db_session,
        BOOTSTRAP_USER_ID,
        fake_embedding_service,
        defer_write_embeddings=True,
    )
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service)
    task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Old effective title",
            origin=AGENT_ORIGIN,
            state=PROPOSED_STATE,
            confidence=0.6,
        )
    )
    jobs_before = db_session.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.type == JOB_TYPE_EMBED_OBJECT,
            Job.payload["object_id"].as_string() == str(task.id),
        )
    )

    updated = tools.update_task(
        UpdateTaskInput(object_id=task.id, title="New effective title")
    )
    assert updated.changed is True
    jobs_after = db_session.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.type == JOB_TYPE_EMBED_OBJECT,
            Job.payload["object_id"].as_string() == str(task.id),
        )
    )
    assert jobs_after == jobs_before + 1

    raw_output = updated.model_dump(mode="json")
    bounded = serialize_tool_output_for_assistant("update_task", raw_output).model_visible_payload
    affected_ids: list[uuid.UUID] = []
    collect_object_ids_from_bounded_tool(
        "update_task", bounded, [], affected_ids
    )
    assert task.id in affected_ids


def test_serialize_tool_output_for_assistant_returns_dataclass() -> None:
    raw = {
        "object": {
            "id": str(uuid.uuid4()),
            "kind": "task",
            "title": "x",
            "origin": AGENT_ORIGIN,
            "state": PROPOSED_STATE,
        },
        "changed": False,
        "evidence_edges_created": 0,
    }
    result = serialize_tool_output_for_assistant("update_task", raw)
    assert isinstance(result, AssistantToolModelOutput)
    assert json.loads(result.model_output_json) == result.model_visible_payload
