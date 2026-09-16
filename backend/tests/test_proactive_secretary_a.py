"""Proactive Secretary Pass A — one-shot scheduled_activity foundation."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.schemas import ObjectCreate
from app.db.engine import engine
from app.db.models import Job, Notification, Object, User
from app.domain.object_visibility import tombstone_object
from app.domain.scheduled_activity import (
    KIND_SCHEDULED_ACTIVITY,
    METADATA_PRIORITY,
    METADATA_SCHEDULE_KIND,
    SCHEDULE_KIND_ONCE,
    SCHEDULED_ACTIVITY_STATUS_CANCELLED,
    SCHEDULED_ACTIVITY_STATUS_COMPLETED,
    SCHEDULED_ACTIVITY_STATUS_SCHEDULED,
)
from app.jobs.constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_PENDING,
    JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
    RECURRING_SOURCE_JOB_TYPES,
)
from app.jobs.scheduled_activity_handler import handle_run_scheduled_activity
from app.jobs.worker import process_one_job
from app.services.action_plan_service import ActionPlanService
from app.services.domain_tool_service import DomainToolService
from app.services.domain_write_mode import DomainWriteMode
from app.services.graph_service import GraphService
from app.services.job_queue_service import JobQueueService
from app.services.notification_service import NotificationService
from app.services.scheduled_activity_service import ScheduledActivityService
from app.tools.execution_context import ExecutionContext
from app.tools.gateway import ToolExecutionGateway
from app.tools.policy import ToolPermission
from app.tools.registry import TOOL_REGISTRY
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import QueryObjectsInput
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture
def mcp_server(patched_mcp_tool_session):
    from app.mcp.server import create_mcp_server

    return create_mcp_server()


def _future_run_at(*, hours: int = 2) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


def _tools(db_session, user_id=BOOTSTRAP_USER_ID, *, approved: bool = False) -> DomainToolService:
    return DomainToolService(
        db_session,
        user_id,
        None,
        defer_write_embeddings=True,
        write_mode=(
            DomainWriteMode.APPROVED_CONFIRMED if approved else DomainWriteMode.AGENT_PROPOSED
        ),
    )


def _count_activities(session, user_id=BOOTSTRAP_USER_ID) -> int:
    return session.scalar(
        select(func.count())
        .select_from(Object)
        .where(Object.user_id == user_id, Object.kind == KIND_SCHEDULED_ACTIVITY)
    )


def _count_run_jobs(session, user_id=BOOTSTRAP_USER_ID) -> int:
    return session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.user_id == user_id, Job.type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY)
    )


def _count_notifications(session, user_id=BOOTSTRAP_USER_ID) -> int:
    return session.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user_id)
    )


def _create_args(**overrides) -> dict:
    payload = {
        "title": "Call the dentist",
        "body": "Bring insurance card",
        "run_at": _future_run_at().isoformat(),
        "priority": "high",
    }
    payload.update(overrides)
    return payload


def _stage_create(db_session, args=None, context=ExecutionContext.INTERACTIVE_ASSISTANT):
    gateway = ToolExecutionGateway()
    return gateway.execute(
        _tools(db_session),
        "create_scheduled_activity",
        args or _create_args(),
        context=context,
    )


def _approve_staged(db_session, staged, user_id=BOOTSTRAP_USER_ID):
    plan = ActionPlanService(db_session, user_id).create_plan([staged.staged_action])
    return ActionPlanService(db_session, user_id).approve(plan.id)


def _persist_user() -> uuid.UUID:
    user_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=user_id, display_name=f"psa-{user_id}"))
        session.commit()
    return user_id


def _persist_activity(
    user_id: uuid.UUID,
    *,
    run_at: datetime | None = None,
    title: str = "Persisted reminder",
    body: str | None = "Details",
    priority: str = "urgent",
) -> tuple[uuid.UUID, uuid.UUID, datetime]:
    requested = run_at or _future_run_at()
    create_at = (
        requested
        if requested > datetime.now(UTC)
        else datetime.now(UTC) + timedelta(hours=2)
    )
    with Session(engine) as session:
        graph = GraphService(session, user_id)
        obj = ScheduledActivityService(session, user_id, graph).create_once(
            title=title,
            body=body,
            run_at=create_at,
            priority=priority,
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
        if requested != create_at:
            obj.due_at = requested
            job.run_after = requested
        activity_id, job_id, stored_due = obj.id, job.id, obj.due_at
        session.commit()
    return activity_id, job_id, stored_due


def _load(model, entity_id):
    with Session(engine) as session:
        row = session.get(model, entity_id)
        if row is not None:
            session.expunge(row)
        return row


def _cleanup_user(user_id: uuid.UUID) -> None:
    with Session(engine) as session:
        session.execute(delete(Notification).where(Notification.user_id == user_id))
        session.execute(delete(Job).where(Job.user_id == user_id))
        session.execute(delete(Object).where(Object.user_id == user_id))
        session.execute(delete(User).where(User.id == user_id))
        session.commit()


def _notification_count(user_id: uuid.UUID) -> int:
    with Session(engine) as session:
        return session.scalar(
            select(func.count()).select_from(Notification).where(Notification.user_id == user_id)
        )


def _commit(work):
    with Session(engine) as session:
        result = work(session)
        session.commit()
        return result


def _drain_until_job(job_id: uuid.UUID, *, limit: int = 20) -> Job:
    for _ in range(limit):
        stored = _load(Job, job_id)
        assert stored is not None
        if stored.status == JOB_STATUS_DONE:
            return stored
        processed = process_one_job()
        if not processed:
            return _load(Job, job_id)
    raise AssertionError("job did not settle")


def test_run_scheduled_activity_is_not_recurring_source_job() -> None:
    assert JOB_TYPE_RUN_SCHEDULED_ACTIVITY not in RECURRING_SOURCE_JOB_TYPES
    assert TOOL_REGISTRY["create_scheduled_activity"].permission == ToolPermission.INTERNAL_WRITE
    assert TOOL_REGISTRY["cancel_scheduled_activity"].permission == ToolPermission.INTERNAL_WRITE
    assert TOOL_REGISTRY["create_scheduled_activity"].prepare_method == (
        "prepare_create_scheduled_activity"
    )


def test_interactive_create_requires_approval_without_object_or_job(db_session) -> None:
    before_objects = _count_activities(db_session)
    before_jobs = _count_run_jobs(db_session)
    result = _stage_create(db_session)
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert _count_activities(db_session) == before_objects
    assert _count_run_jobs(db_session) == before_jobs
    args = result.staged_action["arguments"]
    assert args["title"] == "Call the dentist"
    assert args["body"] == "Bring insurance card"
    assert args["priority"] == "high"
    assert "run_at" in args
    assert "schedule_kind" not in args
    assert set(args) <= {"title", "body", "run_at", "priority"}
    assert "job" not in str(args).lower()
    assert "activity_id" not in args
    public = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan(
        [result.staged_action]
    )
    shown = public.actions[0]["arguments"]
    assert shown["title"] == "Call the dentist"
    assert shown["body"] == "Bring insurance card"
    assert "run_at" in shown
    assert shown["priority"] == "high"
    assert "schedule_kind" not in shown
    assert set(shown) <= {"title", "body", "run_at", "priority"}
    assert "job_id" not in shown
    assert "activity_id" not in shown


def test_rejected_action_plan_creates_nothing(db_session) -> None:
    staged = _stage_create(db_session)
    plan = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan([staged.staged_action])
    ActionPlanService(db_session, BOOTSTRAP_USER_ID).reject(plan.id)
    assert _count_activities(db_session) == 0
    assert _count_run_jobs(db_session) == 0
    assert _count_notifications(db_session) == 0


@pytest.mark.asyncio
async def test_mcp_create_and_cancel_fail_closed(db_session, mcp_server) -> None:
    from mcp.client import Client

    before_objects = _count_activities(db_session)
    before_jobs = _count_run_jobs(db_session)
    async with Client(mcp_server) as client:
        created = await client.call_tool(
            "create_scheduled_activity",
            {
                "title": "MCP reminder",
                "run_at": _future_run_at().isoformat(),
            },
        )
        cancelled = await client.call_tool(
            "cancel_scheduled_activity",
            {"activity_id": str(uuid.uuid4())},
        )
    assert created.is_error
    assert "approval" in created.content[0].text.lower()
    assert cancelled.is_error
    assert "approval" in cancelled.content[0].text.lower()
    assert _count_activities(db_session) == before_objects
    assert _count_run_jobs(db_session) == before_jobs


def test_approved_create_persists_object_and_job(db_session) -> None:
    staged = _stage_create(db_session)
    frozen_run_at = datetime.fromisoformat(staged.staged_action["arguments"]["run_at"])
    view = _approve_staged(db_session, staged)
    assert view.status == "executed"
    activities = list(
        db_session.scalars(
            select(Object).where(
                Object.user_id == BOOTSTRAP_USER_ID,
                Object.kind == KIND_SCHEDULED_ACTIVITY,
            )
        )
    )
    assert len(activities) == 1
    activity = activities[0]
    assert activity.status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
    assert activity.title == "Call the dentist"
    assert activity.body == "Bring insurance card"
    assert activity.due_at == frozen_run_at
    assert activity.metadata_[METADATA_SCHEDULE_KIND] == SCHEDULE_KIND_ONCE
    assert activity.metadata_[METADATA_PRIORITY] == "high"
    jobs = list(
        db_session.scalars(
            select(Job).where(
                Job.user_id == BOOTSTRAP_USER_ID,
                Job.type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
            )
        )
    )
    assert len(jobs) == 1
    assert jobs[0].payload == {"activity_id": str(activity.id)}
    assert jobs[0].run_after == frozen_run_at
    assert jobs[0].status == JOB_STATUS_PENDING


def test_query_objects_lists_scheduled_activities(db_session) -> None:
    staged = _stage_create(db_session)
    _approve_staged(db_session, staged)
    listed = _tools(db_session).query_objects(
        QueryObjectsInput(
            kinds=[KIND_SCHEDULED_ACTIVITY],
            statuses=[SCHEDULED_ACTIVITY_STATUS_SCHEDULED],
            sort_by="due_at",
            sort_order="asc",
        )
    )
    assert len(listed.objects) == 1
    assert listed.objects[0].kind == KIND_SCHEDULED_ACTIVITY
    assert listed.objects[0].title == "Call the dentist"


def test_past_run_at_is_rejected(db_session) -> None:
    result = _stage_create(
        db_session,
        _create_args(run_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat()),
    )
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert "past" in (result.error or "")
    assert _count_activities(db_session) == 0
    assert _count_run_jobs(db_session) == 0


def test_future_job_is_not_claimed_before_run_after() -> None:
    user_id = _persist_user()
    try:
        activity_id, job_id, due = _persist_activity(user_id, run_at=_future_run_at(hours=6))
        with Session(engine) as session:
            claimed = JobQueueService(session).claim_next()
            session.rollback()
        if claimed is not None and claimed.id == job_id:
            raise AssertionError("future scheduled job was claimed early")
        stored = _load(Job, job_id)
        assert stored.status == JOB_STATUS_PENDING
        assert stored.run_after == due
        assert _load(Object, activity_id).status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
        assert _notification_count(user_id) == 0
    finally:
        _cleanup_user(user_id)


def test_worker_fires_once_with_exact_notification() -> None:
    user_id = _persist_user()
    try:
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, _ = _persist_activity(
            user_id,
            run_at=due,
            title="Wake up",
            body="Stand up",
            priority="urgent",
        )
        stored = _drain_until_job(job_id)
        assert stored.status == JOB_STATUS_DONE
        with Session(engine) as session:
            notes = list(
                session.scalars(select(Notification).where(Notification.user_id == user_id))
            )
            activity = session.get(Object, activity_id)
            assert len(notes) == 1
            note = notes[0]
            assert note.title == "Wake up"
            assert note.body == "Stand up"
            assert note.priority == "urgent"
            assert note.source_object_id == activity_id
            assert note.proposal_ == {
                "type": "scheduled_activity",
                "activity_id": str(activity_id),
            }
            assert activity.status == SCHEDULED_ACTIVITY_STATUS_COMPLETED
            assert activity.occurred_at is not None
    finally:
        _cleanup_user(user_id)


def test_repeated_handler_does_not_duplicate_notification() -> None:
    user_id = _persist_user()
    try:
        activity_id, job_id, _ = _persist_activity(
            user_id, run_at=datetime.now(UTC) - timedelta(seconds=1)
        )
        _drain_until_job(job_id)
        _commit(
            lambda session: handle_run_scheduled_activity(
                session, None, {"activity_id": str(activity_id)}, user_id
            )
        )
        assert _notification_count(user_id) == 1
    finally:
        _cleanup_user(user_id)


def test_handler_rollback_then_retry_creates_one_notification(monkeypatch) -> None:
    user_id = _persist_user()
    original = NotificationService.create

    def boom(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("simulated failure after notification")

    try:
        activity_id, job_id, _ = _persist_activity(
            user_id, run_at=datetime.now(UTC) - timedelta(seconds=1)
        )
        monkeypatch.setattr(NotificationService, "create", boom)
        with Session(engine) as session:
            with pytest.raises(RuntimeError, match="simulated failure"):
                handle_run_scheduled_activity(
                    session, None, {"activity_id": str(activity_id)}, user_id
                )
            session.rollback()
        activity = _load(Object, activity_id)
        assert activity.status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
        assert _notification_count(user_id) == 0
        monkeypatch.setattr(NotificationService, "create", original)
        _drain_until_job(job_id)
        assert _notification_count(user_id) == 1
        assert _load(Object, activity_id).status == SCHEDULED_ACTIVITY_STATUS_COMPLETED
    finally:
        _cleanup_user(user_id)


def test_overdue_job_fires_after_simulated_restart() -> None:
    user_id = _persist_user()
    try:
        past = datetime.now(UTC) - timedelta(hours=3)
        activity_id, job_id, _ = _persist_activity(user_id, run_at=past)
        stored = _drain_until_job(job_id)
        assert stored.status == JOB_STATUS_DONE
        assert _notification_count(user_id) == 1
        assert _load(Object, activity_id).status == SCHEDULED_ACTIVITY_STATUS_COMPLETED
    finally:
        _cleanup_user(user_id)


def test_cancel_before_due_requires_approval_and_blocks_notification(db_session) -> None:
    staged = _stage_create(db_session)
    _approve_staged(db_session, staged)
    activity = db_session.scalar(
        select(Object).where(Object.kind == KIND_SCHEDULED_ACTIVITY)
    )
    gateway = ToolExecutionGateway()
    cancel = gateway.execute(
        _tools(db_session),
        "cancel_scheduled_activity",
        {"activity_id": str(activity.id)},
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    assert cancel.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert activity.status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
    plan = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan([cancel.staged_action])
    view = ActionPlanService(db_session, BOOTSTRAP_USER_ID).approve(plan.id)
    assert view.status == "executed"
    db_session.refresh(activity)
    assert activity.status == SCHEDULED_ACTIVITY_STATUS_CANCELLED
    output = view.result["actions"][0]["output"]
    assert output["changed"] is True
    job = db_session.scalar(
        select(Job).where(Job.type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY)
    )
    assert job.status == JOB_STATUS_DONE
    handle_run_scheduled_activity(
        db_session, None, {"activity_id": str(activity.id)}, BOOTSTRAP_USER_ID
    )
    assert _count_notifications(db_session) == 0


def test_cancel_twice_is_idempotent(db_session) -> None:
    staged = _stage_create(db_session)
    _approve_staged(db_session, staged)
    activity = db_session.scalar(select(Object).where(Object.kind == KIND_SCHEDULED_ACTIVITY))
    gateway = ToolExecutionGateway()
    first = gateway.execute(
        _tools(db_session, approved=True),
        "cancel_scheduled_activity",
        {"activity_id": str(activity.id)},
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    second = gateway.execute(
        _tools(db_session, approved=True),
        "cancel_scheduled_activity",
        {"activity_id": str(activity.id)},
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert first.success is True
    assert first.output["changed"] is True
    assert second.success is True
    assert second.output["changed"] is False
    assert second.output["status"] == SCHEDULED_ACTIVITY_STATUS_CANCELLED


def test_cancel_completed_does_not_pretend_undo(db_session) -> None:
    staged = _stage_create(db_session)
    _approve_staged(db_session, staged)
    activity = db_session.scalar(select(Object).where(Object.kind == KIND_SCHEDULED_ACTIVITY))
    handle_run_scheduled_activity(
        db_session, None, {"activity_id": str(activity.id)}, BOOTSTRAP_USER_ID
    )
    db_session.refresh(activity)
    assert activity.status == SCHEDULED_ACTIVITY_STATUS_COMPLETED
    result = ToolExecutionGateway().execute(
        _tools(db_session, approved=True),
        "cancel_scheduled_activity",
        {"activity_id": str(activity.id)},
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert result.success is True
    assert result.output["changed"] is False
    assert result.output["status"] == SCHEDULED_ACTIVITY_STATUS_COMPLETED
    db_session.refresh(activity)
    assert activity.status == SCHEDULED_ACTIVITY_STATUS_COMPLETED


def test_cancel_foreign_and_wrong_kind_fail_closed(db_session, nornickel_user_id) -> None:
    staged = _stage_create(db_session)
    _approve_staged(db_session, staged)
    activity = db_session.scalar(select(Object).where(Object.kind == KIND_SCHEDULED_ACTIVITY))
    foreign = ToolExecutionGateway().execute(
        _tools(db_session, nornickel_user_id, approved=True),
        "cancel_scheduled_activity",
        {"activity_id": str(activity.id)},
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert foreign.success is False
    task = GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="task", title="Not an activity", origin="user")
    )
    wrong = ToolExecutionGateway().execute(
        _tools(db_session, approved=True),
        "cancel_scheduled_activity",
        {"activity_id": str(task.id)},
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert wrong.success is False
    assert "scheduled_activity" in (wrong.error or "")


def test_tombstoned_activity_does_not_notify() -> None:
    user_id = _persist_user()
    try:
        activity_id, job_id, _ = _persist_activity(
            user_id, run_at=datetime.now(UTC) - timedelta(seconds=1)
        )
        _commit(
            lambda session: tombstone_object(session.get(Object, activity_id))
        )
        _drain_until_job(job_id)
        assert _notification_count(user_id) == 0
    finally:
        _cleanup_user(user_id)


def test_cancel_then_worker_no_notification() -> None:
    user_id = _persist_user()
    try:
        activity_id, job_id, _ = _persist_activity(
            user_id, run_at=datetime.now(UTC) - timedelta(seconds=1)
        )
        _commit(
            lambda session: ScheduledActivityService(
                session, user_id, GraphService(session, user_id)
            ).cancel(activity_id)
        )
        _drain_until_job(job_id)
        assert _notification_count(user_id) == 0
        assert _load(Object, activity_id).status == SCHEDULED_ACTIVITY_STATUS_CANCELLED
    finally:
        _cleanup_user(user_id)


def test_worker_then_cancel_keeps_notification() -> None:
    user_id = _persist_user()
    try:
        activity_id, job_id, _ = _persist_activity(
            user_id, run_at=datetime.now(UTC) - timedelta(seconds=1)
        )
        _drain_until_job(job_id)
        _commit(
            lambda session: ScheduledActivityService(
                session, user_id, GraphService(session, user_id)
            ).cancel(activity_id)
        )
        assert _load(Object, activity_id).status == SCHEDULED_ACTIVITY_STATUS_COMPLETED
        assert _notification_count(user_id) == 1
    finally:
        _cleanup_user(user_id)


def test_foreign_payload_does_not_notify_other_user() -> None:
    owner = _persist_user()
    other = _persist_user()
    try:
        activity_id, _, _ = _persist_activity(
            owner, run_at=datetime.now(UTC) - timedelta(seconds=1)
        )
        _commit(
            lambda session: handle_run_scheduled_activity(
                session, None, {"activity_id": str(activity_id)}, other
            )
        )
        assert _notification_count(owner) == 0
        assert _notification_count(other) == 0
        assert _load(Object, activity_id).status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
    finally:
        _cleanup_user(owner)
        _cleanup_user(other)


def test_handler_source_has_no_llm_or_external_actions() -> None:
    source = inspect.getsource(handle_run_scheduled_activity)
    lowered = source.lower()
    for needle in (
        "openai",
        "llm",
        "assistant",
        "send_email",
        "create_calendar",
        "actionplan",
        "mcp",
    ):
        assert needle not in lowered
    service_source = inspect.getsource(ScheduledActivityService.fire)
    for needle in ("openai", "llm", "send_email", "create_calendar", "mcp"):
        assert needle not in service_source.lower()
