"""PHASE 26A closure corrective tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import Edge, Job, Object, Representation, User
from app.jobs.constants import (
    JOB_TYPE_CORRELATE_OBJECT,
    JOB_TYPE_EMBED_OBJECT,
    JOB_TYPE_SUMMARIZE_RESOURCE,
)
from app.llm.correlation_judge import CorrelationJudgeResult
from app.domain.task_lifecycle import TASK_STATUS_DELETED
from app.services.correlation_candidate_service import CorrelationCandidateService
from app.services.correlation_constants import (
    CANDIDATE_MAX_EXACT_THREAD,
    CORRELATION_MAX_FINAL_CANDIDATES,
    SEMANTIC_SUMMARY_METADATA_KEY,
    SEMANTIC_SUMMARY_REVISION_KEY,
)
from app.services.correlation_models import CorrelationCandidate, CorrelationDecision
from app.services.correlation_service import CorrelationService
from app.services.context_service import ContextService
from app.services.deterministic_relation_service import DeterministicRelationService
from app.services.edge_dedup import correlation_signature
from app.services.graph_service import GraphService
from app.services.mail_rfc_id import extract_rfc_message_id
from app.services.pipeline_enqueue import enqueue_correlate_object, enqueue_embed_object
from app.services.representation_service import KIND_CHUNK, KIND_SUMMARY, RepresentationService
from app.services.semantic_summary_service import SemanticSummaryService
from app.users.bootstrap import BOOTSTRAP_USER_ID


class RawCorrelationJudge:
    """Returns adversarial decisions without filtering."""

    def __init__(self, decisions: list[CorrelationDecision]) -> None:
        self._decisions = decisions

    def judge(
        self,
        trigger_title: str,
        trigger_kind: str,
        trigger_summary: str,
        candidates: list[CorrelationCandidate],
    ) -> CorrelationJudgeResult:
        return CorrelationJudgeResult(decisions=tuple(self._decisions))


class RecordingSummarizer:
    def __init__(self, response: str = "summary") -> None:
        self.last_input: str | None = None
        self._response = response

    def summarize(self, text: str) -> str:
        self.last_input = text
        return self._response


class RevisionMutatingSummarizer:
    def __init__(self, session, object_id, user_id) -> None:
        self._session = session
        self._object_id = object_id
        self._user_id = user_id

    def summarize(self, text: str) -> str:
        obj = self._session.scalar(
            select(Object).where(Object.id == self._object_id, Object.user_id == self._user_id)
        )
        if obj is not None:
            metadata = dict(obj.metadata_ or {})
            metadata["content_revision"] = "rev-stale"
            obj.metadata_ = metadata
            self._session.flush()
        return "stale summary"


def _create_email(
    graph: GraphService,
    title: str,
    metadata: dict,
    provider: str = "gmail",
    external_id: str | None = None,
    occurred_at: datetime | None = None,
) -> Object:
    return graph.create_object(
        ObjectCreate(
            kind="email",
            title=title,
            origin="source",
            provider=provider,
            external_id=external_id or str(uuid4()),
            metadata=metadata,
            occurred_at=occurred_at or datetime.now(UTC),
        )
    )


def test_adversarial_judge_invalid_decisions_ignored(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    trigger = graph.create_object(
        ObjectCreate(
            kind="note",
            title="Trigger seminar",
            origin="user",
            metadata={"sender": "user@example.com"},
        )
    )
    allowed = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Task seminar",
            origin="user",
            metadata={"recipients": ["user@example.com"]},
        )
    )
    rejected_target = graph.create_object(
        ObjectCreate(kind="task", title="Rejected", origin="user", state="rejected")
    )
    other_user_obj = graph.create_object(ObjectCreate(kind="task", title="Other", origin="user"))
    invented_id = uuid4()
    decisions = [
        CorrelationDecision(allowed.id, "related_to", 0.95, "ok"),
        CorrelationDecision(invented_id, "related_to", 0.95, "invented"),
        CorrelationDecision(trigger.id, "related_to", 0.95, "self"),
        CorrelationDecision(allowed.id, "depends_on", 0.95, "bad type"),
        CorrelationDecision(allowed.id, "related_to", 0.5, "low"),
        CorrelationDecision(allowed.id, "related_to", float("nan"), "nan"),
        CorrelationDecision(allowed.id, "related_to", float("inf"), "inf"),
        CorrelationDecision(allowed.id, "related_to", -0.1, "neg"),
        CorrelationDecision(allowed.id, "related_to", 1.1, "gt1"),
        CorrelationDecision(rejected_target.id, "related_to", 0.95, "rejected"),
    ]
    judge = RawCorrelationJudge(decisions)
    created = CorrelationService(db_session, BOOTSTRAP_USER_ID, judge).run_correlation(trigger.id)
    assert created == 1
    count = db_session.scalar(
        select(func.count()).select_from(Edge).where(
            Edge.source_id == trigger.id,
            Edge.origin == "agent",
        )
    )
    assert count == 1


def test_final_candidate_cap_all_sources(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    trigger = _create_email(
        graph,
        "Thread anchor",
        {
            "thread_id": "thread-cap",
            "sender": "cap@example.com",
            "headers": {"message-id": "<anchor@example.com>"},
        },
    )
    for index in range(CANDIDATE_MAX_EXACT_THREAD):
        _create_email(
            graph,
            f"Peer {index}",
            {"thread_id": "thread-cap", "sender": f"p{index}@example.com"},
            external_id=f"peer-{index}",
            occurred_at=datetime.now(UTC) - timedelta(minutes=index),
        )
    for index in range(10):
        graph.create_object(
            ObjectCreate(
                kind="note",
                title=f"Participant neighbor ADC {index}",
                origin="user",
                metadata={"recipients": ["cap@example.com"]},
            )
        )
    for index in range(20):
        graph.create_object(
            ObjectCreate(
                kind="note",
                title=f"Semantic ADC document {index}",
                origin="user",
                body=f"ADC semantic content {index}",
            )
        )
    candidates = CorrelationCandidateService(db_session, BOOTSTRAP_USER_ID).collect_candidates(
        trigger.id
    )
    assert len(candidates) <= CORRELATION_MAX_FINAL_CANDIDATES


def test_gmail_rfc_message_id_from_headers(db_session) -> None:
    meta = {
        "message_id": "gmail-api-id-123",
        "headers": {"message-id": "<real-rfc@example.com>"},
    }
    assert extract_rfc_message_id(meta, "gmail") == "real-rfc@example.com"


def test_no_reference_from_own_message_id(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    msg = _create_email(
        graph,
        "Self ref",
        {
            "message_id": "gmail-api-self",
            "headers": {
                "message-id": "<self@example.com>",
                "references": "<self@example.com>",
            },
        },
        external_id="self-ref",
    )
    DeterministicRelationService(db_session, BOOTSTRAP_USER_ID).apply_source_relations(msg.id)
    count = db_session.scalar(select(func.count()).select_from(Edge).where(Edge.source_id == msg.id))
    assert count == 0


def test_gmail_in_reply_to_uses_rfc_header(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    parent = _create_email(
        graph,
        "Parent",
        {
            "message_id": "gmail-parent-api-id",
            "headers": {"message-id": "<parent@example.com>"},
            "thread_id": "t1",
        },
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


def test_same_thread_edges_bounded(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    trigger = _create_email(graph, "Trigger", {"thread_id": "long-thread"}, external_id="trigger")
    for index in range(20):
        _create_email(
            graph,
            f"Peer {index}",
            {"thread_id": "long-thread"},
            external_id=f"long-{index}",
            occurred_at=datetime.now(UTC) - timedelta(minutes=index),
        )
    created = DeterministicRelationService(db_session, BOOTSTRAP_USER_ID).apply_source_relations(
        trigger.id
    )
    assert created <= CANDIDATE_MAX_EXACT_THREAD
    second = DeterministicRelationService(db_session, BOOTSTRAP_USER_ID).apply_source_relations(
        trigger.id
    )
    assert second == 0


def test_participant_email_normalization(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    trigger = _create_email(
        graph,
        "Trigger",
        {"from": "Ivan Petrov <ivan@example.com>"},
        provider="yandex_mail",
    )
    target = graph.create_object(
        ObjectCreate(
            kind="note",
            title="Target",
            origin="user",
            metadata={"to": ["ivan@example.com"]},
        )
    )
    judge = RawCorrelationJudge(
        [CorrelationDecision(target.id, "related_to", 0.9, "shared participant")]
    )
    created = CorrelationService(db_session, BOOTSTRAP_USER_ID, judge).run_correlation(trigger.id)
    assert created == 1


def test_symmetric_rejected_related_to_blocks_reverse(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    a = graph.create_object(ObjectCreate(kind="note", title="A", origin="user"))
    b = graph.create_object(ObjectCreate(kind="task", title="B", origin="user"))
    signature = correlation_signature(a.id, b.id, "related_to")
    graph.create_edge(
        EdgeCreate(
            source_id=a.id,
            target_id=b.id,
            type="related_to",
            origin="agent",
            state="rejected",
            confidence=0.9,
            metadata={"correlation_signature": signature},
        )
    )
    judge = RawCorrelationJudge([CorrelationDecision(a.id, "related_to", 0.9, "reverse")])
    created = CorrelationService(db_session, BOOTSTRAP_USER_ID, judge).run_correlation(b.id)
    assert created == 0


def test_judge_cross_user_target_ignored(db_session) -> None:
    other_user = User(display_name="Other user")
    db_session.add(other_user)
    db_session.flush()
    other_graph = GraphService(db_session, other_user.id)
    cross_user_target = other_graph.create_object(
        ObjectCreate(kind="task", title="Other user task", origin="user")
    )
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    trigger = graph.create_object(
        ObjectCreate(
            kind="note",
            title="Trigger",
            origin="user",
            metadata={"sender": "user@example.com"},
        )
    )
    allowed = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Allowed",
            origin="user",
            metadata={"recipients": ["user@example.com"]},
        )
    )
    judge = RawCorrelationJudge(
        [
            CorrelationDecision(cross_user_target.id, "related_to", 0.95, "cross-user"),
            CorrelationDecision(allowed.id, "related_to", 0.95, "ok"),
        ]
    )
    created = CorrelationService(db_session, BOOTSTRAP_USER_ID, judge).run_correlation(trigger.id)
    assert created == 1
    cross_edge = db_session.scalar(
        select(Edge).where(
            Edge.source_id == trigger.id,
            Edge.target_id == cross_user_target.id,
        )
    )
    assert cross_edge is None


def test_judge_deleted_task_target_ignored(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    trigger = graph.create_object(
        ObjectCreate(
            kind="note",
            title="Trigger",
            origin="user",
            metadata={"sender": "user@example.com"},
        )
    )
    deleted_task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Deleted task",
            origin="user",
            status=TASK_STATUS_DELETED,
        )
    )
    allowed = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Allowed",
            origin="user",
            metadata={"recipients": ["user@example.com"]},
        )
    )
    judge = RawCorrelationJudge(
        [
            CorrelationDecision(deleted_task.id, "related_to", 0.95, "deleted"),
            CorrelationDecision(allowed.id, "related_to", 0.95, "ok"),
        ]
    )
    created = CorrelationService(db_session, BOOTSTRAP_USER_ID, judge).run_correlation(trigger.id)
    assert created == 1
    deleted_edge = db_session.scalar(
        select(Edge).where(
            Edge.source_id == trigger.id,
            Edge.target_id == deleted_task.id,
        )
    )
    assert deleted_edge is None


def test_event_embed_queues_correlate_job(db_session, fake_embedding_service) -> None:
    from unittest.mock import patch

    from app.jobs.handlers import handle_embed_object
    from app.llm.embedding_text import embed_job_payload

    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    event = graph.create_object(
        ObjectCreate(kind="event", title="Meeting", origin="source", provider="google_calendar")
    )
    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.services.representation_embedding_worker.SessionLocal", lambda: db_session
    ), patch.object(db_session, "close", lambda: None):
        handle_embed_object(
            db_session,
            fake_embedding_service,
            embed_job_payload(event),
            BOOTSTRAP_USER_ID,
        )
    correlate_job = db_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_CORRELATE_OBJECT,
            Job.status == "pending",
        )
    )
    assert correlate_job is not None
    payload = correlate_job.payload or {}
    assert payload.get("object_id") == str(event.id)


def test_semantic_summary_discards_stale_revision(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    obj = graph.create_object(
        ObjectCreate(
            kind="document",
            title="Doc",
            origin="user",
            metadata={"content_revision": "rev-1"},
        )
    )
    RepresentationService(db_session, BOOTSTRAP_USER_ID).ingest_text_content(
        obj.id, "word " * 200
    )
    summary = SemanticSummaryService(
        db_session,
        BOOTSTRAP_USER_ID,
        summarizer=RevisionMutatingSummarizer(db_session, obj.id, BOOTSTRAP_USER_ID),
    ).update_summary_for_object(obj.id)
    assert summary is None
    db_session.refresh(obj)
    assert obj.metadata_.get(SEMANTIC_SUMMARY_METADATA_KEY) is None
    rep = db_session.scalar(
        select(Representation).where(
            Representation.object_id == obj.id,
            Representation.kind == KIND_SUMMARY,
        )
    )
    assert rep is None or rep.text != "stale summary"


def test_semantic_summary_uses_bounded_chunks(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    obj = graph.create_object(
        ObjectCreate(
            kind="document",
            title="Long doc",
            origin="user",
            metadata={"content_revision": "rev-chunks"},
        )
    )
    reps = RepresentationService(db_session, BOOTSTRAP_USER_ID)
    long_text = "intro " * 50 + "UNIQUE_TAIL_MARKER " + "tail " * 200
    reps.ingest_text_content(obj.id, long_text)
    chunk_reps = db_session.scalars(
        select(Representation).where(
            Representation.object_id == obj.id,
            Representation.kind == KIND_CHUNK,
        )
    ).all()
    if chunk_reps:
        chunk_reps[-1].text = "UNIQUE_TAIL_MARKER at document end"
        db_session.flush()
    recorder = RecordingSummarizer()
    SemanticSummaryService(
        db_session, BOOTSTRAP_USER_ID, summarizer=recorder
    ).update_summary_for_object(obj.id)
    assert recorder.last_input is not None
    assert "UNIQUE_TAIL_MARKER" in recorder.last_input
    assert len(recorder.last_input) <= 4000


def test_folder_context_scoped_to_contained(db_session, fake_embedding_service) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    folder = graph.create_object(
        ObjectCreate(kind="folder", title="Docs folder", origin="user")
    )
    contained = graph.create_object(
        ObjectCreate(
            kind="document",
            title="Contained ADC secret",
            origin="user",
            body="Contains ADC secret keyword inside folder",
        )
    )
    for index in range(15):
        graph.create_object(
            ObjectCreate(
                kind="note",
                title=f"Global strong ADC {index}",
                origin="user",
                body="ADC ADC ADC global dominance",
            )
        )
    graph.create_edge(
        EdgeCreate(
            source_id=folder.id,
            target_id=contained.id,
            type="contains",
            origin="system",
            state="confirmed",
        )
    )
    result = ContextService(db_session, BOOTSTRAP_USER_ID, fake_embedding_service).build_context(
        object_id=folder.id,
        query="ADC secret",
    )
    global_notes = db_session.scalars(
        select(Object).where(Object.title.like("Global strong ADC%"))
    ).all()
    global_ids = {obj.id for obj in global_notes}
    result_ids = {item.object_id for item in result.items}
    assert contained.id in result_ids
    assert global_ids.isdisjoint(result_ids)
    semantic_match_ids = {
        item.object_id
        for item in result.items
        if item.why_included == "semantic object match"
    }
    assert semantic_match_ids.isdisjoint(global_ids)


def test_pipeline_summarize_embed_correlate_sequence(db_session, fake_embedding_service) -> None:
    from unittest.mock import patch

    from app.jobs.handlers import handle_summarize_resource

    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    obj = graph.create_object(
        ObjectCreate(
            kind="document",
            title="Pipeline",
            origin="user",
            metadata={"content_revision": "rev-pipe"},
        )
    )
    RepresentationService(db_session, BOOTSTRAP_USER_ID).ingest_text_content(obj.id, "content body")
    summarize_before = db_session.scalar(
        select(func.count()).select_from(Job).where(Job.type == JOB_TYPE_SUMMARIZE_RESOURCE)
    )
    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ), patch(
        "app.jobs.handlers.create_openai_summarizer_from_effective",
        lambda effective: RecordingSummarizer("pipeline summary"),
    ):
        handle_summarize_resource(
            db_session,
            fake_embedding_service,
            {"object_id": str(obj.id), "expected_revision": "rev-pipe"},
            BOOTSTRAP_USER_ID,
        )
    db_session.refresh(obj)
    assert obj.metadata_.get(SEMANTIC_SUMMARY_METADATA_KEY) is not None
    embed_jobs = db_session.scalar(
        select(func.count()).select_from(Job).where(
            Job.type == JOB_TYPE_EMBED_OBJECT,
            Job.status == "pending",
        )
    )
    assert summarize_before == 0
    assert embed_jobs >= 1


def test_correlation_failure_does_not_rollback_embedding(db_session, fake_embedding_service) -> None:
    from unittest.mock import patch

    from app.jobs.handlers import handle_embed_object
    from app.llm.embedding_text import embed_job_payload

    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    obj = graph.create_object(ObjectCreate(kind="note", title="Stable", origin="user"))
    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.services.representation_embedding_worker.SessionLocal", lambda: db_session
    ), patch.object(db_session, "close", lambda: None):
        handle_embed_object(
            db_session,
            fake_embedding_service,
            embed_job_payload(obj),
            BOOTSTRAP_USER_ID,
        )

    class FailingJudge:
        def judge(self, *args, **kwargs):
            raise RuntimeError("judge failed")

    try:
        CorrelationService(db_session, BOOTSTRAP_USER_ID, FailingJudge()).run_correlation(obj.id)
    except RuntimeError:
        db_session.rollback()

    db_session.expire_all()
    persisted = db_session.scalar(
        select(Object).where(Object.id == obj.id, Object.user_id == BOOTSTRAP_USER_ID)
    )
    assert persisted is not None
    assert persisted.embedding is not None


def test_duplicate_correlate_enqueue_deduped(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    obj = graph.create_object(ObjectCreate(kind="note", title="Dup", origin="user"))
    enqueue_correlate_object(db_session, obj.id, BOOTSTRAP_USER_ID, obj.kind)
    enqueue_correlate_object(db_session, obj.id, BOOTSTRAP_USER_ID, obj.kind)
    count = db_session.scalar(
        select(func.count()).select_from(Job).where(
            Job.type == JOB_TYPE_CORRELATE_OBJECT,
            Job.status.in_(("pending", "running")),
        )
    )
    assert count == 1
