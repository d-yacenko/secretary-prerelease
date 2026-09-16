"""Workflow Intelligence Pass D — bounded background auto-labeling."""

from __future__ import annotations

import inspect
import math
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.ai_audit.constants import (
    EVENT_MODEL_ROUND,
    EVENT_TRACE_FINISHED,
    EVENT_TRACE_STARTED,
    WORKLOAD_BACKGROUND_AUTO_LABEL,
)
from app.ai_audit.context import ai_trace_session, set_current_job_id
from app.ai_audit.trace_service import AITraceService
from app.api.deps import get_db
from app.api.schemas import ObjectCreate
from app.db.engine import engine
from app.db.models import (
    AITrace,
    AITraceEvent,
    Edge,
    ExternalActionAttempt,
    Job,
    Notification,
    Object,
    PendingActionPlan,
    User,
    UserSettings,
)
from app.domain.labels import EDGE_TYPE_LABELED_WITH
from app.domain.object_visibility import tombstone_object
from app.domain.scheduled_activity import KIND_SCHEDULED_ACTIVITY
from app.jobs.constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_PENDING,
    JOB_TYPE_AUTO_LABEL_OBJECT,
)
from app.jobs.handlers import HANDLERS, handle_auto_label_object, handle_embed_object
from app.llm.auto_label_classifier import FakeAutoLabelClassifier, _raw_assignment_rows
from app.llm.embedding_text import embed_job_payload
from app.main import app
from app.proactive.constants import PROACTIVE_READ_TOOL_NAMES
from app.services.auto_label_constants import (
    ANNOTATION_SOURCE_BACKGROUND_AUTO_LABEL,
    AUTO_LABEL_MAX_ASSIGNMENTS,
    AUTO_LABEL_MAX_CONTENT_CHARS,
    AUTO_LABEL_MAX_PENDING_PER_USER,
    AUTO_LABEL_MAX_TITLE_CHARS,
    AUTO_LABEL_MAX_VOCABULARY,
    AUTO_LABEL_MIN_CONFIDENCE,
    AUTO_LABEL_VERSION,
    METADATA_ANNOTATION_SOURCE,
    METADATA_AUTO_LABEL_VERSION,
)
from app.services.auto_label_models import AutoLabelAssignment, validate_auto_label_assignments
from app.services.auto_label_service import (
    AutoLabelService,
    acquire_auto_label_user_gate,
    bounded_object_input,
    enqueue_auto_label_object,
)
from app.services.graph_service import GraphService
from app.services.job_queue_service import JobQueueService
from app.services.label_service import LabelService
from app.services.provenance import AGENT_ORIGIN, CONFIRMED_STATE, REJECTED_STATE
from app.tools.registry import PROACTIVE_TOOL_DEFINITIONS
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient


class _SessionProxy:
    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._session, name)


@pytest.fixture(autouse=True)
def _share_test_session_for_traces(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ai_audit.context.SessionLocal", lambda: _SessionProxy(db_session)
    )


def _graph(session: Session) -> GraphService:
    return GraphService(session, BOOTSTRAP_USER_ID)


def _labels(session: Session) -> LabelService:
    return LabelService(session, BOOTSTRAP_USER_ID)


def _note(session: Session, title: str = "Note", body: str | None = None) -> Object:
    return _graph(session).create_object(
        ObjectCreate(kind="note", title=title, body=body, origin="user")
    )


def _enable_auto_label(session: Session, enabled: bool = True) -> None:
    row = session.get(UserSettings, BOOTSTRAP_USER_ID)
    if row is None:
        row = UserSettings(user_id=BOOTSTRAP_USER_ID, auto_label_enabled=enabled)
        session.add(row)
    else:
        row.auto_label_enabled = enabled
    session.flush()


class _HookClassifier:
    def __init__(self, assignments: list[AutoLabelAssignment], hook) -> None:
        self._assignments = assignments
        self._hook = hook
        self.calls = 0

    def classify(self, *, obj, candidates, personal=None):
        self.calls += 1
        self._hook()
        return FakeAutoLabelClassifier(assignments=self._assignments).classify(
            obj=obj,
            candidates=candidates,
            personal=personal,
        )


def _active_labeled_edges(session: Session) -> list[Edge]:
    return list(
        session.scalars(
            select(Edge).where(
                Edge.type == EDGE_TYPE_LABELED_WITH,
                Edge.state != REJECTED_STATE,
            )
        )
    )


def _auto_label_jobs(session: Session) -> list[Job]:
    return list(
        session.scalars(
            select(Job).where(
                Job.user_id == BOOTSTRAP_USER_ID,
                Job.type == JOB_TYPE_AUTO_LABEL_OBJECT,
            )
        )
    )


def _embed(session: Session, fake_embedding_service, obj: Object) -> None:
    with patch("app.jobs.handlers.SessionLocal", lambda: session), patch(
        "app.services.representation_embedding_worker.SessionLocal", lambda: session
    ), patch("app.ai_audit.context.SessionLocal", lambda: session), patch.object(
        session, "close", lambda: None
    ):
        handle_embed_object(
            session,
            fake_embedding_service,
            embed_job_payload(obj),
            BOOTSTRAP_USER_ID,
        )


@contextmanager
def _isolated_auto_label_user():
    user_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=user_id, display_name=f"auto-label-{user_id}"))
        session.add(UserSettings(user_id=user_id, auto_label_enabled=True))
        session.commit()
    try:
        yield user_id
    finally:
        with Session(engine) as session:
            session.execute(delete(Edge).where(Edge.user_id == user_id))
            session.execute(delete(AITraceEvent).where(
                AITraceEvent.trace_id.in_(select(AITrace.id).where(AITrace.user_id == user_id))
            ))
            session.execute(delete(AITrace).where(AITrace.user_id == user_id))
            session.execute(delete(Job).where(Job.user_id == user_id))
            session.execute(delete(Object).where(Object.user_id == user_id))
            session.execute(delete(UserSettings).where(UserSettings.user_id == user_id))
            session.execute(delete(User).where(User.id == user_id))
            session.commit()


def _seed_note_and_label(user_id: UUID, *, body: str = "work") -> tuple[UUID, UUID, dict]:
    with Session(engine) as session:
        label = LabelService(session, user_id).create_label("Work").label
        note = GraphService(session, user_id).create_object(
            ObjectCreate(kind="note", title="Note", body=body, origin="user")
        )
        enqueue_auto_label_object(session, note.id, user_id)
        jobs = list(
            session.scalars(
                select(Job).where(
                    Job.user_id == user_id,
                    Job.type == JOB_TYPE_AUTO_LABEL_OBJECT,
                )
            )
        )
        payload = dict(jobs[0].payload)
        session.commit()
        return note.id, label.id, payload


def _count_active_edges(session: Session, user_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Edge)
            .where(
                Edge.user_id == user_id,
                Edge.type == EDGE_TYPE_LABELED_WITH,
                Edge.state != REJECTED_STATE,
            )
        )
        or 0
    )


def _auto_label_jobs_for(session: Session, user_id: UUID) -> list[Job]:
    return list(
        session.scalars(
            select(Job).where(
                Job.user_id == user_id,
                Job.type == JOB_TYPE_AUTO_LABEL_OBJECT,
            )
        )
    )


# --------------------------------------------------------------------------- settings


def test_get_settings_defaults_auto_label_false(db_session, auth_headers) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as raw:
        client = AuthTestClient(raw, auth_headers)
        body = client.get("/me/settings").json()
        assert body["auto_label_enabled"] is False
        assert body["proactive_enabled"] is False
    app.dependency_overrides.clear()


def test_patch_auto_label_true_false_independent_of_proactive(
    db_session, auth_headers, monkeypatch
) -> None:
    def override_get_db():
        yield db_session

    synced: list[UUID] = []
    monkeypatch.setattr(
        "app.services.proactive_scheduler.ProactiveScheduler.sync_user",
        lambda self, user_id: synced.append(user_id),
    )
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as raw:
        client = AuthTestClient(raw, auth_headers)
        enabled = client.patch("/me/settings", json={"auto_label_enabled": True})
        assert enabled.status_code == 200
        body = enabled.json()
        assert body["auto_label_enabled"] is True
        assert body["proactive_enabled"] is False
        assert body["proactive_interval_minutes"] == 60
        disabled = client.patch("/me/settings", json={"auto_label_enabled": False})
        assert disabled.json()["auto_label_enabled"] is False
        assert disabled.json()["proactive_enabled"] is False
    app.dependency_overrides.clear()
    assert synced == []
    row = db_session.get(UserSettings, BOOTSTRAP_USER_ID)
    assert row is not None
    assert row.auto_label_enabled is False
    assert row.proactive_enabled is False


def test_enabling_auto_label_does_not_backfill_jobs(db_session, auth_headers) -> None:
    _note(db_session, "Existing")
    _labels(db_session).create_label("Work")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as raw:
        client = AuthTestClient(raw, auth_headers)
        assert client.patch("/me/settings", json={"auto_label_enabled": True}).status_code == 200
    app.dependency_overrides.clear()
    assert _auto_label_jobs(db_session) == []


def test_disabled_queued_job_is_model_free_noop(db_session) -> None:
    _enable_auto_label(db_session, True)
    note = _note(db_session)
    label = _labels(db_session).create_label("Work").label
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    jobs = _auto_label_jobs(db_session)
    assert len(jobs) == 1
    _enable_auto_label(db_session, False)
    fake = FakeAutoLabelClassifier(
        assignments=[
            AutoLabelAssignment(label_id=label.id, confidence=0.99, rationale="work")
        ]
    )
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(jobs[0].payload)
    assert fake.calls == 0
    edges = db_session.scalars(select(Edge).where(Edge.type == EDGE_TYPE_LABELED_WITH)).all()
    assert edges == []


# --------------------------------------------------------------------------- enqueue


def test_embed_disabled_does_not_enqueue(db_session, fake_embedding_service) -> None:
    _labels(db_session).create_label("Work")
    note = _note(db_session)
    _embed(db_session, fake_embedding_service, note)
    assert _auto_label_jobs(db_session) == []


def test_enabled_zero_labels_no_job(db_session, fake_embedding_service) -> None:
    _enable_auto_label(db_session)
    note = _note(db_session)
    _embed(db_session, fake_embedding_service, note)
    assert _auto_label_jobs(db_session) == []


def test_enabled_with_labels_enqueues_one_job(db_session, fake_embedding_service) -> None:
    _enable_auto_label(db_session)
    _labels(db_session).create_label("Work")
    note = _note(db_session)
    _embed(db_session, fake_embedding_service, note)
    jobs = _auto_label_jobs(db_session)
    assert len(jobs) == 1
    payload = jobs[0].payload
    assert payload["object_id"] == str(note.id)
    assert "classification_signature" in payload
    assert "body" not in payload
    assert "title" not in payload


def test_identical_signature_dedupes_pending_and_done(
    db_session, fake_embedding_service
) -> None:
    _enable_auto_label(db_session)
    _labels(db_session).create_label("Work")
    note = _note(db_session, "Stable")
    _embed(db_session, fake_embedding_service, note)
    _embed(db_session, fake_embedding_service, note)
    jobs = _auto_label_jobs(db_session)
    assert len(jobs) == 1
    jobs[0].status = JOB_STATUS_DONE
    db_session.flush()
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    assert len(_auto_label_jobs(db_session)) == 1


def test_semantic_change_enqueues_new_signature(db_session) -> None:
    _enable_auto_label(db_session)
    _labels(db_session).create_label("Work")
    note = _note(db_session, "First", body="alpha")
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    first = _auto_label_jobs(db_session)
    assert len(first) == 1
    note.body = "beta"
    db_session.flush()
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    jobs = _auto_label_jobs(db_session)
    assert len(jobs) == 2
    assert len({job.payload["classification_signature"] for job in jobs}) == 2


def test_queue_cap_skips_without_failing_embed(db_session, fake_embedding_service) -> None:
    _enable_auto_label(db_session)
    _labels(db_session).create_label("Work")
    for index in range(AUTO_LABEL_MAX_PENDING_PER_USER):
        JobQueueService(db_session).enqueue(
            JOB_TYPE_AUTO_LABEL_OBJECT,
            {
                "object_id": str(uuid.uuid4()),
                "classification_signature": f"cap-{index}",
            },
            user_id=BOOTSTRAP_USER_ID,
        )
    note = _note(db_session, "Burst")
    _embed(db_session, fake_embedding_service, note)
    pending = db_session.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.user_id == BOOTSTRAP_USER_ID,
            Job.type == JOB_TYPE_AUTO_LABEL_OBJECT,
            Job.status == JOB_STATUS_PENDING,
        )
    )
    assert int(pending or 0) == AUTO_LABEL_MAX_PENDING_PER_USER
    db_session.refresh(note)
    assert note.id is not None


def test_label_object_never_auto_labeled(db_session, fake_embedding_service) -> None:
    _enable_auto_label(db_session)
    label = _labels(db_session).create_label("Work").label
    _embed(db_session, fake_embedding_service, label)
    assert _auto_label_jobs(db_session) == []


def test_scheduled_activity_and_attachment_and_agent_origin_excluded(
    db_session, fake_embedding_service
) -> None:
    _enable_auto_label(db_session)
    _labels(db_session).create_label("Work")
    activity = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind=KIND_SCHEDULED_ACTIVITY,
        title="Ping",
        origin="user",
        state="confirmed",
    )
    attachment = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        title="ics",
        origin="source",
        state="confirmed",
        metadata_={"parent_email_id": str(uuid.uuid4())},
    )
    agent_obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="note",
        title="agent note",
        origin="agent",
        state="confirmed",
    )
    db_session.add_all([activity, attachment, agent_obj])
    db_session.flush()
    for obj in (activity, attachment, agent_obj):
        enqueue_auto_label_object(db_session, obj.id, BOOTSTRAP_USER_ID)
    assert _auto_label_jobs(db_session) == []


# --------------------------------------------------------------------------- classifier bounds


def test_validate_assignments_fail_closed_and_bounds() -> None:
    owned = uuid.uuid4()
    foreign = uuid.uuid4()
    deleted = uuid.uuid4()
    allowed = {owned}
    raw = [
        {"label_id": str(uuid.uuid4()), "confidence": 0.99, "rationale": "invented"},
        {"label_id": str(foreign), "confidence": 0.99, "rationale": "foreign"},
        {"label_id": str(deleted), "confidence": 0.99, "rationale": "deleted"},
        {"label_id": str(owned), "confidence": float("nan"), "rationale": "nan"},
        {"label_id": str(owned), "confidence": math.inf, "rationale": "inf"},
        {"label_id": str(owned), "confidence": 1.2, "rationale": "range"},
        {"label_id": str(owned), "confidence": 0.84, "rationale": "low"},
        {"label_id": str(owned), "confidence": 0.90, "rationale": "dup-low"},
        {"label_id": str(owned), "confidence": 0.95, "rationale": "dup-high"},
    ]
    accepted = validate_auto_label_assignments(raw, allowed)
    assert len(accepted) == 1
    assert accepted[0].label_id == owned
    assert accepted[0].confidence == 0.95
    extras = [
        {"label_id": str(uuid.uuid4()), "confidence": 0.99, "rationale": "x"}
        for _ in range(8)
    ]
    many_allowed = {UUID(row["label_id"]) for row in extras}
    extras.append({"label_id": str(owned), "confidence": 0.99, "rationale": "owned"})
    many_allowed.add(owned)
    accepted_many = validate_auto_label_assignments(extras, many_allowed)
    assert len(accepted_many) == AUTO_LABEL_MAX_ASSIGNMENTS
    assert validate_auto_label_assignments([], allowed) == ()
    assert _raw_assignment_rows("not-json") == []
    assert AUTO_LABEL_MIN_CONFIDENCE == 0.85


def test_bounded_object_input_prefers_summary_and_truncates(db_session) -> None:
    huge = "x" * (AUTO_LABEL_MAX_CONTENT_CHARS + 50)
    note = _graph(db_session).create_object(
        ObjectCreate(
            kind="note",
            title="T" * (AUTO_LABEL_MAX_TITLE_CHARS + 20),
            body=huge,
            origin="user",
            metadata={"secret": "nope", "semantic_summary": "summary-only"},
        )
    )
    payload = bounded_object_input(note)
    assert payload.content == "summary-only"
    assert payload.content_source == "semantic_summary"
    assert len(payload.title) == AUTO_LABEL_MAX_TITLE_CHARS
    note.metadata_ = {"secret": "nope"}
    db_session.flush()
    body_payload = bounded_object_input(note)
    assert body_payload.content_source == "body"
    assert len(body_payload.content) == AUTO_LABEL_MAX_CONTENT_CHARS
    assert "secret" not in body_payload.content


def test_classifier_receives_only_owned_active_candidates(db_session) -> None:
    _enable_auto_label(db_session)
    owned = _labels(db_session).create_label("Owned").label
    other = uuid.uuid4()
    db_session.add(User(id=other, display_name="other"))
    db_session.flush()
    LabelService(db_session, other).create_label("Foreign")
    tombstoned = _labels(db_session).create_label("Tombstone").label
    LabelService(db_session, BOOTSTRAP_USER_ID).delete_label(tombstoned.id)
    note = _note(db_session, body="hello")
    fake = FakeAutoLabelClassifier(
        assignments=[
            AutoLabelAssignment(label_id=owned.id, confidence=0.99, rationale="ok")
        ]
    )
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    job = _auto_label_jobs(db_session)[0]
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(job.payload)
    assert fake.calls == 1
    assert fake.last_obj is not None
    assert fake.last_obj.content == "hello"
    assert all(item.label_id == owned.id for item in fake.last_candidates or [])
    assert tombstoned.id not in {item.label_id for item in fake.last_candidates or []}


def test_vocabulary_over_bound_skips(db_session) -> None:
    _enable_auto_label(db_session)
    for index in range(AUTO_LABEL_MAX_VOCABULARY + 1):
        _labels(db_session).create_label(f"L{index}")
    note = _note(db_session)
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    assert _auto_label_jobs(db_session) == []


# --------------------------------------------------------------------------- assignment / provenance


def test_background_edge_provenance_and_no_object_touch(db_session) -> None:
    _enable_auto_label(db_session)
    label = _labels(db_session).create_label("Work").label
    note = _note(db_session, "Invoice", body="work item")
    note.provider = "gmail"
    note.external_id = "msg-1"
    db_session.flush()
    updated_before = note.updated_at
    fake = FakeAutoLabelClassifier(
        assignments=[
            AutoLabelAssignment(label_id=label.id, confidence=0.91, rationale="work mail")
        ]
    )
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(
        _auto_label_jobs(db_session)[0].payload
    )
    edge = db_session.scalar(select(Edge).where(Edge.type == EDGE_TYPE_LABELED_WITH))
    assert edge is not None
    assert edge.state == CONFIRMED_STATE
    assert edge.origin == AGENT_ORIGIN
    assert edge.confidence == 0.91
    assert edge.metadata_[METADATA_ANNOTATION_SOURCE] == ANNOTATION_SOURCE_BACKGROUND_AUTO_LABEL
    assert edge.metadata_[METADATA_AUTO_LABEL_VERSION] == AUTO_LABEL_VERSION
    db_session.refresh(note)
    assert note.updated_at == updated_before
    assert note.provider == "gmail"
    assert note.external_id == "msg-1"
    second = AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(
        _auto_label_jobs(db_session)[0].payload
    )
    assert second.already_present == 1
    assert (
        db_session.scalar(
            select(func.count()).select_from(Edge).where(Edge.type == EDGE_TYPE_LABELED_WITH)
        )
        == 1
    )


def test_rejected_history_suppresses_background_but_interactive_readd_works(
    db_session,
) -> None:
    _enable_auto_label(db_session)
    label = _labels(db_session).create_label("Work").label
    note = _note(db_session, body="work")
    fake = FakeAutoLabelClassifier(
        assignments=[
            AutoLabelAssignment(label_id=label.id, confidence=0.99, rationale="again")
        ]
    )
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(
        _auto_label_jobs(db_session)[0].payload
    )
    _labels(db_session).remove_label(note.id, label.id)
    rejected = db_session.scalar(select(Edge).where(Edge.state == REJECTED_STATE))
    assert rejected is not None
    outcome = AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(
        _auto_label_jobs(db_session)[0].payload
    )
    assert outcome.suppressed_rejected == 1
    active = db_session.scalars(
        select(Edge).where(Edge.type == EDGE_TYPE_LABELED_WITH, Edge.state != REJECTED_STATE)
    ).all()
    assert active == []
    readded = _labels(db_session).assign_label(note.id, label.id)
    assert readded.created is True
    assert readded.edge.state == CONFIRMED_STATE


def test_add_only_keeps_previous_assignment(db_session) -> None:
    _enable_auto_label(db_session)
    label_a = _labels(db_session).create_label("A").label
    label_b = _labels(db_session).create_label("B").label
    note = _note(db_session, body="first")
    first = FakeAutoLabelClassifier(
        assignments=[
            AutoLabelAssignment(label_id=label_a.id, confidence=0.9, rationale="a"),
            AutoLabelAssignment(label_id=label_b.id, confidence=0.9, rationale="b"),
        ]
    )
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=first).run_job(
        _auto_label_jobs(db_session)[0].payload
    )
    note.body = "second"
    db_session.flush()
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    jobs = _auto_label_jobs(db_session)
    second_job = next(
        job for job in jobs if job.payload["classification_signature"] != jobs[0].payload["classification_signature"]
    ) if jobs[0].payload["classification_signature"] != jobs[1].payload["classification_signature"] else jobs[1]
    second = FakeAutoLabelClassifier(
        assignments=[
            AutoLabelAssignment(label_id=label_b.id, confidence=0.9, rationale="b-only")
        ]
    )
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=second).run_job(second_job.payload)
    active_ids = {
        edge.target_id
        for edge in db_session.scalars(
            select(Edge).where(Edge.type == EDGE_TYPE_LABELED_WITH, Edge.state != REJECTED_STATE)
        )
    }
    assert active_ids == {label_a.id, label_b.id}


def test_stale_signature_enqueues_current_without_model(db_session) -> None:
    _enable_auto_label(db_session)
    _labels(db_session).create_label("Work")
    note = _note(db_session, "S1", body="one")
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    stale = _auto_label_jobs(db_session)[0]
    note.body = "two"
    db_session.flush()
    fake = FakeAutoLabelClassifier()
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(stale.payload)
    assert fake.calls == 0
    jobs = _auto_label_jobs(db_session)
    assert len(jobs) == 2
    current_sigs = {job.payload["classification_signature"] for job in jobs}
    assert len(current_sigs) == 2
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(stale.payload)
    assert len(_auto_label_jobs(db_session)) == 2


def test_disable_during_classifier_discards_model_output(db_session) -> None:
    _enable_auto_label(db_session)
    label = _labels(db_session).create_label("Work").label
    note = _note(db_session, body="work")
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    fake = _HookClassifier(
        [AutoLabelAssignment(label_id=label.id, confidence=0.99, rationale="work")],
        hook=lambda: _enable_auto_label(db_session, False),
    )
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(
        _auto_label_jobs(db_session)[0].payload
    )
    assert fake.calls == 1
    assert _active_labeled_edges(db_session) == []


def test_object_semantic_change_during_classifier_enqueues_current(db_session) -> None:
    _enable_auto_label(db_session)
    label = _labels(db_session).create_label("Work").label
    note = _note(db_session, body="one")
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    stale = _auto_label_jobs(db_session)[0]

    def mutate() -> None:
        note.body = "two"
        db_session.flush()

    fake = _HookClassifier(
        [AutoLabelAssignment(label_id=label.id, confidence=0.99, rationale="stale")],
        hook=mutate,
    )
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(stale.payload)
    assert fake.calls == 1
    assert _active_labeled_edges(db_session) == []
    jobs = _auto_label_jobs(db_session)
    assert len(jobs) == 2
    assert len({job.payload["classification_signature"] for job in jobs}) == 2
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(stale.payload)
    assert len(_auto_label_jobs(db_session)) == 2


def test_object_tombstone_during_classifier_discards(db_session) -> None:
    _enable_auto_label(db_session)
    label = _labels(db_session).create_label("Work").label
    note = _note(db_session, body="work")
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)

    def mutate() -> None:
        tombstone_object(note)
        db_session.flush()

    fake = _HookClassifier(
        [AutoLabelAssignment(label_id=label.id, confidence=0.99, rationale="gone")],
        hook=mutate,
    )
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(
        _auto_label_jobs(db_session)[0].payload
    )
    assert fake.calls == 1
    assert _active_labeled_edges(db_session) == []
    assert len(_auto_label_jobs(db_session)) == 1


def test_object_reject_during_classifier_discards(db_session) -> None:
    _enable_auto_label(db_session)
    label = _labels(db_session).create_label("Work").label
    note = _note(db_session, body="work")
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)

    def mutate() -> None:
        note.state = REJECTED_STATE
        db_session.flush()

    fake = _HookClassifier(
        [AutoLabelAssignment(label_id=label.id, confidence=0.99, rationale="rejected")],
        hook=mutate,
    )
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(
        _auto_label_jobs(db_session)[0].payload
    )
    assert fake.calls == 1
    assert _active_labeled_edges(db_session) == []


def test_vocabulary_mutate_during_classifier_discards_obsolete(db_session) -> None:
    _enable_auto_label(db_session)
    label_a = _labels(db_session).create_label("A").label
    label_b = _labels(db_session).create_label("B").label
    note = _note(db_session, body="work")
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    first_sig = _auto_label_jobs(db_session)[0].payload["classification_signature"]

    def mutate() -> None:
        _labels(db_session).rename_label(label_a.id, "A-renamed")
        _labels(db_session).create_label("C")
        _labels(db_session).delete_label(label_b.id)

    fake = _HookClassifier(
        [AutoLabelAssignment(label_id=label_a.id, confidence=0.99, rationale="obsolete")],
        hook=mutate,
    )
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(
        _auto_label_jobs(db_session)[0].payload
    )
    assert fake.calls == 1
    assert _active_labeled_edges(db_session) == []
    jobs = _auto_label_jobs(db_session)
    current_sigs = {job.payload["classification_signature"] for job in jobs}
    assert first_sig in current_sigs
    assert len(current_sigs) == 2


def test_classifier_has_no_identity_input() -> None:
    parameters = inspect.signature(FakeAutoLabelClassifier.classify).parameters
    assert "identity_facts" not in parameters
    source = inspect.getsource(FakeAutoLabelClassifier.classify)
    assert "identity" not in source


def test_loaded_vocabulary_over_bound_skips_model_on_existing_job(db_session) -> None:
    _enable_auto_label(db_session)
    for index in range(AUTO_LABEL_MAX_VOCABULARY):
        _labels(db_session).create_label(f"L{index}")
    note = _note(db_session, body="work")
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    assert len(_auto_label_jobs(db_session)) == 1
    _labels(db_session).create_label("overflow")
    fake = FakeAutoLabelClassifier()
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(
        _auto_label_jobs(db_session)[0].payload
    )
    assert fake.calls == 0
    assert _active_labeled_edges(db_session) == []


def test_signature_dedupe_with_many_unrelated_done_jobs(db_session) -> None:
    _enable_auto_label(db_session)
    _labels(db_session).create_label("Work")
    note = _note(db_session, body="stable")
    for index in range(40):
        JobQueueService(db_session).enqueue(
            JOB_TYPE_AUTO_LABEL_OBJECT,
            {
                "object_id": str(uuid.uuid4()),
                "classification_signature": f"unrelated-{index}",
            },
            user_id=BOOTSTRAP_USER_ID,
        )
    for job in _auto_label_jobs(db_session):
        job.status = JOB_STATUS_DONE
    db_session.flush()
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    matching = [
        job
        for job in _auto_label_jobs(db_session)
        if job.payload.get("object_id") == str(note.id)
    ]
    assert len(matching) == 1


def test_post_fence_source_edit_commits_before_authority() -> None:
    with _isolated_auto_label_user() as user_id:
        note_id, label_id, payload = _seed_note_and_label(user_id)

        def after_classify() -> None:
            with Session(engine) as other:
                note = other.get(Object, note_id)
                assert note is not None
                note.body = "changed-after-model"
                other.commit()

        fake = FakeAutoLabelClassifier(
            assignments=[
                AutoLabelAssignment(label_id=label_id, confidence=0.99, rationale="stale")
            ]
        )
        with patch(
            "app.services.auto_label_service.ai_trace_session",
            lambda *args, **kwargs: nullcontext(),
        ), Session(engine) as worker:
            AutoLabelService(
                worker,
                user_id,
                classifier=fake,
                after_classify=after_classify,
            ).run_job(payload)
            worker.commit()
        with Session(engine) as session:
            assert _count_active_edges(session, user_id) == 0
            jobs = _auto_label_jobs_for(session, user_id)
            assert len({job.payload["classification_signature"] for job in jobs}) == 2


def test_post_fence_tombstone_commits_before_authority() -> None:
    with _isolated_auto_label_user() as user_id:
        note_id, label_id, payload = _seed_note_and_label(user_id)

        def after_classify() -> None:
            with Session(engine) as other:
                note = other.get(Object, note_id)
                assert note is not None
                tombstone_object(note)
                other.commit()

        fake = FakeAutoLabelClassifier(
            assignments=[
                AutoLabelAssignment(label_id=label_id, confidence=0.99, rationale="gone")
            ]
        )
        with patch(
            "app.services.auto_label_service.ai_trace_session",
            lambda *args, **kwargs: nullcontext(),
        ), Session(engine) as worker:
            AutoLabelService(
                worker, user_id, classifier=fake, after_classify=after_classify
            ).run_job(payload)
            worker.commit()
        with Session(engine) as session:
            assert _count_active_edges(session, user_id) == 0


def test_post_fence_reject_commits_before_authority() -> None:
    with _isolated_auto_label_user() as user_id:
        note_id, label_id, payload = _seed_note_and_label(user_id)

        def after_classify() -> None:
            with Session(engine) as other:
                note = other.get(Object, note_id)
                assert note is not None
                note.state = REJECTED_STATE
                other.commit()

        fake = FakeAutoLabelClassifier(
            assignments=[
                AutoLabelAssignment(label_id=label_id, confidence=0.99, rationale="rej")
            ]
        )
        with patch(
            "app.services.auto_label_service.ai_trace_session",
            lambda *args, **kwargs: nullcontext(),
        ), Session(engine) as worker:
            AutoLabelService(
                worker, user_id, classifier=fake, after_classify=after_classify
            ).run_job(payload)
            worker.commit()
        with Session(engine) as session:
            assert _count_active_edges(session, user_id) == 0


def test_post_fence_vocabulary_commits_before_authority() -> None:
    with _isolated_auto_label_user() as user_id:
        _note_id, label_id, payload = _seed_note_and_label(user_id)

        def after_classify() -> None:
            with Session(engine) as other:
                LabelService(other, user_id).rename_label(label_id, "Renamed")
                LabelService(other, user_id).create_label("Extra")
                other.commit()

        fake = FakeAutoLabelClassifier(
            assignments=[
                AutoLabelAssignment(label_id=label_id, confidence=0.99, rationale="old")
            ]
        )
        with patch(
            "app.services.auto_label_service.ai_trace_session",
            lambda *args, **kwargs: nullcontext(),
        ), Session(engine) as worker:
            AutoLabelService(
                worker, user_id, classifier=fake, after_classify=after_classify
            ).run_job(payload)
            worker.commit()
        with Session(engine) as session:
            assert _count_active_edges(session, user_id) == 0
            assert len({job.payload["classification_signature"] for job in _auto_label_jobs_for(session, user_id)}) == 2


def test_post_fence_disable_commits_before_authority() -> None:
    with _isolated_auto_label_user() as user_id:
        _note_id, label_id, payload = _seed_note_and_label(user_id)

        def after_classify() -> None:
            with Session(engine) as other:
                settings = other.get(UserSettings, user_id)
                assert settings is not None
                settings.auto_label_enabled = False
                other.commit()

        fake = FakeAutoLabelClassifier(
            assignments=[
                AutoLabelAssignment(label_id=label_id, confidence=0.99, rationale="late")
            ]
        )
        with patch(
            "app.services.auto_label_service.ai_trace_session",
            lambda *args, **kwargs: nullcontext(),
        ), Session(engine) as worker:
            AutoLabelService(
                worker, user_id, classifier=fake, after_classify=after_classify
            ).run_job(payload)
            worker.commit()
        with Session(engine) as session:
            assert _count_active_edges(session, user_id) == 0


def test_post_authority_serializes_taxonomy_mutation_behind_worker() -> None:
    with _isolated_auto_label_user() as user_id:
        _note_id, label_id, payload = _seed_note_and_label(user_id)
        renamed = threading.Event()
        started = threading.Event()
        errors: list[BaseException] = []
        racer_thread: list[threading.Thread] = []

        def racer() -> None:
            try:
                started.set()
                with Session(engine) as other:
                    LabelService(other, user_id).rename_label(label_id, "Office")
                    other.commit()
                renamed.set()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def after_authority() -> None:
            thread = threading.Thread(target=racer)
            racer_thread.append(thread)
            thread.start()
            assert started.wait(timeout=5)
            time.sleep(0.2)
            assert not renamed.is_set()

        fake = FakeAutoLabelClassifier(
            assignments=[
                AutoLabelAssignment(label_id=label_id, confidence=0.99, rationale="locked")
            ]
        )
        with patch(
            "app.services.auto_label_service.ai_trace_session",
            lambda *args, **kwargs: nullcontext(),
        ), Session(engine) as worker:
            AutoLabelService(
                worker, user_id, classifier=fake, after_authority=after_authority
            ).run_job(payload)
            assert not renamed.is_set()
            worker.commit()
        assert racer_thread
        racer_thread[0].join(timeout=15)
        assert renamed.is_set()
        assert errors == []
        with Session(engine) as session:
            assert _count_active_edges(session, user_id) == 1
            label = session.get(Object, label_id)
            assert label is not None
            assert label.title == "Office"


def test_concurrent_identical_enqueue_creates_one_job() -> None:
    with _isolated_auto_label_user() as user_id:
        with Session(engine) as session:
            LabelService(session, user_id).create_label("Work")
            note = GraphService(session, user_id).create_object(
                ObjectCreate(kind="note", title="Note", body="stable", origin="user")
            )
            note_id = note.id
            session.commit()
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                with Session(engine) as session:
                    barrier.wait(timeout=10)
                    enqueue_auto_label_object(session, note_id, user_id)
                    session.commit()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        assert errors == []
        with Session(engine) as session:
            jobs = [
                job
                for job in _auto_label_jobs_for(session, user_id)
                if job.payload.get("object_id") == str(note_id)
            ]
            assert len(jobs) == 1


def test_stale_requeue_races_ordinary_enqueue_one_current_job() -> None:
    with _isolated_auto_label_user() as user_id:
        note_id, _label_id, stale_payload = _seed_note_and_label(user_id, body="one")
        with Session(engine) as session:
            note = session.get(Object, note_id)
            assert note is not None
            note.body = "two"
            session.commit()
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def stale_worker() -> None:
            try:
                with Session(engine) as session:
                    barrier.wait(timeout=10)
                    AutoLabelService(session, user_id, classifier=FakeAutoLabelClassifier()).run_job(
                        stale_payload
                    )
                    session.commit()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def enqueue_worker() -> None:
            try:
                with Session(engine) as session:
                    barrier.wait(timeout=10)
                    enqueue_auto_label_object(session, note_id, user_id)
                    session.commit()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        with patch(
            "app.services.auto_label_service.ai_trace_session",
            lambda *args, **kwargs: nullcontext(),
        ):
            threads = [
                threading.Thread(target=stale_worker),
                threading.Thread(target=enqueue_worker),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
        assert errors == []
        with Session(engine) as session:
            current_jobs = [
                job
                for job in _auto_label_jobs_for(session, user_id)
                if job.payload.get("classification_signature") != stale_payload["classification_signature"]
            ]
            assert len(current_jobs) == 1


def test_queue_cap_holds_under_concurrent_enqueue() -> None:
    with _isolated_auto_label_user() as user_id:
        with Session(engine) as session:
            LabelService(session, user_id).create_label("Work")
            for index in range(AUTO_LABEL_MAX_PENDING_PER_USER - 1):
                JobQueueService(session).enqueue(
                    JOB_TYPE_AUTO_LABEL_OBJECT,
                    {
                        "object_id": str(uuid.uuid4()),
                        "classification_signature": f"cap-{index}",
                    },
                    user_id=user_id,
                )
            notes = [
                GraphService(session, user_id).create_object(
                    ObjectCreate(kind="note", title=f"N{index}", body="x", origin="user")
                )
                for index in range(2)
            ]
            note_ids = [note.id for note in notes]
            session.commit()
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def worker(object_id: UUID) -> None:
            try:
                with Session(engine) as session:
                    barrier.wait(timeout=10)
                    enqueue_auto_label_object(session, object_id, user_id)
                    session.commit()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(note_id,)) for note_id in note_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        assert errors == []
        with Session(engine) as session:
            pending = session.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.user_id == user_id,
                    Job.type == JOB_TYPE_AUTO_LABEL_OBJECT,
                    Job.status == JOB_STATUS_PENDING,
                )
            )
            assert int(pending or 0) == AUTO_LABEL_MAX_PENDING_PER_USER


def test_audit_workload_and_parent_trace(db_session, monkeypatch) -> None:
    class _Proxy:
        def __init__(self, session: Session) -> None:
            self._session = session

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    monkeypatch.setattr("app.ai_audit.context.SessionLocal", lambda: _Proxy(db_session))
    _enable_auto_label(db_session)
    label = _labels(db_session).create_label("Work").label
    note = _note(db_session, body="work")
    fake = FakeAutoLabelClassifier(
        assignments=[
            AutoLabelAssignment(label_id=label.id, confidence=0.99, rationale="work")
        ]
    )
    parent_id: UUID | None = None
    with ai_trace_session(
        BOOTSTRAP_USER_ID, "embedding", object_id=note.id, session=db_session, commit_on_exit=False
    ) as parent:
        parent_id = parent.trace_id
        enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    job = _auto_label_jobs(db_session)[0]
    assert job.payload.get("parent_trace_id") == str(parent_id)
    token = set_current_job_id(job.id)
    try:
        AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(job.payload)
    finally:
        from app.ai_audit.context import reset_current_job_id

        reset_current_job_id(token)
    traces = list(
        db_session.scalars(
            select(AITrace).where(AITrace.workload == WORKLOAD_BACKGROUND_AUTO_LABEL)
        )
    )
    assert len(traces) == 1
    trace = traces[0]
    assert trace.object_id == note.id
    assert trace.job_id == job.id
    assert trace.parent_trace_id == parent_id
    events = list(
        db_session.scalars(select(AITraceEvent).where(AITraceEvent.trace_id == trace.id))
    )
    assert any(event.event_type == EVENT_MODEL_ROUND for event in events)


def test_side_effects_zero(db_session) -> None:
    pap_before = db_session.scalar(select(func.count()).select_from(PendingActionPlan)) or 0
    eaa_before = db_session.scalar(select(func.count()).select_from(ExternalActionAttempt)) or 0
    tasks_before = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.kind == "task")
    ) or 0
    notes_before = db_session.scalar(select(func.count()).select_from(Notification)) or 0
    _enable_auto_label(db_session)
    label = _labels(db_session).create_label("Work").label
    note = _note(db_session, body="work")
    fake = FakeAutoLabelClassifier(
        assignments=[
            AutoLabelAssignment(label_id=label.id, confidence=0.99, rationale="work")
        ]
    )
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    AutoLabelService(db_session, BOOTSTRAP_USER_ID, classifier=fake).run_job(
        _auto_label_jobs(db_session)[0].payload
    )
    assert (db_session.scalar(select(func.count()).select_from(PendingActionPlan)) or 0) == pap_before
    assert (
        db_session.scalar(select(func.count()).select_from(ExternalActionAttempt)) or 0
    ) == eaa_before
    assert (
        db_session.scalar(select(func.count()).select_from(Object).where(Object.kind == "task"))
        or 0
    ) == tasks_before
    assert (db_session.scalar(select(func.count()).select_from(Notification)) or 0) == notes_before
    settings = db_session.get(UserSettings, BOOTSTRAP_USER_ID)
    assert settings is not None
    assert settings.proactive_enabled is False


def test_proactive_allowlist_unchanged() -> None:
    assert PROACTIVE_READ_TOOL_NAMES == (
        "retrieve",
        "query_objects",
        "get_object",
        "get_context",
        "list_neighbors",
        "list_notifications",
    )
    names = {item["name"] for item in PROACTIVE_TOOL_DEFINITIONS}
    assert tuple(item["name"] for item in PROACTIVE_TOOL_DEFINITIONS) == PROACTIVE_READ_TOOL_NAMES
    assert names == set(PROACTIVE_READ_TOOL_NAMES)
    assert "assign_label" not in names
    assert "list_labels" not in names


def test_handler_registered() -> None:
    assert JOB_TYPE_AUTO_LABEL_OBJECT in HANDLERS
    assert HANDLERS[JOB_TYPE_AUTO_LABEL_OBJECT] is handle_auto_label_object


def test_no_taxonomy_prefixes_in_auto_label_modules() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    forbidden = ("Сфера ·", "Проект ·", "Роль ·", "Внимание ·", "Работа ·")
    for path in (
        root / "services" / "auto_label_service.py",
        root / "llm" / "auto_label_classifier.py",
        root / "services" / "auto_label_constants.py",
    ):
        text = path.read_text(encoding="utf-8")
        for prefix in forbidden:
            assert prefix not in text


def _use_real_audit_sessions(monkeypatch) -> None:
    from app.db.session import SessionLocal as RealSessionLocal

    monkeypatch.setattr("app.ai_audit.context.SessionLocal", RealSessionLocal)


def test_user_serialization_lock_compiles_to_no_key_update() -> None:
    user_sql = str(
        select(User)
        .where(User.id == BOOTSTRAP_USER_ID)
        .with_for_update(key_share=True)
        .compile(dialect=postgresql.dialect())
    )
    settings_sql = str(
        select(UserSettings)
        .where(UserSettings.user_id == BOOTSTRAP_USER_ID)
        .with_for_update()
        .compile(dialect=postgresql.dialect())
    )
    assert "FOR NO KEY UPDATE" in user_sql
    assert "FOR NO KEY UPDATE" not in settings_sql
    assert "FOR UPDATE" in settings_sql


def test_real_ai_audit_session_completes_with_user_gate(monkeypatch) -> None:
    _use_real_audit_sessions(monkeypatch)
    with _isolated_auto_label_user() as user_id:
        note_id, label_id, payload = _seed_note_and_label(user_id)
        with Session(engine) as session:
            job_id = _auto_label_jobs_for(session, user_id)[0].id
        fake = FakeAutoLabelClassifier(
            assignments=[
                AutoLabelAssignment(label_id=label_id, confidence=0.99, rationale="match")
            ]
        )
        errors: list[BaseException] = []

        def worker_run() -> None:
            try:
                token = set_current_job_id(job_id)
                try:
                    with Session(engine) as worker:
                        worker.execute(text("SET LOCAL lock_timeout = '3s'"))
                        worker.execute(text("SET LOCAL statement_timeout = '8s'"))
                        with patch(
                            "app.services.auto_label_service.create_auto_label_classifier_from_effective",
                            lambda *_args, **_kwargs: fake,
                        ):
                            handle_auto_label_object(worker, None, payload, user_id)
                        worker.commit()
                finally:
                    from app.ai_audit.context import reset_current_job_id

                    reset_current_job_id(token)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=worker_run)
        thread.start()
        thread.join(timeout=12)
        assert not thread.is_alive()
        assert errors == []
        with Session(engine) as session:
            assert _count_active_edges(session, user_id) == 1
            edge = session.scalar(
                select(Edge).where(
                    Edge.user_id == user_id,
                    Edge.type == EDGE_TYPE_LABELED_WITH,
                    Edge.state != REJECTED_STATE,
                )
            )
            assert edge is not None
            assert edge.source_id == note_id
            assert edge.target_id == label_id
            traces = list(
                session.scalars(
                    select(AITrace).where(
                        AITrace.user_id == user_id,
                        AITrace.workload == WORKLOAD_BACKGROUND_AUTO_LABEL,
                    )
                )
            )
            assert len(traces) == 1
            trace = traces[0]
            assert trace.finished_at is not None
            assert trace.success is True
            assert trace.job_id == job_id
            events = {
                item.event_type
                for item in session.scalars(
                    select(AITraceEvent).where(AITraceEvent.trace_id == trace.id)
                )
            }
            assert EVENT_TRACE_STARTED in events
            assert EVENT_MODEL_ROUND in events
            assert "auto_label_result" in events
            assert EVENT_TRACE_FINISHED in events


def test_user_gate_allows_audit_fk_and_serializes_second_gate(monkeypatch) -> None:
    _use_real_audit_sessions(monkeypatch)
    with _isolated_auto_label_user() as user_id:
        gate_held = threading.Event()
        release_gate = threading.Event()
        audit_committed = threading.Event()
        second_acquired = threading.Event()
        errors: list[BaseException] = []

        def holder() -> None:
            try:
                with Session(engine) as session:
                    session.execute(text("SET LOCAL lock_timeout = '8s'"))
                    acquire_auto_label_user_gate(session, user_id)
                    gate_held.set()
                    assert release_gate.wait(timeout=10)
                    session.commit()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def auditor() -> None:
            try:
                assert gate_held.wait(timeout=5)
                with Session(engine) as audit:
                    audit.execute(text("SET LOCAL lock_timeout = '3s'"))
                    audit.execute(text("SET LOCAL statement_timeout = '5s'"))
                    service = AITraceService(audit)
                    trace = service.start_trace(
                        user_id=user_id,
                        workload=WORKLOAD_BACKGROUND_AUTO_LABEL,
                    )
                    service.record_event(
                        trace_id=trace.id,
                        user_id=user_id,
                        sequence=1,
                        event_type=EVENT_TRACE_STARTED,
                        metadata={"workload": WORKLOAD_BACKGROUND_AUTO_LABEL},
                    )
                    audit.commit()
                audit_committed.set()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def waiter() -> None:
            try:
                assert gate_held.wait(timeout=5)
                with Session(engine) as session:
                    session.execute(text("SET LOCAL lock_timeout = '8s'"))
                    LabelService(session, user_id)._lock_user()
                    second_acquired.set()
                    session.commit()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=holder),
            threading.Thread(target=auditor),
            threading.Thread(target=waiter),
        ]
        for item in threads:
            item.start()
        assert audit_committed.wait(timeout=6)
        assert not second_acquired.is_set()
        release_gate.set()
        for item in threads:
            item.join(timeout=10)
            assert not item.is_alive()
        assert second_acquired.is_set()
        assert errors == []
