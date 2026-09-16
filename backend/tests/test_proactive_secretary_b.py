"""Proactive Secretary Pass B — recurring schedules, timezone/DST, exactly-once."""

from __future__ import annotations

import inspect
import threading
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models import Job, Notification, Object, User
from app.domain.object_visibility import tombstone_object
from app.domain.recurrence import (
    RecurrenceSpec,
    as_utc,
    instant_to_iso,
    next_occurrence,
    same_instant,
)
from app.domain.scheduled_activity import (
    KIND_SCHEDULED_ACTIVITY,
    METADATA_LOCAL_TIME,
    METADATA_SCHEDULE_KIND,
    METADATA_TIMEZONE,
    METADATA_WEEKDAYS,
    SCHEDULE_KIND_DAILY,
    SCHEDULE_KIND_ONCE,
    SCHEDULE_KIND_WEEKLY,
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
from app.services.assistant_service import AssistantService
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

CLIENT_TZ = "Europe/Moscow"


@pytest.fixture
def mcp_server(patched_mcp_tool_session):
    from app.mcp.server import create_mcp_server

    return create_mcp_server()


def _tools(db_session, user_id=BOOTSTRAP_USER_ID, *, approved: bool = False) -> DomainToolService:
    return DomainToolService(
        db_session,
        user_id,
        None,
        defer_write_embeddings=True,
        client_timezone=CLIENT_TZ,
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


def _count_run_jobs(session, user_id=BOOTSTRAP_USER_ID, *, pending_only: bool = False) -> int:
    stmt = select(func.count()).select_from(Job).where(
        Job.user_id == user_id, Job.type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY
    )
    if pending_only:
        stmt = stmt.where(Job.status == JOB_STATUS_PENDING)
    return session.scalar(stmt)


def _count_notifications(session, user_id=BOOTSTRAP_USER_ID) -> int:
    return session.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user_id)
    )


def _daily_args(**overrides) -> dict:
    payload = {
        "title": "Morning standup",
        "body": "Open the notes",
        "schedule_kind": "daily",
        "local_time": "09:30",
        "timezone": CLIENT_TZ,
        "priority": "high",
    }
    payload.update(overrides)
    return payload


def _weekly_args(**overrides) -> dict:
    payload = {
        "title": "Weekly review",
        "body": "Write the summary",
        "schedule_kind": "weekly",
        "local_time": "10:00",
        "timezone": CLIENT_TZ,
        "weekdays": ["fri", "mon", "wed"],
        "priority": "normal",
    }
    payload.update(overrides)
    return payload


def _stage(db_session, args=None, context=ExecutionContext.INTERACTIVE_ASSISTANT):
    return ToolExecutionGateway().execute(
        _tools(db_session),
        "create_recurring_scheduled_activity",
        args or _daily_args(),
        context=context,
    )


def _approve_staged(db_session, staged, user_id=BOOTSTRAP_USER_ID):
    plan = ActionPlanService(db_session, user_id).create_plan([staged.staged_action])
    return ActionPlanService(db_session, user_id).approve(plan.id), plan


def _persist_user() -> uuid.UUID:
    user_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=user_id, display_name=f"psb-{user_id}"))
        session.commit()
    return user_id


def _spec_daily(
    local_time: str = "09:30",
    timezone: str = CLIENT_TZ,
) -> RecurrenceSpec:
    return RecurrenceSpec(
        schedule_kind="daily",
        timezone=timezone,
        local_time=local_time,
    )


def _spec_weekly(
    local_time: str = "10:00",
    timezone: str = CLIENT_TZ,
    weekdays: tuple[str, ...] = ("mon", "wed", "fri"),
) -> RecurrenceSpec:
    return RecurrenceSpec(
        schedule_kind="weekly",
        timezone=timezone,
        local_time=local_time,
        weekdays=weekdays,
    )


def _persist_recurring(
    user_id: uuid.UUID,
    spec: RecurrenceSpec,
    *,
    due_at: datetime | None = None,
    title: str = "Persisted recurring",
    body: str | None = "Details",
    priority: str = "urgent",
) -> tuple[uuid.UUID, uuid.UUID, datetime]:
    first = next_occurrence(spec, datetime.now(UTC))
    with Session(engine) as session:
        graph = GraphService(session, user_id)
        obj = ScheduledActivityService(session, user_id, graph).create_recurring(
            title=title,
            body=body,
            spec=spec,
            run_at=first,
            priority=priority,
            origin_state="confirmed",
            confidence=None,
            enqueue_embedding=False,
        )
        job = session.scalars(
            select(Job).where(
                Job.user_id == user_id,
                Job.type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
            )
        )
        matched = next(
            (
                row
                for row in job
                if (row.payload or {}).get("activity_id") == str(obj.id)
            ),
            None,
        )
        assert matched is not None
        stored_due = first
        if due_at is not None:
            obj.due_at = due_at
            matched.run_after = due_at
            payload = dict(matched.payload or {})
            payload["occurrence_due_at"] = instant_to_iso(due_at)
            matched.payload = payload
            stored_due = due_at
        activity_id, job_id = obj.id, matched.id
        session.commit()
    return activity_id, job_id, stored_due


def _persist_once(
    user_id: uuid.UUID,
    *,
    due_at: datetime | None = None,
    title: str = "Persisted once",
) -> tuple[uuid.UUID, uuid.UUID, datetime]:
    create_at = datetime.now(UTC) + timedelta(hours=2)
    with Session(engine) as session:
        graph = GraphService(session, user_id)
        obj = ScheduledActivityService(session, user_id, graph).create_once(
            title=title,
            body="Once body",
            run_at=create_at,
            priority="normal",
            origin_state="confirmed",
            confidence=None,
            enqueue_embedding=False,
        )
        job = session.scalars(
            select(Job).where(
                Job.user_id == user_id,
                Job.type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
            )
        )
        matched = next(
            (
                row
                for row in job
                if (row.payload or {}).get("activity_id") == str(obj.id)
            ),
            None,
        )
        assert matched is not None
        stored_due = create_at
        if due_at is not None:
            obj.due_at = due_at
            matched.run_after = due_at
            stored_due = due_at
        activity_id, job_id = obj.id, matched.id
        session.commit()
    return activity_id, job_id, stored_due


def _patch_metadata(activity_id: uuid.UUID, updater) -> None:
    with Session(engine) as session:
        obj = session.get(Object, activity_id)
        assert obj is not None
        metadata = dict(obj.metadata_ or {})
        updater(metadata)
        obj.metadata_ = metadata
        session.commit()


def _patch_job_payload(job_id: uuid.UUID, updater) -> None:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        payload = dict(job.payload or {})
        updater(payload)
        job.payload = payload
        session.commit()


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


def _pending_run_jobs(user_id: uuid.UUID) -> list[Job]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(Job).where(
                    Job.user_id == user_id,
                    Job.type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
                    Job.status == JOB_STATUS_PENDING,
                )
            )
        )
        for row in rows:
            session.expunge(row)
        return rows


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


def test_recurring_job_type_is_not_source_sync() -> None:
    assert JOB_TYPE_RUN_SCHEDULED_ACTIVITY not in RECURRING_SOURCE_JOB_TYPES
    spec = TOOL_REGISTRY["create_recurring_scheduled_activity"]
    assert spec.permission == ToolPermission.INTERNAL_WRITE
    assert spec.prepare_method == "prepare_create_recurring_scheduled_activity"
    assert spec.assistant_exposed is True
    assert spec.mcp_exposed is True


def test_interactive_recurring_create_requires_approval_without_object_or_job(db_session) -> None:
    before_objects = _count_activities(db_session)
    before_jobs = _count_run_jobs(db_session)
    result = _stage(db_session)
    assert result.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert _count_activities(db_session) == before_objects
    assert _count_run_jobs(db_session) == before_jobs
    args = result.staged_action["arguments"]
    assert args["title"] == "Morning standup"
    assert args["body"] == "Open the notes"
    assert args["schedule_kind"] == "daily"
    assert args["local_time"] == "09:30"
    assert args["timezone"] == CLIENT_TZ
    assert args["priority"] == "high"
    assert "run_at" in args
    assert "weekdays" not in args
    assert "occurrence_due_at" not in args
    assert "activity_id" not in args
    assert "job" not in str(args).lower()
    public = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan([result.staged_action])
    shown = public.actions[0]["arguments"]
    assert shown["schedule_kind"] == "daily"
    assert shown["local_time"] == "09:30"
    assert shown["timezone"] == CLIENT_TZ
    assert "run_at" in shown
    assert "weekdays" not in shown
    assert "occurrence_due_at" not in shown
    assert "activity_id" not in shown
    assert "job_id" not in shown


def test_rejected_recurring_plan_creates_nothing(db_session) -> None:
    staged = _stage(db_session)
    plan = ActionPlanService(db_session, BOOTSTRAP_USER_ID).create_plan([staged.staged_action])
    ActionPlanService(db_session, BOOTSTRAP_USER_ID).reject(plan.id)
    assert _count_activities(db_session) == 0
    assert _count_run_jobs(db_session) == 0
    assert _count_notifications(db_session) == 0


@pytest.mark.asyncio
async def test_mcp_recurring_create_fail_closed(db_session, mcp_server) -> None:
    from mcp.client import Client

    before_objects = _count_activities(db_session)
    before_jobs = _count_run_jobs(db_session)
    async with Client(mcp_server) as client:
        created = await client.call_tool(
            "create_recurring_scheduled_activity",
            {
                "title": "MCP daily",
                "schedule_kind": "daily",
                "local_time": "08:00",
            },
        )
    assert created.is_error
    assert "approval" in created.content[0].text.lower()
    assert _count_activities(db_session) == before_objects
    assert _count_run_jobs(db_session) == before_jobs


def test_approved_daily_persists_object_and_fenced_job(db_session) -> None:
    staged = _stage(db_session)
    frozen_run_at = datetime.fromisoformat(staged.staged_action["arguments"]["run_at"])
    view, _ = _approve_staged(db_session, staged)
    assert view.status == "executed"
    activity = db_session.scalar(
        select(Object).where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.kind == KIND_SCHEDULED_ACTIVITY,
        )
    )
    assert activity is not None
    assert activity.status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
    assert activity.metadata_[METADATA_SCHEDULE_KIND] == SCHEDULE_KIND_DAILY
    assert activity.metadata_[METADATA_TIMEZONE] == CLIENT_TZ
    assert activity.metadata_[METADATA_LOCAL_TIME] == "09:30"
    assert METADATA_WEEKDAYS not in activity.metadata_
    assert same_instant(activity.due_at, frozen_run_at)
    jobs = list(
        db_session.scalars(
            select(Job).where(
                Job.user_id == BOOTSTRAP_USER_ID,
                Job.type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
            )
        )
    )
    assert len(jobs) == 1
    assert jobs[0].payload["activity_id"] == str(activity.id)
    assert same_instant(
        datetime.fromisoformat(jobs[0].payload["occurrence_due_at"]),
        frozen_run_at,
    )
    assert jobs[0].run_after == activity.due_at
    assert jobs[0].status == JOB_STATUS_PENDING


def test_approved_weekly_canonicalizes_weekdays_and_first_run(db_session) -> None:
    staged = _stage(db_session, _weekly_args())
    args = staged.staged_action["arguments"]
    assert args["weekdays"] == ["mon", "wed", "fri"]
    frozen_run_at = datetime.fromisoformat(args["run_at"])
    view, _ = _approve_staged(db_session, staged)
    assert view.status == "executed"
    activity = db_session.scalar(
        select(Object).where(Object.kind == KIND_SCHEDULED_ACTIVITY)
    )
    assert activity.metadata_[METADATA_SCHEDULE_KIND] == SCHEDULE_KIND_WEEKLY
    assert activity.metadata_[METADATA_WEEKDAYS] == ["mon", "wed", "fri"]
    assert same_instant(activity.due_at, frozen_run_at)
    expected = next_occurrence(_spec_weekly(), datetime.now(UTC) - timedelta(seconds=2))
    assert activity.due_at.astimezone(ZoneInfo(CLIENT_TZ)).weekday() in {0, 2, 4}
    assert abs((as_utc(activity.due_at) - as_utc(expected)).total_seconds()) < 3


def test_repeat_approve_does_not_duplicate(db_session) -> None:
    staged = _stage(db_session)
    view, plan = _approve_staged(db_session, staged)
    assert view.status == "executed"
    repeated = ActionPlanService(db_session, BOOTSTRAP_USER_ID).approve(plan.id)
    assert repeated.status == "executed"
    assert _count_activities(db_session) == 1
    assert _count_run_jobs(db_session) == 1


def test_assistant_resume_does_not_re_execute_recurring_mutation() -> None:
    source = inspect.getsource(AssistantService.finalize_executed_plan)
    traced = inspect.getsource(AssistantService._finalize_executed_plan_traced)
    combined = source + traced
    assert "create_recurring_scheduled_activity" not in combined
    assert "run_text_only" in traced
    assert "DomainToolService" not in combined


def test_invalid_timezone_fail_closed(db_session) -> None:
    result = _stage(db_session, _daily_args(timezone="+03:00"))
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert _count_activities(db_session) == 0
    assert _count_run_jobs(db_session) == 0


def test_invalid_local_time_fail_closed(db_session) -> None:
    for value in ("9:30", "24:00", "09:30:00", "25:00"):
        result = _stage(db_session, _daily_args(local_time=value))
        assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert _count_activities(db_session) == 0


def test_weekly_without_weekdays_fail_closed(db_session) -> None:
    args = _weekly_args()
    args.pop("weekdays")
    result = _stage(db_session, args)
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert _count_activities(db_session) == 0


def test_daily_with_weekdays_fail_closed(db_session) -> None:
    result = _stage(db_session, _daily_args(weekdays=["mon"]))
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert _count_activities(db_session) == 0


def test_duplicate_weekdays_are_rejected(db_session) -> None:
    result = _stage(db_session, _weekly_args(weekdays=["mon", "mon"]))
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert _count_activities(db_session) == 0


def test_frozen_first_run_becoming_past_fails_closed(db_session, monkeypatch) -> None:
    staged = _stage(db_session)
    frozen = datetime.fromisoformat(staged.staged_action["arguments"]["run_at"])
    monkeypatch.setattr(
        "app.services.scheduled_activity_service.utcnow",
        lambda: as_utc(frozen) + timedelta(seconds=1),
    )
    view, _ = _approve_staged(db_session, staged)
    assert view.status == "failed"
    assert _count_activities(db_session) == 0
    assert _count_run_jobs(db_session) == 0


def test_omitted_timezone_uses_client_iana_zone(db_session) -> None:
    args = _daily_args()
    args.pop("timezone")
    staged = _stage(db_session, args)
    assert staged.status == ToolExecutionStatus.APPROVAL_REQUIRED
    assert staged.staged_action["arguments"]["timezone"] == CLIENT_TZ


def test_daily_due_occurrence_rearms_without_completing() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily()
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, stored_due = _persist_recurring(user_id, spec, due_at=due)
        stored = _drain_until_job(job_id)
        assert stored.status == JOB_STATUS_DONE
        activity = _load(Object, activity_id)
        assert activity.status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
        assert activity.occurred_at is not None
        assert as_utc(activity.due_at) > datetime.now(UTC)
        expected_next = next_occurrence(spec, activity.occurred_at)
        assert same_instant(activity.due_at, expected_next)
        notes = None
        with Session(engine) as session:
            notes = list(session.scalars(select(Notification).where(Notification.user_id == user_id)))
        assert len(notes) == 1
        assert notes[0].title == "Persisted recurring"
        assert notes[0].proposal_["type"] == "scheduled_activity"
        assert notes[0].proposal_["activity_id"] == str(activity_id)
        assert same_instant(
            datetime.fromisoformat(notes[0].proposal_["scheduled_for"]),
            stored_due,
        )
        successors = _pending_run_jobs(user_id)
        assert len(successors) == 1
        assert successors[0].run_after == activity.due_at
        assert same_instant(
            datetime.fromisoformat(successors[0].payload["occurrence_due_at"]),
            activity.due_at,
        )
    finally:
        _cleanup_user(user_id)


def test_weekly_fire_advances_to_next_selected_weekday() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_weekly(weekdays=("mon", "thu"))
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, _ = _persist_recurring(user_id, spec, due_at=due)
        _drain_until_job(job_id)
        activity = _load(Object, activity_id)
        assert activity.status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
        nxt_local = as_utc(activity.due_at).astimezone(ZoneInfo(CLIENT_TZ))
        assert nxt_local.strftime("%a").lower()[:3] in {"mon", "thu"}
        assert same_instant(activity.due_at, next_occurrence(spec, activity.occurred_at))
        assert _notification_count(user_id) == 1
    finally:
        _cleanup_user(user_id)


def test_stale_occurrence_job_is_noop() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily()
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, stored_due = _persist_recurring(user_id, spec, due_at=due)
        _drain_until_job(job_id)
        _commit(
            lambda session: handle_run_scheduled_activity(
                session,
                None,
                {
                    "activity_id": str(activity_id),
                    "occurrence_due_at": instant_to_iso(stored_due),
                },
                user_id,
            )
        )
        assert _notification_count(user_id) == 1
        assert len(_pending_run_jobs(user_id)) == 1
    finally:
        _cleanup_user(user_id)


def test_duplicate_same_occurrence_jobs_create_one_notification() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily()
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, stored_due = _persist_recurring(user_id, spec, due_at=due)
        payload = {
            "activity_id": str(activity_id),
            "occurrence_due_at": instant_to_iso(stored_due),
        }
        with Session(engine) as session:
            JobQueueService(session).enqueue(
                JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
                payload,
                user_id=user_id,
                run_after=due,
            )
            session.commit()
        errors: list[Exception] = []

        def worker() -> None:
            try:
                with Session(engine) as session:
                    handle_run_scheduled_activity(session, None, payload, user_id)
                    session.commit()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert _notification_count(user_id) == 1
        activity = _load(Object, activity_id)
        successors = [
            job
            for job in _pending_run_jobs(user_id)
            if same_instant(
                datetime.fromisoformat(str(job.payload.get("occurrence_due_at"))),
                activity.due_at,
            )
        ]
        assert len(successors) == 1
        _drain_until_job(job_id)
    finally:
        _cleanup_user(user_id)


def test_rollback_after_notification_then_retry(monkeypatch) -> None:
    user_id = _persist_user()
    original = NotificationService.create

    def boom(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("simulated failure after notification")

    try:
        spec = _spec_daily()
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, stored_due = _persist_recurring(user_id, spec, due_at=due)
        monkeypatch.setattr(NotificationService, "create", boom)
        with Session(engine) as session:
            with pytest.raises(RuntimeError, match="simulated failure"):
                handle_run_scheduled_activity(
                    session,
                    None,
                    {
                        "activity_id": str(activity_id),
                        "occurrence_due_at": instant_to_iso(stored_due),
                    },
                    user_id,
                )
            session.rollback()
        activity = _load(Object, activity_id)
        assert activity.status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
        assert same_instant(activity.due_at, stored_due)
        assert _notification_count(user_id) == 0
        monkeypatch.setattr(NotificationService, "create", original)
        _drain_until_job(job_id)
        assert _notification_count(user_id) == 1
        assert len(_pending_run_jobs(user_id)) == 1
        assert _load(Object, activity_id).status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
    finally:
        _cleanup_user(user_id)


def test_rollback_after_successor_enqueue_then_retry(monkeypatch) -> None:
    user_id = _persist_user()
    original = JobQueueService.enqueue

    def boom(self, job_type, payload, user_id, run_after=None):
        job = original(self, job_type, payload, user_id, run_after)
        if job_type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY and payload.get("occurrence_due_at"):
            raise RuntimeError("simulated failure after successor enqueue")
        return job

    try:
        spec = _spec_daily()
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, stored_due = _persist_recurring(user_id, spec, due_at=due)
        monkeypatch.setattr(JobQueueService, "enqueue", boom)
        with Session(engine) as session:
            with pytest.raises(RuntimeError, match="simulated failure"):
                handle_run_scheduled_activity(
                    session,
                    None,
                    {
                        "activity_id": str(activity_id),
                        "occurrence_due_at": instant_to_iso(stored_due),
                    },
                    user_id,
                )
            session.rollback()
        assert _notification_count(user_id) == 0
        assert same_instant(_load(Object, activity_id).due_at, stored_due)
        monkeypatch.setattr(JobQueueService, "enqueue", original)
        _drain_until_job(job_id)
        assert _notification_count(user_id) == 1
        assert len(_pending_run_jobs(user_id)) == 1
    finally:
        _cleanup_user(user_id)


def test_overdue_one_period_emits_one_notification() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily("09:00")
        due = datetime.now(UTC) - timedelta(hours=3)
        activity_id, job_id, _ = _persist_recurring(user_id, spec, due_at=due)
        _drain_until_job(job_id)
        assert _notification_count(user_id) == 1
        activity = _load(Object, activity_id)
        assert as_utc(activity.due_at) > datetime.now(UTC)
        assert same_instant(activity.due_at, next_occurrence(spec, activity.occurred_at))
    finally:
        _cleanup_user(user_id)


def test_overdue_several_daily_periods_coalesce() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily("09:00")
        due = datetime.now(UTC) - timedelta(days=5)
        activity_id, job_id, old_due = _persist_recurring(user_id, spec, due_at=due)
        _drain_until_job(job_id)
        assert _notification_count(user_id) == 1
        activity = _load(Object, activity_id)
        now = datetime.now(UTC)
        assert as_utc(activity.due_at) > now
        assert as_utc(activity.due_at) != as_utc(old_due) + timedelta(days=1)
        assert same_instant(activity.due_at, next_occurrence(spec, activity.occurred_at))
    finally:
        _cleanup_user(user_id)


def test_overdue_weekly_coalesces_across_weeks() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_weekly("09:00", weekdays=("mon",))
        due = datetime.now(UTC) - timedelta(days=21)
        activity_id, job_id, _ = _persist_recurring(user_id, spec, due_at=due)
        _drain_until_job(job_id)
        assert _notification_count(user_id) == 1
        activity = _load(Object, activity_id)
        assert as_utc(activity.due_at) > datetime.now(UTC)
        assert as_utc(activity.due_at).astimezone(ZoneInfo(CLIENT_TZ)).weekday() == 0
    finally:
        _cleanup_user(user_id)


def test_dst_spring_forward_rearm_keeps_configured_local_time(monkeypatch) -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily("02:30", timezone="America/New_York")
        due = datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
        activity_id, job_id, _ = _persist_recurring(user_id, spec, due_at=due)
        monkeypatch.setattr(
            "app.services.scheduled_activity_service.utcnow",
            lambda: datetime(2026, 3, 8, 7, 31, tzinfo=UTC),
        )
        _drain_until_job(job_id)
        activity = _load(Object, activity_id)
        assert same_instant(activity.due_at, datetime(2026, 3, 9, 6, 30, tzinfo=UTC))
        local = as_utc(activity.due_at).astimezone(ZoneInfo("America/New_York"))
        assert (local.hour, local.minute) == (2, 30)
        assert _notification_count(user_id) == 1
    finally:
        _cleanup_user(user_id)


def test_query_objects_lists_recurring_scheduled(db_session) -> None:
    staged = _stage(db_session)
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


def test_cancel_before_first_occurrence(db_session) -> None:
    staged = _stage(db_session)
    _approve_staged(db_session, staged)
    activity = db_session.scalar(select(Object).where(Object.kind == KIND_SCHEDULED_ACTIVITY))
    result = ToolExecutionGateway().execute(
        _tools(db_session, approved=True),
        "cancel_scheduled_activity",
        {"activity_id": str(activity.id)},
        context=ExecutionContext.APPROVED_ACTION_PLAN,
    )
    assert result.output["changed"] is True
    db_session.refresh(activity)
    assert activity.status == SCHEDULED_ACTIVITY_STATUS_CANCELLED
    job = db_session.scalar(select(Job).where(Job.type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY))
    assert job.status == JOB_STATUS_DONE
    handle_run_scheduled_activity(
        db_session,
        None,
        {
            "activity_id": str(activity.id),
            "occurrence_due_at": instant_to_iso(activity.due_at),
        },
        BOOTSTRAP_USER_ID,
    )
    assert _count_notifications(db_session) == 0


def test_cancel_after_successful_fire_retires_successor() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily()
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, _ = _persist_recurring(user_id, spec, due_at=due)
        _drain_until_job(job_id)
        assert _notification_count(user_id) == 1
        _commit(
            lambda session: ScheduledActivityService(
                session, user_id, GraphService(session, user_id)
            ).cancel(activity_id)
        )
        assert _load(Object, activity_id).status == SCHEDULED_ACTIVITY_STATUS_CANCELLED
        assert _notification_count(user_id) == 1
        assert _pending_run_jobs(user_id) == []
    finally:
        _cleanup_user(user_id)


def test_repeat_cancel_recurring_is_idempotent(db_session) -> None:
    staged = _stage(db_session)
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
    assert first.output["changed"] is True
    assert second.output["changed"] is False
    assert second.output["status"] == SCHEDULED_ACTIVITY_STATUS_CANCELLED


def test_cancel_then_fire_no_notification() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily()
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, stored_due = _persist_recurring(user_id, spec, due_at=due)
        _commit(
            lambda session: ScheduledActivityService(
                session, user_id, GraphService(session, user_id)
            ).cancel(activity_id)
        )
        _drain_until_job(job_id)
        _commit(
            lambda session: handle_run_scheduled_activity(
                session,
                None,
                {
                    "activity_id": str(activity_id),
                    "occurrence_due_at": instant_to_iso(stored_due),
                },
                user_id,
            )
        )
        assert _notification_count(user_id) == 0
        assert _load(Object, activity_id).status == SCHEDULED_ACTIVITY_STATUS_CANCELLED
    finally:
        _cleanup_user(user_id)


def test_fire_then_cancel_keeps_occurrence_and_retires_future() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily()
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, _ = _persist_recurring(user_id, spec, due_at=due)
        _drain_until_job(job_id)
        _commit(
            lambda session: ScheduledActivityService(
                session, user_id, GraphService(session, user_id)
            ).cancel(activity_id)
        )
        assert _notification_count(user_id) == 1
        assert _load(Object, activity_id).status == SCHEDULED_ACTIVITY_STATUS_CANCELLED
        assert _pending_run_jobs(user_id) == []
    finally:
        _cleanup_user(user_id)


def test_concurrent_fire_and_cancel_invariants() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily()
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, _, stored_due = _persist_recurring(user_id, spec, due_at=due)
        payload = {
            "activity_id": str(activity_id),
            "occurrence_due_at": instant_to_iso(stored_due),
        }
        errors: list[Exception] = []

        def fire_worker() -> None:
            try:
                with Session(engine) as session:
                    handle_run_scheduled_activity(session, None, payload, user_id)
                    session.commit()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def cancel_worker() -> None:
            try:
                with Session(engine) as session:
                    ScheduledActivityService(
                        session, user_id, GraphService(session, user_id)
                    ).cancel(activity_id)
                    session.commit()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=fire_worker), threading.Thread(target=cancel_worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert _load(Object, activity_id).status == SCHEDULED_ACTIVITY_STATUS_CANCELLED
        assert _notification_count(user_id) in {0, 1}
        assert _pending_run_jobs(user_id) == []
    finally:
        _cleanup_user(user_id)


def test_one_shot_legacy_payload_still_completes() -> None:
    user_id = _persist_user()
    try:
        with Session(engine) as session:
            graph = GraphService(session, user_id)
            obj = ScheduledActivityService(session, user_id, graph).create_once(
                title="Once",
                body="Legacy",
                run_at=datetime.now(UTC) + timedelta(hours=2),
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
            obj.due_at = datetime.now(UTC) - timedelta(seconds=1)
            job.run_after = obj.due_at
            activity_id, job_id = obj.id, job.id
            session.commit()
        _drain_until_job(job_id)
        activity = _load(Object, activity_id)
        assert activity.status == SCHEDULED_ACTIVITY_STATUS_COMPLETED
        assert activity.metadata_[METADATA_SCHEDULE_KIND] == SCHEDULE_KIND_ONCE
        assert _notification_count(user_id) == 1
        assert _pending_run_jobs(user_id) == []
        with Session(engine) as session:
            note = session.scalar(select(Notification).where(Notification.user_id == user_id))
            assert "scheduled_for" not in note.proposal_
    finally:
        _cleanup_user(user_id)


def test_one_shot_preview_still_omits_schedule_kind(db_session) -> None:
    result = ToolExecutionGateway().execute(
        _tools(db_session),
        "create_scheduled_activity",
        {
            "title": "Call once",
            "run_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        },
        context=ExecutionContext.INTERACTIVE_ASSISTANT,
    )
    args = result.staged_action["arguments"]
    assert "schedule_kind" not in args
    assert set(args) <= {"title", "body", "run_at", "priority"}


def test_handler_source_has_no_llm_or_external_actions() -> None:
    source = inspect.getsource(handle_run_scheduled_activity)
    service_source = inspect.getsource(ScheduledActivityService.fire)
    recurring_source = inspect.getsource(ScheduledActivityService._fire_recurring)
    combined = (source + service_source + recurring_source).lower()
    for needle in (
        "openai",
        "llm",
        "assistant",
        "send_email",
        "create_calendar",
        "actionplan",
        "mcp",
        "external_action",
    ):
        assert needle not in combined


def _assert_fail_closed(activity_id: uuid.UUID, job_id: uuid.UUID, stored_due: datetime) -> None:
    activity = _load(Object, activity_id)
    assert activity.status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
    assert same_instant(activity.due_at, stored_due)
    assert activity.occurred_at is None
    assert _notification_count(activity.user_id) == 0
    successors = [
        job
        for job in _pending_run_jobs(activity.user_id)
        if job.id != job_id
    ]
    assert successors == []


def test_exact_once_schedule_kind_still_completes() -> None:
    user_id = _persist_user()
    try:
        activity_id, job_id, _ = _persist_once(
            user_id, due_at=datetime.now(UTC) - timedelta(seconds=1)
        )
        assert _load(Object, activity_id).metadata_[METADATA_SCHEDULE_KIND] == SCHEDULE_KIND_ONCE
        _drain_until_job(job_id)
        activity = _load(Object, activity_id)
        assert activity.status == SCHEDULED_ACTIVITY_STATUS_COMPLETED
        assert activity.occurred_at is not None
        assert _notification_count(user_id) == 1
        assert _pending_run_jobs(user_id) == []
    finally:
        _cleanup_user(user_id)


def test_unknown_schedule_kind_monthly_fails_closed() -> None:
    user_id = _persist_user()
    try:
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, stored_due = _persist_once(user_id, due_at=due)
        _patch_metadata(activity_id, lambda meta: meta.__setitem__(METADATA_SCHEDULE_KIND, "monthly"))
        payload = {"activity_id": str(activity_id)}
        with Session(engine) as session:
            with pytest.raises(ValueError, match="unknown schedule_kind"):
                handle_run_scheduled_activity(session, None, payload, user_id)
            session.rollback()
        _assert_fail_closed(activity_id, job_id, stored_due)
        processed = process_one_job()
        assert processed is True
        job = _load(Job, job_id)
        assert job.status != JOB_STATUS_DONE
        assert "unknown schedule_kind" in (job.last_error or "")
        _assert_fail_closed(activity_id, job_id, stored_due)
    finally:
        _cleanup_user(user_id)


def test_missing_schedule_kind_fails_closed() -> None:
    user_id = _persist_user()
    try:
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, stored_due = _persist_once(user_id, due_at=due)
        _patch_metadata(activity_id, lambda meta: meta.pop(METADATA_SCHEDULE_KIND, None))
        payload = {"activity_id": str(activity_id)}
        with Session(engine) as session:
            with pytest.raises(ValueError, match="unknown schedule_kind"):
                handle_run_scheduled_activity(session, None, payload, user_id)
            session.rollback()
        _assert_fail_closed(activity_id, job_id, stored_due)
        assert _load(Object, activity_id).status != SCHEDULED_ACTIVITY_STATUS_COMPLETED
    finally:
        _cleanup_user(user_id)


def test_daily_with_corrupt_recurrence_metadata_fails_closed() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily()
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, stored_due = _persist_recurring(user_id, spec, due_at=due)
        _patch_metadata(activity_id, lambda meta: meta.pop(METADATA_TIMEZONE, None))
        payload = {
            "activity_id": str(activity_id),
            "occurrence_due_at": instant_to_iso(stored_due),
        }
        with Session(engine) as session:
            with pytest.raises(ValueError, match="invalid recurrence metadata"):
                handle_run_scheduled_activity(session, None, payload, user_id)
            session.rollback()
        activity = _load(Object, activity_id)
        assert activity.status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
        assert same_instant(activity.due_at, stored_due)
        assert activity.occurred_at is None
        assert _notification_count(user_id) == 0
        assert len(_pending_run_jobs(user_id)) == 1
        processed = process_one_job()
        assert processed is True
        assert _load(Job, job_id).status != JOB_STATUS_DONE
        assert _notification_count(user_id) == 0
        assert same_instant(_load(Object, activity_id).due_at, stored_due)
        assert len(_pending_run_jobs(user_id)) == 1
    finally:
        _cleanup_user(user_id)


def test_stale_occurrence_fence_is_not_an_error() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily()
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, stored_due = _persist_recurring(user_id, spec, due_at=due)
        _drain_until_job(job_id)
        _commit(
            lambda session: handle_run_scheduled_activity(
                session,
                None,
                {
                    "activity_id": str(activity_id),
                    "occurrence_due_at": instant_to_iso(stored_due),
                },
                user_id,
            )
        )
        assert _notification_count(user_id) == 1
        assert len(_pending_run_jobs(user_id)) == 1
        assert _load(Object, activity_id).status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
    finally:
        _cleanup_user(user_id)


def test_cancelled_completed_tombstoned_remain_noop_even_with_unknown_kind() -> None:
    user_id = _persist_user()
    try:
        due = datetime.now(UTC) - timedelta(seconds=1)
        cancelled_id, _, cancelled_due = _persist_once(user_id, due_at=due, title="C")
        _commit(
            lambda session: ScheduledActivityService(
                session, user_id, GraphService(session, user_id)
            ).cancel(cancelled_id)
        )
        _patch_metadata(cancelled_id, lambda meta: meta.__setitem__(METADATA_SCHEDULE_KIND, "monthly"))
        _commit(
            lambda session: handle_run_scheduled_activity(
                session,
                None,
                {"activity_id": str(cancelled_id), "occurrence_due_at": instant_to_iso(cancelled_due)},
                user_id,
            )
        )
        assert _load(Object, cancelled_id).status == SCHEDULED_ACTIVITY_STATUS_CANCELLED
        assert _notification_count(user_id) == 0

        completed_id, completed_job, _ = _persist_once(
            user_id, due_at=datetime.now(UTC) - timedelta(seconds=1), title="D"
        )
        _drain_until_job(completed_job)
        assert _notification_count(user_id) == 1
        _patch_metadata(completed_id, lambda meta: meta.__setitem__(METADATA_SCHEDULE_KIND, "monthly"))
        _commit(
            lambda session: handle_run_scheduled_activity(
                session, None, {"activity_id": str(completed_id)}, user_id
            )
        )
        assert _load(Object, completed_id).status == SCHEDULED_ACTIVITY_STATUS_COMPLETED
        assert _notification_count(user_id) == 1

        tomb_id, tomb_job, _ = _persist_once(
            user_id, due_at=datetime.now(UTC) - timedelta(seconds=1), title="T"
        )
        _patch_metadata(tomb_id, lambda meta: meta.__setitem__(METADATA_SCHEDULE_KIND, "monthly"))
        _commit(lambda session: tombstone_object(session.get(Object, tomb_id)))
        _drain_until_job(tomb_job)
        assert _notification_count(user_id) == 1
        assert _load(Object, tomb_id).status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
    finally:
        _cleanup_user(user_id)


def _assert_corrupt_occurrence_fence(payload: dict) -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily()
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, stored_due = _persist_recurring(user_id, spec, due_at=due)
        handler_payload = {"activity_id": str(activity_id), **payload}

        def _apply_job_payload(job_payload: dict) -> None:
            job_payload.clear()
            job_payload.update(handler_payload)

        _patch_job_payload(job_id, _apply_job_payload)
        with Session(engine) as session:
            with pytest.raises(ValueError, match="invalid occurrence fence"):
                handle_run_scheduled_activity(session, None, handler_payload, user_id)
            session.rollback()
        activity = _load(Object, activity_id)
        assert activity.status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
        assert same_instant(activity.due_at, stored_due)
        assert activity.occurred_at is None
        assert _notification_count(user_id) == 0
        assert len(_pending_run_jobs(user_id)) == 1
        processed = process_one_job()
        assert processed is True
        job = _load(Job, job_id)
        assert job.status != JOB_STATUS_DONE
        assert "invalid occurrence fence" in (job.last_error or "")
        activity = _load(Object, activity_id)
        assert activity.status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
        assert same_instant(activity.due_at, stored_due)
        assert activity.occurred_at is None
        assert _notification_count(user_id) == 0
        assert len(_pending_run_jobs(user_id)) == 1
    finally:
        _cleanup_user(user_id)


def test_recurring_missing_occurrence_due_at_fails_closed() -> None:
    _assert_corrupt_occurrence_fence({})


def test_recurring_malformed_occurrence_due_at_fails_closed() -> None:
    _assert_corrupt_occurrence_fence({"occurrence_due_at": "not-a-timestamp"})


def test_recurring_naive_occurrence_due_at_fails_closed() -> None:
    _assert_corrupt_occurrence_fence({"occurrence_due_at": "2026-03-08T07:30:00"})


def test_recurring_wrong_type_occurrence_due_at_fails_closed() -> None:
    _assert_corrupt_occurrence_fence({"occurrence_due_at": 123})


def test_valid_mismatched_occurrence_fence_is_safe_noop() -> None:
    user_id = _persist_user()
    try:
        spec = _spec_daily()
        due = datetime.now(UTC) - timedelta(seconds=1)
        activity_id, job_id, stored_due = _persist_recurring(user_id, spec, due_at=due)
        stale = instant_to_iso(as_utc(stored_due) - timedelta(days=1))
        _commit(
            lambda session: handle_run_scheduled_activity(
                session,
                None,
                {"activity_id": str(activity_id), "occurrence_due_at": stale},
                user_id,
            )
        )
        activity = _load(Object, activity_id)
        assert activity.status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED
        assert same_instant(activity.due_at, stored_due)
        assert activity.occurred_at is None
        assert _notification_count(user_id) == 0
        assert len(_pending_run_jobs(user_id)) == 1
        assert _load(Job, job_id).status == JOB_STATUS_PENDING
    finally:
        _cleanup_user(user_id)
