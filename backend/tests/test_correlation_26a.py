"""PHASE 26A correlation and semantic summary tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import Edge, Job, Object, Representation
from app.jobs.constants import JOB_TYPE_CORRELATE_OBJECT, JOB_TYPE_SUMMARIZE_RESOURCE
from app.llm.correlation_judge import FakeCorrelationJudge
from app.llm.summarizer import FakeSummarizer
from app.services.correlation_candidate_service import CorrelationCandidateService
from app.services.correlation_constants import (
    CORRELATION_MAX_FINAL_CANDIDATES,
    CORRELATION_MIN_CONFIDENCE,
    SEMANTIC_SUMMARY_METADATA_KEY,
    SEMANTIC_SUMMARY_REVISION_KEY,
)
from app.services.correlation_models import CorrelationDecision
from app.services.correlation_service import CorrelationService
from app.services.deterministic_relation_service import DeterministicRelationService
from app.services.folder_object_service import FolderObjectService, build_folder_external_id
from app.services.graph_service import GraphService
from app.services.relation_decision_service import RelationDecisionService
from app.services.representation_service import KIND_SUMMARY, RepresentationService
from app.services.semantic_summary_service import SemanticSummaryService
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _create_email(
    graph: GraphService,
    title: str,
    metadata: dict,
    provider: str = "gmail",
    external_id: str | None = None,
) -> Object:
    return graph.create_object(
        ObjectCreate(
            kind="email",
            title=title,
            origin="source",
            provider=provider,
            external_id=external_id or str(uuid4()),
            metadata=metadata,
            occurred_at=datetime.now(UTC),
        )
    )


def test_gmail_same_thread_deterministic_related_to(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    deterministic = DeterministicRelationService(db_session, BOOTSTRAP_USER_ID)
    a = _create_email(
        graph,
        "A",
        {"thread_id": "thread-1"},
        external_id="msg-a",
    )
    b = _create_email(
        graph,
        "B",
        {"thread_id": "thread-1"},
        external_id="msg-b",
    )
    created = deterministic.apply_source_relations(a.id)
    assert created == 1
    deterministic.apply_source_relations(a.id)
    count = db_session.scalar(
        select(func.count()).select_from(Edge).where(
            Edge.source_id == a.id,
            Edge.target_id == b.id,
            Edge.type == "related_to",
        )
    )
    assert count == 1
    edge = db_session.scalar(
        select(Edge).where(
            Edge.source_id == a.id,
            Edge.target_id == b.id,
            Edge.type == "related_to",
        )
    )
    assert edge is not None
    assert edge.type == "related_to"
    assert edge.origin == "source"
    assert edge.state == "observed"


def test_gmail_in_reply_to_creates_references(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    parent = _create_email(
        graph,
        "Parent",
        {"headers": {"message-id": "<parent@example.com>"}, "thread_id": "t1"},
        external_id="parent",
    )
    child = _create_email(
        graph,
        "Child",
        {
            "thread_id": "t1",
            "headers": {"in-reply-to": "<parent@example.com>"},
        },
        external_id="child",
    )
    DeterministicRelationService(db_session, BOOTSTRAP_USER_ID).apply_source_relations(child.id)
    edge = db_session.scalar(
        select(Edge).where(
            Edge.source_id == child.id,
            Edge.target_id == parent.id,
            Edge.type == "references",
        )
    )
    assert edge is not None
    assert edge.type == "references"


def test_candidate_service_caps_and_excludes_rejected(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    trigger = graph.create_object(
        ObjectCreate(kind="note", title="Seminar ADC project", origin="user")
    )
    for index in range(30):
        graph.create_object(
            ObjectCreate(
                kind="note",
                title=f"Neighbor {index} ADC",
                origin="user",
            )
        )
    rejected = graph.create_object(
        ObjectCreate(kind="note", title="Rejected ADC", origin="user", state="rejected")
    )
    candidates = CorrelationCandidateService(db_session, BOOTSTRAP_USER_ID).collect_candidates(
        trigger.id
    )
    assert len(candidates) <= CORRELATION_MAX_FINAL_CANDIDATES
    assert all(candidate.object_id != rejected.id for candidate in candidates)


def test_fake_judge_creates_proposed_edge(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    trigger = graph.create_object(
        ObjectCreate(
            kind="note",
            title="Trigger seminar",
            origin="user",
            metadata={"sender": "user@example.com"},
        )
    )
    target = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Task seminar",
            origin="user",
            metadata={"recipients": ["user@example.com"]},
        )
    )
    judge = FakeCorrelationJudge(
        decisions=[
            CorrelationDecision(
                target_object_id=target.id,
                relation_type="related_to",
                confidence=0.9,
                rationale="Совпадает название проекта.",
            )
        ]
    )
    created = CorrelationService(db_session, BOOTSTRAP_USER_ID, judge).run_correlation(trigger.id)
    assert created == 1
    edge = db_session.scalar(
        select(Edge).where(
            Edge.source_id == trigger.id,
            Edge.target_id == target.id,
            Edge.origin == "agent",
        )
    )
    assert edge is not None
    assert edge.origin == "agent"
    assert edge.state == "proposed"
    assert edge.confidence == 0.9


def test_low_confidence_ignored(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    trigger = graph.create_object(ObjectCreate(kind="note", title="T", origin="user"))
    target = graph.create_object(ObjectCreate(kind="task", title="X", origin="user"))
    judge = FakeCorrelationJudge(
        decisions=[
            CorrelationDecision(
                target_object_id=target.id,
                relation_type="related_to",
                confidence=0.5,
                rationale="weak",
            )
        ]
    )
    created = CorrelationService(db_session, BOOTSTRAP_USER_ID, judge).run_correlation(trigger.id)
    assert created == 0


def test_semantic_summary_small_text_without_llm(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    obj = graph.create_object(
        ObjectCreate(
            kind="document",
            title="Short",
            origin="user",
            metadata={"content_revision": "rev-1"},
        )
    )
    RepresentationService(
        db_session,
        BOOTSTRAP_USER_ID,
        summarizer=FakeSummarizer(),
    ).ingest_text_content(obj.id, "Короткий текст.")
    db_session.refresh(obj)
    assert obj.metadata_[SEMANTIC_SUMMARY_METADATA_KEY] == "Короткий текст."
    assert obj.metadata_[SEMANTIC_SUMMARY_REVISION_KEY] == "rev-1"


def test_semantic_summary_service_updates_representation(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    obj = graph.create_object(
        ObjectCreate(
            kind="document",
            title="Long",
            origin="user",
            metadata={"content_revision": "rev-2"},
        )
    )
    long_text = "слово " * 200
    RepresentationService(db_session, BOOTSTRAP_USER_ID).ingest_text_content(obj.id, long_text)
    summary = SemanticSummaryService(
        db_session,
        BOOTSTRAP_USER_ID,
        summarizer=FakeSummarizer(max_chars=120),
    ).update_summary_for_object(obj.id)
    assert summary is not None
    rep = db_session.scalar(
        select(Representation).where(
            Representation.object_id == obj.id,
            Representation.kind == KIND_SUMMARY,
        )
    )
    assert rep is not None
    db_session.refresh(obj)
    assert obj.metadata_[SEMANTIC_SUMMARY_METADATA_KEY] == summary


def test_folder_object_deterministic_external_id(db_session) -> None:
    from app.db.models import LocalDevice, LocalRoot

    device = LocalDevice(
        user_id=BOOTSTRAP_USER_ID,
        device_key="laptop",
        display_name="Laptop",
    )
    db_session.add(device)
    db_session.flush()
    root = LocalRoot(
        user_id=BOOTSTRAP_USER_ID,
        device_id=device.id,
        root_path="docs",
        default_policy="metadata_only",
    )
    db_session.add(root)
    db_session.flush()
    folder = FolderObjectService(db_session, BOOTSTRAP_USER_ID).ensure_folder_for_root(device, root)
    assert folder.kind == "folder"
    assert folder.external_id == build_folder_external_id("laptop", "docs")


def test_relation_decision_confirm_and_reject(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = graph.create_object(ObjectCreate(kind="note", title="S", origin="user"))
    target = graph.create_object(ObjectCreate(kind="task", title="T", origin="user"))
    edge = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type="related_to",
            origin="agent",
            state="proposed",
            confidence=0.9,
        )
    )
    service = RelationDecisionService(db_session, BOOTSTRAP_USER_ID)
    confirmed = service.apply_decision(edge.id, "confirm")
    assert confirmed.state == "confirmed"
    rejected_edge = graph.create_edge(
        EdgeCreate(
            source_id=source.id,
            target_id=target.id,
            type="references",
            origin="agent",
            state="proposed",
            confidence=0.9,
        )
    )
    rejected = service.apply_decision(rejected_edge.id, "reject")
    assert rejected.state == "rejected"
