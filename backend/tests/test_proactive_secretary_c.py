"""Proactive Secretary Pass C — bounded background attention review."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_embedding_service
from app.api.schemas import EdgeCreate, ObjectCreate
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
from app.domain.object_visibility import tombstone_object
from app.jobs.constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_EMBED_OBJECT,
    JOB_TYPE_PROACTIVE_REVIEW,
    JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
    RECURRING_SOURCE_JOB_TYPES,
)
from app.jobs.handlers import get_handler
from app.jobs.worker import process_one_job
from app.llm.assistant_models import AssistantProviderResult
from app.llm.openai_assistant_provider import SYSTEM_INSTRUCTIONS, OpenAIAssistantProvider
from app.main import app
from app.proactive.constants import (
    PROACTIVE_MAX_ROUNDS,
    PROACTIVE_MAX_TOOL_CALLS,
    PROACTIVE_READ_TOOL_NAMES,
    PROACTIVE_SEED_OBJECT_LIMIT,
)
from app.services.graph_service import GraphService
from app.services.job_queue_service import JobQueueService
from app.services.notification_service import NotificationService
from app.services.proactive_review_service import ProactiveReviewService
from app.services.proactive_scheduler import ProactiveScheduler
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE
from app.services.scheduled_activity_service import ScheduledActivityService
from app.tools.registry import ASSISTANT_TOOL_DEFINITIONS, PROACTIVE_TOOL_DEFINITIONS
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient, apply_embedding_service_overrides


class ScriptedProactiveProvider:
    def __init__(
        self,
        answer: str,
        tool_calls: list[tuple[str, dict]] | None = None,
        *,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
        after_tools=None,
    ) -> None:
        self.answer = answer
        self.tool_calls = list(tool_calls or [])
        self.calls = 0
        self.last_tool_definitions = None
        self.last_instructions = ""
        self.last_ui_context = ""
        self.rejected = []
        self._started = started
        self._release = release
        self._after_tools = after_tools

    def run(
        self,
        message,
        history,
        ui_context,
        reference_datetime,
        timezone,
        tool_runner,
        identity_facts=None,
        *,
        system_instructions=None,
        tool_definitions=None,
    ) -> AssistantProviderResult:
        self.calls += 1
        self.last_tool_definitions = tool_definitions
        self.last_instructions = system_instructions or ""
        self.last_ui_context = ui_context
        if self._started is not None:
            self._started.set()
        if self._release is not None and not self._release.wait(timeout=15):
            raise TimeoutError("proactive provider was not released")
        for name, arguments in self.tool_calls:
            result = tool_runner(name, arguments)
            if not result.success:
                self.rejected.append(name)
        if self._after_tools is not None:
            self._after_tools()
        if hasattr(tool_runner, "commit_model_visible_outputs"):
            tool_runner.commit_model_visible_outputs()
        return AssistantProviderResult(
            answer=self.answer,
            candidate_object_ids=[],
            affected_object_ids=[],
            store_false_used=True,
        )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _none_answer() -> str:
    return json.dumps({"decision": "none", "notification": None, "personal_relevance": None})


def _personal_relevance(
    relationship: str = "responsible",
    dependency: str = "waiting_on_user",
) -> dict:
    return {"relationship": relationship, "dependency": dependency}


def _insight_answer(
    source_id,
    *,
    confidence: float = 0.91,
    title: str = "Attention item",
    related_id=None,
    personal_relevance: dict | None = None,
    extra: dict | None = None,
) -> str:
    payload = {
        "decision": "notify",
        "personal_relevance": personal_relevance or _personal_relevance(),
        "notification": {
            "kind": "insight",
            "title": title,
            "body": "A bounded useful insight.",
            "priority": "normal",
            "source_object_id": str(source_id),
            "related_object_id": None if related_id is None else str(related_id),
            "confidence": confidence,
            "task": None,
        },
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload)


def _task_answer(source_id, *, confidence: float = 0.91) -> str:
    return json.dumps(
        {
            "decision": "notify",
            "personal_relevance": _personal_relevance(),
            "notification": {
                "kind": "task_proposal",
                "title": "Proposed follow-up",
                "body": "Create a task from this evidence.",
                "priority": "normal",
                "source_object_id": str(source_id),
                "related_object_id": None,
                "confidence": confidence,
                "task": {
                    "title": "Follow up",
                    "description": "From proactive review",
                    "due_at": None,
                    "start_at": None,
                },
            },
        }
    )


def _enable(session: Session, user_id=BOOTSTRAP_USER_ID, *, interval: int = 60) -> UserSettings:
    row = session.get(UserSettings, user_id)
    if row is None:
        row = UserSettings(user_id=user_id)
        session.add(row)
        session.flush()
    row.proactive_enabled = True
    row.proactive_interval_minutes = interval
    session.flush()
    return row


def _disable(session: Session, user_id=BOOTSTRAP_USER_ID) -> None:
    row = session.get(UserSettings, user_id)
    if row is None:
        return
    row.proactive_enabled = False
    session.flush()


def _source_email(session: Session, user_id=BOOTSTRAP_USER_ID, *, title: str = "Recent mail") -> Object:
    obj = GraphService(session, user_id).create_object(
        ObjectCreate(kind="email", title=title, origin="source", body="Please review the attached plan.")
    )
    session.flush()
    return obj


def _count_jobs(session: Session, user_id=BOOTSTRAP_USER_ID, *, status: str | None = None) -> int:
    stmt = select(func.count()).select_from(Job).where(
        Job.user_id == user_id,
        Job.type == JOB_TYPE_PROACTIVE_REVIEW,
    )
    if status is not None:
        stmt = stmt.where(Job.status == status)
    return session.scalar(stmt)


def _jobs(session: Session, user_id=BOOTSTRAP_USER_ID) -> list[Job]:
    return list(
        session.scalars(
            select(Job).where(
                Job.user_id == user_id,
                Job.type == JOB_TYPE_PROACTIVE_REVIEW,
            )
        )
    )


def _notifications(session: Session, user_id=BOOTSTRAP_USER_ID) -> list[Notification]:
    return list(
        session.scalars(select(Notification).where(Notification.user_id == user_id))
    )


def _proactive_payload(hours_ago: float = 1) -> dict:
    return {"window_start": (_utcnow() - timedelta(hours=hours_ago)).isoformat()}


def _install_provider(monkeypatch, provider: ScriptedProactiveProvider) -> ScriptedProactiveProvider:
    monkeypatch.setattr(
        "app.services.proactive_review_service.create_proactive_provider",
        lambda effective: provider,
    )
    return provider


def _noop_trace(*args, **kwargs):
    from contextlib import nullcontext

    return nullcontext()


@pytest.fixture
def profile_client(db_session, auth_headers, fake_embedding_service):
    def override_get_db():
        yield db_session

    apply_embedding_service_overrides(fake_embedding_service)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_embedding_service] = lambda: fake_embedding_service
    with TestClient(app) as raw:
        yield AuthTestClient(raw, auth_headers)
    app.dependency_overrides.clear()


@pytest.fixture
def silent_trace(monkeypatch):
    monkeypatch.setattr(
        "app.services.proactive_review_service.ai_trace_session",
        _noop_trace,
    )


def test_settings_defaults_disabled(profile_client) -> None:
    body = profile_client.get("/me/settings").json()
    assert body["proactive_enabled"] is False
    assert body["proactive_interval_minutes"] == 60


def test_settings_patch_enable_disable_and_interval_bounds(profile_client) -> None:
    before = profile_client.get("/me/settings").json()
    enabled = profile_client.patch("/me/settings", json={"proactive_enabled": True})
    assert enabled.status_code == 200
    assert enabled.json()["proactive_enabled"] is True
    disabled = profile_client.patch("/me/settings", json={"proactive_enabled": False})
    assert disabled.json()["proactive_enabled"] is False
    low = profile_client.patch("/me/settings", json={"proactive_interval_minutes": 15})
    assert low.status_code == 200
    assert low.json()["proactive_interval_minutes"] == 15
    high = profile_client.patch("/me/settings", json={"proactive_interval_minutes": 1440})
    assert high.status_code == 200
    assert high.json()["proactive_interval_minutes"] == 1440
    assert profile_client.patch("/me/settings", json={"proactive_interval_minutes": 14}).status_code == 422
    assert profile_client.patch("/me/settings", json={"proactive_interval_minutes": 1441}).status_code == 422
    after = profile_client.get("/me/settings").json()
    assert after["assistant_model"] == before["assistant_model"]
    assert after["assistant_reasoning_effort"] == before["assistant_reasoning_effort"]
    assert after["assistant_verbosity"] == before["assistant_verbosity"]
    assert after["assistant_max_rounds"] == before["assistant_max_rounds"]


def test_scheduler_disabled_user_has_no_job(db_session) -> None:
    ProactiveScheduler(db_session).run_maintenance()
    assert _count_jobs(db_session) == 0


def test_scheduler_enabled_exactly_one_pending_and_repeat_stable(db_session) -> None:
    _enable(db_session)
    scheduler = ProactiveScheduler(db_session)
    scheduler.run_maintenance()
    jobs = [job for job in _jobs(db_session) if job.status == JOB_STATUS_PENDING]
    assert len(jobs) == 1
    window_start = datetime.fromisoformat(jobs[0].payload["window_start"])
    assert window_start >= _utcnow() - timedelta(minutes=61)
    first_id = jobs[0].id
    scheduler.run_maintenance()
    jobs = [job for job in _jobs(db_session) if job.status in (JOB_STATUS_PENDING, JOB_STATUS_RUNNING)]
    assert len(jobs) == 1
    assert jobs[0].id == first_id


def test_scheduler_disable_retires_pending(db_session) -> None:
    _enable(db_session)
    ProactiveScheduler(db_session).run_maintenance()
    assert _count_jobs(db_session, status=JOB_STATUS_PENDING) == 1
    _disable(db_session)
    ProactiveScheduler(db_session).run_maintenance()
    assert _count_jobs(db_session, status=JOB_STATUS_PENDING) == 0
    assert all(job.status == JOB_STATUS_DONE for job in _jobs(db_session))


def test_running_disabled_skips_llm_notification_successor(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    source = _source_email(db_session)
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_insight_answer(source.id)))
    _disable(db_session)
    before_jobs = _count_jobs(db_session)
    before_notes = len(_notifications(db_session))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 0
    assert _count_jobs(db_session) == before_jobs
    assert len(_notifications(db_session)) == before_notes


def test_successful_run_enqueues_one_successor_with_current_interval(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session, interval=90)
    _source_email(db_session)
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    before = _count_jobs(db_session)
    started = _utcnow()
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 1
    successors = [
        job
        for job in _jobs(db_session)
        if job.status == JOB_STATUS_PENDING and job.type == JOB_TYPE_PROACTIVE_REVIEW
    ]
    assert len(successors) == 1
    assert _count_jobs(db_session) == before + 1
    delta = successors[0].run_after - started
    assert timedelta(minutes=89) <= delta <= timedelta(minutes=91)


def test_gate_quiet_window_skips_llm(db_session, monkeypatch, silent_trace) -> None:
    _enable(db_session)
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 0
    assert _count_jobs(db_session, status=JOB_STATUS_PENDING) == 1


def test_gate_recent_source_object_eligible(db_session, monkeypatch, silent_trace) -> None:
    _enable(db_session)
    _source_email(db_session)
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 1


def test_gate_approaching_open_task(db_session, monkeypatch, silent_trace) -> None:
    _enable(db_session)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    graph.create_object(
        ObjectCreate(
            kind="task",
            title="Due soon",
            origin="user",
            status="open",
            due_at=_utcnow() + timedelta(hours=12),
        )
    )
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(
        {"window_start": (_utcnow() - timedelta(minutes=5)).isoformat()}
    )
    assert provider.calls == 1


def test_gate_recently_overdue_task(db_session, monkeypatch, silent_trace) -> None:
    _enable(db_session)
    GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="task",
            title="Recently overdue",
            origin="user",
            status="in_progress",
            due_at=_utcnow() - timedelta(days=2),
        )
    )
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(
        {"window_start": (_utcnow() - timedelta(minutes=5)).isoformat()}
    )
    assert provider.calls == 1


def test_gate_upcoming_event(db_session, monkeypatch, silent_trace) -> None:
    _enable(db_session)
    GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="event",
            title="Standup",
            origin="source",
            start_at=_utcnow() + timedelta(hours=3),
        )
    )
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(
        {"window_start": (_utcnow() - timedelta(minutes=5)).isoformat()}
    )
    assert provider.calls == 1


def test_gate_rejected_tombstoned_attachment_not_eligible(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    rejected = graph.create_object(
        ObjectCreate(kind="email", title="Rejected", origin="source", state=REJECTED_STATE)
    )
    tombstoned = graph.create_object(
        ObjectCreate(kind="email", title="Deleted", origin="source")
    )
    tombstone_object(tombstoned)
    attachment = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        title="Child attachment",
        origin="source",
        state="observed",
        metadata_={"parent_email_id": str(uuid.uuid4())},
    )
    db_session.add(attachment)
    db_session.flush()
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 0
    assert rejected.id is not None


@pytest.mark.parametrize("tool_name", ["send_email", "create_task", "create_calendar_event"])
def test_forbidden_tool_then_valid_insight_is_not_persisted(
    db_session, monkeypatch, silent_trace, tool_name
) -> None:
    _enable(db_session)
    source = _source_email(db_session)
    provider = _install_provider(
        monkeypatch,
        ScriptedProactiveProvider(
            _insight_answer(source.id),
            tool_calls=[(tool_name, {"title": "x", "to": "a@b.c"})],
        ),
    )
    before_plans = db_session.scalar(select(func.count()).select_from(PendingActionPlan))
    before_attempts = db_session.scalar(select(func.count()).select_from(ExternalActionAttempt))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 1
    assert provider.rejected == [tool_name]
    assert _notifications(db_session) == []
    assert db_session.scalar(select(func.count()).select_from(PendingActionPlan)) == before_plans
    assert db_session.scalar(select(func.count()).select_from(ExternalActionAttempt)) == before_attempts
    assert _count_jobs(db_session, status=JOB_STATUS_PENDING) == 1


def test_proactive_tool_definitions_are_read_only() -> None:
    names = [item["name"] for item in PROACTIVE_TOOL_DEFINITIONS]
    assert names == list(PROACTIVE_READ_TOOL_NAMES)
    assert "send_email" not in names
    assert "create_task" not in names
    assert "create_calendar_event" not in names


def test_none_result_and_low_confidence(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    source = _source_email(db_session)
    _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert len(_notifications(db_session)) == 0
    assert _count_jobs(db_session, status=JOB_STATUS_PENDING) == 1

    _install_provider(monkeypatch, ScriptedProactiveProvider(_insight_answer(source.id, confidence=0.5)))
    before = len(_notifications(db_session))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert len(_notifications(db_session)) == before


def test_valid_insight_creates_one_notification(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    source = _source_email(db_session)
    before_objects = db_session.scalar(select(func.count()).select_from(Object))
    before_edges = db_session.scalar(select(func.count()).select_from(Edge))
    before_plans = db_session.scalar(select(func.count()).select_from(PendingActionPlan))
    _install_provider(monkeypatch, ScriptedProactiveProvider(_insight_answer(source.id)))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    notes = _notifications(db_session)
    assert len(notes) == 1
    assert notes[0].proposal_["type"] == "proactive_insight"
    assert notes[0].source_object_id == source.id
    assert db_session.scalar(select(func.count()).select_from(Object)) == before_objects
    assert db_session.scalar(select(func.count()).select_from(Edge)) == before_edges
    assert db_session.scalar(select(func.count()).select_from(PendingActionPlan)) == before_plans


def test_task_proposal_created_only_after_accept(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    source = _source_email(db_session)
    before_tasks = db_session.scalar(
        select(func.count()).select_from(Object).where(Object.kind == "task")
    )
    _install_provider(monkeypatch, ScriptedProactiveProvider(_task_answer(source.id)))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    notes = _notifications(db_session)
    assert len(notes) == 1
    assert notes[0].proposal_["type"] == "task"
    assert notes[0].proposal_["proactive"] is True
    assert db_session.scalar(
        select(func.count()).select_from(Object).where(Object.kind == "task")
    ) == before_tasks
    service = NotificationService(db_session, BOOTSTRAP_USER_ID)
    accepted = service.accept(notes[0].id)
    assert accepted.result_object_id is not None
    assert db_session.scalar(
        select(func.count()).select_from(Object).where(Object.kind == "task")
    ) == before_tasks + 1
    again = service.accept(notes[0].id)
    assert again.result_object_id == accepted.result_object_id
    assert db_session.scalar(
        select(func.count()).select_from(Object).where(Object.kind == "task")
    ) == before_tasks + 1
    edge = db_session.scalar(
        select(Edge).where(
            Edge.source_id == accepted.result_object_id,
            Edge.target_id == source.id,
        )
    )
    assert edge is not None


def test_duplicate_active_task_suppresses_proposal(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _source_email(db_session)
    task = graph.create_object(
        ObjectCreate(kind="task", title="Existing", origin="user", status="open")
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=source.id,
            type="references",
            origin="user",
            state="confirmed",
        )
    )
    _install_provider(monkeypatch, ScriptedProactiveProvider(_task_answer(source.id)))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert _notifications(db_session) == []
    assert db_session.get(Object, task.id).title == "Existing"


def test_unresolved_and_cooldown_dedupe(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    source = _source_email(db_session)
    _install_provider(monkeypatch, ScriptedProactiveProvider(_insight_answer(source.id)))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert len(_notifications(db_session)) == 1
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert len(_notifications(db_session)) == 1
    note = _notifications(db_session)[0]
    NotificationService(db_session, BOOTSTRAP_USER_ID).ignore(note.id)
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert len(_notifications(db_session)) == 1


def test_attention_cap_skips_llm(db_session, monkeypatch, silent_trace) -> None:
    _enable(db_session)
    source = _source_email(db_session)
    service = NotificationService(db_session, BOOTSTRAP_USER_ID)
    for index in range(3):
        service.create(
            title=f"Open {index}",
            body=None,
            priority="normal",
            source_object_id=source.id,
            proposal={
                "type": "proactive_insight",
                "proactive": True,
                "proactive_signature": f"cap-{index}",
                "version": 1,
                "confidence": 0.9,
            },
        )
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_insight_answer(source.id)))
    before = len(_notifications(db_session))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 0
    assert len(_notifications(db_session)) == before
    assert _count_jobs(db_session, status=JOB_STATUS_PENDING) == 1


@pytest.mark.parametrize(
    "mode",
    ["foreign", "invented", "deleted", "rejected", "unseen"],
)
def test_evidence_id_safety(db_session, monkeypatch, silent_trace, mode) -> None:
    _enable(db_session)
    visible = _source_email(db_session, title="Visible")
    if mode == "foreign":
        other_user = User(id=uuid.uuid4(), display_name="other")
        db_session.add(other_user)
        db_session.flush()
        foreign = GraphService(db_session, other_user.id).create_object(
            ObjectCreate(kind="email", title="Foreign", origin="source")
        )
        cited = foreign.id
        seed = visible
    elif mode == "invented":
        cited = uuid.uuid4()
        seed = visible
    elif mode == "deleted":
        deleted = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
            ObjectCreate(kind="email", title="Gone", origin="source")
        )
        tombstone_object(deleted)
        cited = deleted.id
        seed = visible
    elif mode == "rejected":
        rejected = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
            ObjectCreate(kind="email", title="No", origin="source", state=REJECTED_STATE)
        )
        cited = rejected.id
        seed = visible
    else:
        unseen = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
            ObjectCreate(kind="email", title="Unseen", origin="source")
        )
        unseen.updated_at = _utcnow() - timedelta(days=30)
        cited = unseen.id
        seed = visible
    _install_provider(monkeypatch, ScriptedProactiveProvider(_insight_answer(cited)))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert _notifications(db_session) == []
    assert seed.id is not None


def test_one_notification_per_run(db_session, monkeypatch, silent_trace) -> None:
    _enable(db_session)
    first = _source_email(db_session, title="One")
    _source_email(db_session, title="Two")
    _install_provider(monkeypatch, ScriptedProactiveProvider(_insight_answer(first.id)))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert len(_notifications(db_session)) == 1


def test_interactive_assistant_keeps_full_tool_set(monkeypatch) -> None:
    captured: list[dict] = []

    class FakeResponses:
        def create(self, **kwargs):
            captured.append(kwargs)
            response = MagicMock()
            response.status = "completed"
            response.usage = MagicMock(input_tokens=1, output_tokens=1)
            response.output = []
            response.output_text = "ok"
            return response

    class FakeClient:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))
    provider = OpenAIAssistantProvider(api_key="test", model="gpt-test", max_rounds=6)
    provider.run(
        message="hello",
        history=[],
        ui_context="",
        reference_datetime=_utcnow(),
        timezone="Europe/Amsterdam",
        tool_runner=lambda *_: None,
    )
    assert captured[0]["tools"] is ASSISTANT_TOOL_DEFINITIONS
    assert provider.last_instructions.startswith(SYSTEM_INSTRUCTIONS[:40])
    names = {item["name"] for item in captured[0]["tools"]}
    assert "send_email" in names
    assert "create_task" in names
    assert provider.max_rounds == 6


def test_proactive_openai_call_uses_read_only_tools(monkeypatch) -> None:
    captured: list[dict] = []

    class FakeResponses:
        def create(self, **kwargs):
            captured.append(kwargs)
            response = MagicMock()
            response.status = "completed"
            response.usage = MagicMock(input_tokens=1, output_tokens=1)
            response.output = []
            response.output_text = _none_answer()
            return response

    class FakeClient:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))
    provider = OpenAIAssistantProvider(
        api_key="test",
        model="gpt-test",
        max_rounds=PROACTIVE_MAX_ROUNDS,
        max_output_tokens=800,
    )
    from app.proactive.instructions import PROACTIVE_SYSTEM_INSTRUCTIONS
    from app.proactive.tool_runner import ProactiveToolRunner

    runner = ProactiveToolRunner(MagicMock(), max_calls=PROACTIVE_MAX_TOOL_CALLS)
    provider.run(
        message="review",
        history=[],
        ui_context="{}",
        reference_datetime=_utcnow(),
        timezone="Europe/Amsterdam",
        tool_runner=runner,
        system_instructions=PROACTIVE_SYSTEM_INSTRUCTIONS,
        tool_definitions=PROACTIVE_TOOL_DEFINITIONS,
    )
    assert captured[0]["tools"] is PROACTIVE_TOOL_DEFINITIONS
    assert {item["name"] for item in captured[0]["tools"]} == set(PROACTIVE_READ_TOOL_NAMES)
    assert provider.max_rounds == 4


def test_proactive_job_type_is_general_lane() -> None:
    assert JOB_TYPE_PROACTIVE_REVIEW not in RECURRING_SOURCE_JOB_TYPES
    assert JOB_TYPE_PROACTIVE_REVIEW != JOB_TYPE_RUN_SCHEDULED_ACTIVITY


def _persist_user() -> uuid.UUID:
    user_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=user_id, display_name=f"proactive-{user_id}"))
        session.commit()
    return user_id


def _cleanup_committed(user_id: uuid.UUID) -> None:
    with Session(engine) as session:
        session.execute(delete(Notification).where(Notification.user_id == user_id))
        session.execute(delete(AITraceEvent).where(AITraceEvent.user_id == user_id))
        session.execute(delete(AITrace).where(AITrace.user_id == user_id))
        session.execute(delete(Job).where(Job.user_id == user_id))
        session.execute(delete(Edge).where(Edge.user_id == user_id))
        session.execute(delete(Object).where(Object.user_id == user_id))
        session.execute(delete(UserSettings).where(UserSettings.user_id == user_id))
        session.execute(delete(User).where(User.id == user_id))
        session.commit()


def test_rollback_then_retry_exactly_once(monkeypatch) -> None:
    user_id = _persist_user()
    fail_once = {"armed": True}
    original = JobQueueService.enqueue

    def wrapping(self, job_type, payload, user_id_arg=None, run_after=None, **kwargs):
        job = original(self, job_type, payload, user_id_arg or kwargs.get("user_id"), run_after=run_after)
        if job_type == JOB_TYPE_PROACTIVE_REVIEW and fail_once["armed"]:
            fail_once["armed"] = False
            raise RuntimeError("injected failure after notify")
        return job

    try:
        with Session(engine) as session:
            _enable(session, user_id)
            source = _source_email(session, user_id)
            source_id = source.id
            JobQueueService(session).enqueue(
                JOB_TYPE_PROACTIVE_REVIEW,
                _proactive_payload(),
                user_id,
                run_after=_utcnow() - timedelta(seconds=1),
            )
            session.commit()
        _install_provider(monkeypatch, ScriptedProactiveProvider(_insight_answer(source_id)))
        monkeypatch.setattr(
            "app.services.proactive_review_service.ai_trace_session",
            _noop_trace,
        )
        monkeypatch.setattr(JobQueueService, "enqueue", wrapping)
        process_one_job(include_types={JOB_TYPE_PROACTIVE_REVIEW})
        with Session(engine) as session:
            notes = list(session.scalars(select(Notification).where(Notification.user_id == user_id)))
            jobs = list(
                session.scalars(
                    select(Job).where(
                        Job.user_id == user_id,
                        Job.type == JOB_TYPE_PROACTIVE_REVIEW,
                    )
                )
            )
            assert notes == []
            assert sum(1 for job in jobs if job.status == JOB_STATUS_PENDING) == 1
            assert all(job.status != JOB_STATUS_DONE for job in jobs)
            pending = next(job for job in jobs if job.status == JOB_STATUS_PENDING)
            pending.run_after = _utcnow() - timedelta(seconds=1)
            session.commit()
        fail_once["armed"] = False
        process_one_job(include_types={JOB_TYPE_PROACTIVE_REVIEW})
        with Session(engine) as session:
            notes = list(session.scalars(select(Notification).where(Notification.user_id == user_id)))
            jobs = list(
                session.scalars(
                    select(Job).where(
                        Job.user_id == user_id,
                        Job.type == JOB_TYPE_PROACTIVE_REVIEW,
                    )
                )
            )
            assert len(notes) == 1
            assert sum(1 for job in jobs if job.status == JOB_STATUS_DONE) == 1
            assert sum(1 for job in jobs if job.status == JOB_STATUS_PENDING) == 1
    finally:
        _cleanup_committed(user_id)


def test_overdue_coalescing_single_review(monkeypatch) -> None:
    user_id = _persist_user()
    try:
        with Session(engine) as session:
            _enable(session, user_id)
            source = _source_email(session, user_id)
            source_id = source.id
            window_start = _utcnow() - timedelta(hours=3)
            JobQueueService(session).enqueue(
                JOB_TYPE_PROACTIVE_REVIEW,
                {"window_start": window_start.isoformat()},
                user_id,
                run_after=_utcnow() - timedelta(hours=2),
            )
            session.commit()
        provider = _install_provider(
            monkeypatch, ScriptedProactiveProvider(_insight_answer(source_id))
        )
        monkeypatch.setattr(
            "app.services.proactive_review_service.ai_trace_session",
            _noop_trace,
        )
        now = _utcnow()
        process_one_job(include_types={JOB_TYPE_PROACTIVE_REVIEW})
        assert provider.calls == 1
        with Session(engine) as session:
            notes = list(session.scalars(select(Notification).where(Notification.user_id == user_id)))
            pending = list(
                session.scalars(
                    select(Job).where(
                        Job.user_id == user_id,
                        Job.type == JOB_TYPE_PROACTIVE_REVIEW,
                        Job.status == JOB_STATUS_PENDING,
                    )
                )
            )
            assert len(notes) <= 1
            assert len(pending) == 1
            assert pending[0].run_after >= now
            start = datetime.fromisoformat(pending[0].payload["window_start"])
            assert start >= now - timedelta(minutes=2)
    finally:
        _cleanup_committed(user_id)


def test_scheduled_lane_isolated_from_blocked_proactive(monkeypatch) -> None:
    user_id = _persist_user()
    started = threading.Event()
    release = threading.Event()

    def blocking_proactive(session, embedding_service, payload, user_id_arg):
        started.set()
        if not release.wait(timeout=15):
            raise TimeoutError("proactive handler was not released")

    original = get_handler

    def patched(job_type: str):
        if job_type == JOB_TYPE_PROACTIVE_REVIEW:
            return blocking_proactive
        return original(job_type)

    monkeypatch.setattr("app.jobs.worker.get_handler", patched)
    try:
        with Session(engine) as session:
            _enable(session, user_id)
            JobQueueService(session).enqueue(
                JOB_TYPE_PROACTIVE_REVIEW,
                _proactive_payload(),
                user_id,
                run_after=_utcnow() - timedelta(seconds=1),
            )
            graph = GraphService(session, user_id)
            obj = ScheduledActivityService(session, user_id, graph).create_once(
                title="Lane reminder",
                body="Keep scheduled lane free",
                run_at=_utcnow() + timedelta(hours=2),
                priority="normal",
                origin_state="confirmed",
                confidence=None,
                enqueue_embedding=False,
            )
            job = session.scalar(
                select(Job).where(
                    Job.user_id == user_id,
                    Job.type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
                )
            )
            assert job is not None
            due = _utcnow() - timedelta(seconds=1)
            obj.due_at = due
            job.run_after = due
            scheduled_job_id = job.id
            session.commit()

        general = threading.Thread(
            target=lambda: process_one_job(exclude_types={JOB_TYPE_RUN_SCHEDULED_ACTIVITY}),
            daemon=True,
        )
        general.start()
        assert started.wait(timeout=5)
        processed = process_one_job(include_types={JOB_TYPE_RUN_SCHEDULED_ACTIVITY})
        assert processed
        with Session(engine) as session:
            notes = list(session.scalars(select(Notification).where(Notification.user_id == user_id)))
            scheduled_job = session.get(Job, scheduled_job_id)
            proactive = list(
                session.scalars(
                    select(Job).where(
                        Job.user_id == user_id,
                        Job.type == JOB_TYPE_PROACTIVE_REVIEW,
                    )
                )
            )
            assert notes
            assert scheduled_job.status == JOB_STATUS_DONE
            assert any(job.status == JOB_STATUS_RUNNING for job in proactive)
        release.set()
        general.join(timeout=10)
    finally:
        release.set()
        _cleanup_committed(user_id)


def test_aitrace_background_proactive_workload(monkeypatch) -> None:
    from app.ai_audit.constants import (
        WORKLOAD_ASSISTANT_INTERACTIVE,
        WORKLOAD_BACKGROUND_PROACTIVE_REVIEW,
    )

    user_id = _persist_user()
    try:
        with Session(engine) as session:
            _enable(session, user_id)
            source = _source_email(session, user_id)
            job = JobQueueService(session).enqueue(
                JOB_TYPE_PROACTIVE_REVIEW,
                _proactive_payload(),
                user_id,
                run_after=_utcnow() - timedelta(seconds=1),
            )
            job_id = job.id
            source_id = source.id
            session.commit()
        _install_provider(monkeypatch, ScriptedProactiveProvider(_insight_answer(source_id)))
        process_one_job(include_types={JOB_TYPE_PROACTIVE_REVIEW})
        with Session(engine) as session:
            traces = list(session.scalars(select(AITrace).where(AITrace.user_id == user_id)))
            assert traces
            assert all(trace.workload == WORKLOAD_BACKGROUND_PROACTIVE_REVIEW for trace in traces)
            assert all(trace.job_id == job_id for trace in traces)
            assert all(trace.workload != WORKLOAD_ASSISTANT_INTERACTIVE for trace in traces)
    finally:
        _cleanup_committed(user_id)


def test_failed_proactive_job_is_rearmed_not_duplicated(db_session) -> None:
    _enable(db_session)
    job = JobQueueService(db_session).enqueue(
        JOB_TYPE_PROACTIVE_REVIEW,
        _proactive_payload(),
        BOOTSTRAP_USER_ID,
    )
    job.status = JOB_STATUS_FAILED
    job.run_after = _utcnow() - timedelta(seconds=1)
    db_session.flush()
    ProactiveScheduler(db_session).run_maintenance()
    jobs = _jobs(db_session)
    held = [item for item in jobs if item.status in (JOB_STATUS_PENDING, JOB_STATUS_FAILED)]
    assert len(held) == 1
    assert held[0].id == job.id
    assert held[0].status == JOB_STATUS_PENDING


def test_forbidden_calls_consume_tool_budget() -> None:
    from app.proactive.tool_runner import ProactiveToolRunner

    runner = ProactiveToolRunner(MagicMock(), max_calls=PROACTIVE_MAX_TOOL_CALLS)
    for _ in range(PROACTIVE_MAX_TOOL_CALLS):
        result = runner("send_email", {"to": "a@b.c"})
        assert not result.success
        assert not result.limit_reached
    overflow = runner("retrieve", {"query": "x"})
    assert overflow.limit_reached
    assert runner.calls_made == PROACTIVE_MAX_TOOL_CALLS
    assert runner.security_violation
    assert runner.has_rejected_tool_attempt


def test_upcoming_calendar_event_kind_is_eligible(db_session, monkeypatch, silent_trace) -> None:
    _enable(db_session)
    GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="calendar_event",
            title="Legacy calendar",
            origin="source",
            start_at=_utcnow() + timedelta(hours=2),
        )
    )
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(
        {"window_start": (_utcnow() - timedelta(minutes=5)).isoformat()}
    )
    assert provider.calls == 1


def test_explicit_file_with_parent_email_id_is_eligible(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    db_session.add(
        Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="file",
            title="Explicit file",
            origin="explicit",
            state=CONFIRMED_STATE,
            metadata_={"parent_email_id": str(uuid.uuid4())},
        )
    )
    db_session.flush()
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 1


def test_proposed_references_edge_does_not_suppress_task_proposal(
    db_session, monkeypatch, silent_trace
) -> None:
    _enable(db_session)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    source = _source_email(db_session)
    task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="Proposed link only",
            origin="agent",
            state="proposed",
            status="open",
            confidence=0.8,
        )
    )
    graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=source.id,
            type="references",
            origin="agent",
            state="proposed",
            confidence=0.8,
        )
    )
    _install_provider(monkeypatch, ScriptedProactiveProvider(_task_answer(source.id)))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    notes = _notifications(db_session)
    assert len(notes) == 1
    assert notes[0].proposal_["type"] == "task"


def test_sql_bounded_gate_queries(db_session, monkeypatch, silent_trace) -> None:
    _enable(db_session)
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    now = _utcnow()
    extras = PROACTIVE_SEED_OBJECT_LIMIT + 8
    window_start = now - timedelta(hours=1)
    window_end = now + timedelta(seconds=1)
    service = ProactiveReviewService(db_session, BOOTSTRAP_USER_ID)

    emails: list[Object] = []
    for index in range(extras):
        emails.append(
            graph.create_object(
                ObjectCreate(kind="email", title=f"Mail {index:02d}", origin="source")
            )
        )
    for index, obj in enumerate(emails):
        db_session.execute(
            Object.__table__.update()
            .where(Object.id == obj.id)
            .values(updated_at=now - timedelta(seconds=index))
        )
    db_session.flush()
    for obj in emails:
        db_session.refresh(obj)
    recent = service._recent_activity(window_start, window_end)
    expected_recent = sorted(emails, key=lambda item: (item.updated_at, item.id), reverse=True)
    assert len(recent) == PROACTIVE_SEED_OBJECT_LIMIT
    assert [obj.id for obj in recent] == [obj.id for obj in expected_recent[:PROACTIVE_SEED_OBJECT_LIMIT]]
    assert [obj.id for obj in recent] != [obj.id for obj in expected_recent]

    tasks: list[Object] = []
    for index in range(extras):
        tasks.append(
            graph.create_object(
                ObjectCreate(
                    kind="task",
                    title=f"Task {index:02d}",
                    origin="user",
                    status="open",
                    due_at=now + timedelta(minutes=index + 1),
                )
            )
        )
    due = service._attention_tasks(now)
    assert len(due) == PROACTIVE_SEED_OBJECT_LIMIT
    assert [obj.id for obj in due] == [
        obj.id for obj in sorted(tasks, key=lambda item: (item.due_at, item.id))[:PROACTIVE_SEED_OBJECT_LIMIT]
    ]

    events: list[Object] = []
    for index in range(extras):
        events.append(
            graph.create_object(
                ObjectCreate(
                    kind="event",
                    title=f"Event {index:02d}",
                    origin="source",
                    start_at=now + timedelta(minutes=index + 1),
                )
            )
        )
    upcoming = service._upcoming_events(now)
    assert len(upcoming) == PROACTIVE_SEED_OBJECT_LIMIT
    assert [obj.id for obj in upcoming] == [
        obj.id
        for obj in sorted(events, key=lambda item: (item.start_at, item.id))[:PROACTIVE_SEED_OBJECT_LIMIT]
    ]

    seeds = service._gate_seed_objects(window_start, window_end, now)
    assert len(seeds) <= PROACTIVE_SEED_OBJECT_LIMIT
    provider = _install_provider(monkeypatch, ScriptedProactiveProvider(_none_answer()))
    ProactiveReviewService(db_session, BOOTSTRAP_USER_ID).run(_proactive_payload())
    assert provider.calls == 1


def test_concurrent_sync_user_creates_exactly_one_job() -> None:
    user_id = _persist_user()
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            with Session(engine) as session:
                barrier.wait(timeout=10)
                ProactiveScheduler(session).sync_user(user_id)
                session.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    try:
        with Session(engine) as session:
            _enable(session, user_id)
            session.commit()
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        assert errors == []
        with Session(engine) as session:
            held = [
                job
                for job in session.scalars(
                    select(Job).where(
                        Job.user_id == user_id,
                        Job.type == JOB_TYPE_PROACTIVE_REVIEW,
                        Job.status.in_((JOB_STATUS_PENDING, JOB_STATUS_RUNNING)),
                    )
                )
            ]
            assert len(held) == 1
    finally:
        _cleanup_committed(user_id)


def test_disable_before_llm_uses_fresh_db_read(monkeypatch) -> None:
    user_id = _persist_user()
    try:
        with Session(engine) as session:
            _enable(session, user_id)
            source = _source_email(session, user_id)
            source_id = source.id
            session.commit()
        provider = _install_provider(
            monkeypatch, ScriptedProactiveProvider(_insight_answer(source_id))
        )
        monkeypatch.setattr(
            "app.services.proactive_review_service.ai_trace_session",
            _noop_trace,
        )
        real = ProactiveReviewService._run_llm

        def wrapped(self, *args, **kwargs):
            cached = self._session.get(UserSettings, user_id)
            assert cached is not None
            assert cached.proactive_enabled is True
            with Session(engine) as other:
                row = other.get(UserSettings, user_id)
                assert row is not None
                row.proactive_enabled = False
                other.commit()
            assert cached.proactive_enabled is True
            assert self._session.get(UserSettings, user_id).proactive_enabled is True
            return real(self, *args, **kwargs)

        monkeypatch.setattr(ProactiveReviewService, "_run_llm", wrapped)
        with Session(engine) as session:
            ProactiveReviewService(session, user_id).run(_proactive_payload())
            session.commit()
            assert provider.calls == 0
            assert list(session.scalars(select(Notification).where(Notification.user_id == user_id))) == []
            pending = session.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.user_id == user_id,
                    Job.type == JOB_TYPE_PROACTIVE_REVIEW,
                    Job.status == JOB_STATUS_PENDING,
                )
            )
            assert pending == 0
    finally:
        _cleanup_committed(user_id)


def test_disable_during_llm_suppresses_persist(monkeypatch) -> None:
    user_id = _persist_user()
    started = threading.Event()
    release = threading.Event()
    try:
        with Session(engine) as session:
            _enable(session, user_id)
            source = _source_email(session, user_id)
            JobQueueService(session).enqueue(
                JOB_TYPE_PROACTIVE_REVIEW,
                _proactive_payload(),
                user_id,
                run_after=_utcnow() - timedelta(seconds=1),
            )
            source_id = source.id
            session.commit()
        _install_provider(
            monkeypatch,
            ScriptedProactiveProvider(
                _insight_answer(source_id),
                started=started,
                release=release,
            ),
        )
        worker = threading.Thread(
            target=lambda: process_one_job(include_types={JOB_TYPE_PROACTIVE_REVIEW}),
            daemon=True,
        )
        worker.start()
        assert started.wait(timeout=5)
        with Session(engine) as other:
            row = other.get(UserSettings, user_id)
            assert row is not None
            row.proactive_enabled = False
            other.commit()
        release.set()
        worker.join(timeout=15)
        with Session(engine) as session:
            notes = list(session.scalars(select(Notification).where(Notification.user_id == user_id)))
            pending = list(
                session.scalars(
                    select(Job).where(
                        Job.user_id == user_id,
                        Job.type == JOB_TYPE_PROACTIVE_REVIEW,
                        Job.status == JOB_STATUS_PENDING,
                    )
                )
            )
            done = list(
                session.scalars(
                    select(Job).where(
                        Job.user_id == user_id,
                        Job.type == JOB_TYPE_PROACTIVE_REVIEW,
                        Job.status == JOB_STATUS_DONE,
                    )
                )
            )
            assert notes == []
            assert pending == []
            assert len(done) == 1
    finally:
        release.set()
        _cleanup_committed(user_id)


def test_interval_change_during_llm_used_for_successor(monkeypatch) -> None:
    user_id = _persist_user()
    started = threading.Event()
    release = threading.Event()
    try:
        with Session(engine) as session:
            _enable(session, user_id, interval=60)
            source = _source_email(session, user_id)
            JobQueueService(session).enqueue(
                JOB_TYPE_PROACTIVE_REVIEW,
                _proactive_payload(),
                user_id,
                run_after=_utcnow() - timedelta(seconds=1),
            )
            source_id = source.id
            session.commit()
        _install_provider(
            monkeypatch,
            ScriptedProactiveProvider(
                _insight_answer(source_id),
                started=started,
                release=release,
            ),
        )
        worker = threading.Thread(
            target=lambda: process_one_job(include_types={JOB_TYPE_PROACTIVE_REVIEW}),
            daemon=True,
        )
        worker.start()
        assert started.wait(timeout=5)
        with Session(engine) as other:
            row = other.get(UserSettings, user_id)
            assert row is not None
            row.proactive_interval_minutes = 15
            other.commit()
        release.set()
        worker.join(timeout=15)
        with Session(engine) as session:
            pending = session.scalar(
                select(Job).where(
                    Job.user_id == user_id,
                    Job.type == JOB_TYPE_PROACTIVE_REVIEW,
                    Job.status == JOB_STATUS_PENDING,
                )
            )
            assert pending is not None
            delta = pending.run_after - datetime.fromisoformat(pending.payload["window_start"])
            assert timedelta(minutes=14) <= delta <= timedelta(minutes=16)
    finally:
        release.set()
        _cleanup_committed(user_id)


def test_failed_rearm_respects_fresh_opt_out() -> None:
    user_id = _persist_user()
    try:
        with Session(engine) as session:
            _enable(session, user_id)
            job = JobQueueService(session).enqueue(
                JOB_TYPE_PROACTIVE_REVIEW,
                _proactive_payload(),
                user_id,
            )
            job.status = JOB_STATUS_FAILED
            job.run_after = _utcnow() - timedelta(seconds=1)
            session.commit()
        with Session(engine) as session:
            row = session.get(UserSettings, user_id)
            assert row is not None
            row.proactive_enabled = False
            session.commit()
        with Session(engine) as session:
            ProactiveScheduler(session).run_maintenance()
            session.commit()
            held = list(
                session.scalars(
                    select(Job).where(
                        Job.user_id == user_id,
                        Job.type == JOB_TYPE_PROACTIVE_REVIEW,
                        Job.status.in_((JOB_STATUS_PENDING, JOB_STATUS_FAILED)),
                    )
                )
            )
            assert held == []
    finally:
        _cleanup_committed(user_id)


def test_source_scheduler_failure_does_not_block_proactive(monkeypatch) -> None:
    from app.services.source_sync_scheduler import SourceSyncScheduler
    from app.worker.run import run_scheduler_maintenance

    user_id = _persist_user()
    try:
        with Session(engine) as session:
            _enable(session, user_id)
            session.commit()

        def boom(self) -> None:
            raise RuntimeError("source sync scheduler exploded")

        monkeypatch.setattr(SourceSyncScheduler, "run_maintenance", boom)
        run_scheduler_maintenance()
        with Session(engine) as session:
            pending = list(
                session.scalars(
                    select(Job).where(
                        Job.user_id == user_id,
                        Job.type == JOB_TYPE_PROACTIVE_REVIEW,
                        Job.status == JOB_STATUS_PENDING,
                    )
                )
            )
            assert len(pending) == 1
    finally:
        _cleanup_committed(user_id)


def test_proactive_scheduler_failure_does_not_rollback_source(monkeypatch) -> None:
    from app.services.source_sync_scheduler import SourceSyncScheduler
    from app.worker.run import run_scheduler_maintenance

    user_id = _persist_user()
    try:
        with Session(engine) as session:
            session.add(UserSettings(user_id=user_id, proactive_enabled=False))
            session.commit()

        def source_work(self) -> None:
            JobQueueService(self._session).enqueue(
                JOB_TYPE_EMBED_OBJECT,
                {"marker": "source-maintenance"},
                user_id,
            )

        def boom(self) -> None:
            raise RuntimeError("proactive scheduler exploded")

        monkeypatch.setattr(SourceSyncScheduler, "run_maintenance", source_work)
        monkeypatch.setattr(ProactiveScheduler, "run_maintenance", boom)
        run_scheduler_maintenance()
        with Session(engine) as session:
            marker = session.scalar(
                select(Job).where(
                    Job.user_id == user_id,
                    Job.type == JOB_TYPE_EMBED_OBJECT,
                )
            )
            assert marker is not None
            assert marker.payload["marker"] == "source-maintenance"
    finally:
        _cleanup_committed(user_id)

