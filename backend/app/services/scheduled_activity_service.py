from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ObjectCreate
from app.db.models import Job, Object
from app.domain.object_visibility import is_object_tombstoned
from app.domain.recurrence import (
    RecurrenceSpec,
    instant_to_iso,
    next_occurrence,
    same_instant,
    spec_from_metadata,
)
from app.domain.scheduled_activity import (
    KIND_SCHEDULED_ACTIVITY,
    METADATA_LOCAL_TIME,
    METADATA_PRIORITY,
    METADATA_SCHEDULE_KIND,
    METADATA_TIMEZONE,
    METADATA_WEEKDAYS,
    NOTIFICATION_PROPOSAL_TYPE,
    RECURRING_SCHEDULE_KINDS,
    SCHEDULE_KIND_ONCE,
    SCHEDULED_ACTIVITY_STATUS_CANCELLED,
    SCHEDULED_ACTIVITY_STATUS_COMPLETED,
    SCHEDULED_ACTIVITY_STATUS_SCHEDULED,
)
from app.jobs.constants import (
    JOB_STATUS_PENDING,
    JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
)
from app.notifications.constants import NOTIFICATION_PRIORITIES
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.job_queue_service import JobQueueService
from app.services.notification_service import NotificationService
from app.services.pipeline_enqueue import enqueue_embed_object
from app.services.provenance import AGENT_ORIGIN
from app.tools.schemas import ToolError


def utcnow() -> datetime:
    return datetime.now(UTC)


def require_future_run_at(run_at: datetime) -> None:
    instant = run_at.astimezone(UTC) if run_at.tzinfo is not None else run_at.replace(tzinfo=UTC)
    if instant < utcnow():
        raise ToolError("run_at is in the past")


def require_occurrence_fence(raw: object) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("scheduled activity has invalid occurrence fence")
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("scheduled activity has invalid occurrence fence") from exc
    if parsed.tzinfo is None:
        raise ValueError("scheduled activity has invalid occurrence fence")
    return parsed.astimezone(UTC)


class ScheduledActivityService:
    def __init__(self, session: Session, user_id: UUID, write_graph: GraphService) -> None:
        self._session = session
        self._user_id = user_id
        self._write_graph = write_graph
        self._jobs = JobQueueService(session)

    def create_once(
        self,
        *,
        title: str,
        body: str | None,
        run_at: datetime,
        priority: str,
        origin_state: str,
        confidence: float | None,
        enqueue_embedding: bool,
    ) -> Object:
        require_future_run_at(run_at)
        if priority not in NOTIFICATION_PRIORITIES:
            raise ToolError(f"invalid notification priority: {priority}")
        try:
            obj = self._write_graph.create_object(
                ObjectCreate(
                    kind=KIND_SCHEDULED_ACTIVITY,
                    title=title,
                    origin=AGENT_ORIGIN,
                    state=origin_state,
                    body=body,
                    status=SCHEDULED_ACTIVITY_STATUS_SCHEDULED,
                    due_at=run_at,
                    confidence=confidence,
                    metadata={
                        METADATA_SCHEDULE_KIND: SCHEDULE_KIND_ONCE,
                        METADATA_PRIORITY: priority,
                    },
                )
            )
        except ValidationError as exc:
            raise ToolError(exc.message) from exc
        self._jobs.enqueue(
            JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
            {"activity_id": str(obj.id)},
            user_id=self._user_id,
            run_after=run_at,
        )
        if enqueue_embedding:
            enqueue_embed_object(self._session, obj.id, self._user_id)
        return obj

    def create_recurring(
        self,
        *,
        title: str,
        body: str | None,
        spec: RecurrenceSpec,
        run_at: datetime,
        priority: str,
        origin_state: str,
        confidence: float | None,
        enqueue_embedding: bool,
    ) -> Object:
        require_future_run_at(run_at)
        if priority not in NOTIFICATION_PRIORITIES:
            raise ToolError(f"invalid notification priority: {priority}")
        metadata: dict = {
            METADATA_SCHEDULE_KIND: spec.schedule_kind,
            METADATA_PRIORITY: priority,
            METADATA_TIMEZONE: spec.timezone,
            METADATA_LOCAL_TIME: spec.local_time,
        }
        if spec.schedule_kind == "weekly":
            metadata[METADATA_WEEKDAYS] = list(spec.weekdays)
        try:
            obj = self._write_graph.create_object(
                ObjectCreate(
                    kind=KIND_SCHEDULED_ACTIVITY,
                    title=title,
                    origin=AGENT_ORIGIN,
                    state=origin_state,
                    body=body,
                    status=SCHEDULED_ACTIVITY_STATUS_SCHEDULED,
                    due_at=run_at,
                    confidence=confidence,
                    metadata=metadata,
                )
            )
        except ValidationError as exc:
            raise ToolError(exc.message) from exc
        self._jobs.enqueue(
            JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
            {
                "activity_id": str(obj.id),
                "occurrence_due_at": instant_to_iso(run_at),
            },
            user_id=self._user_id,
            run_after=run_at,
        )
        if enqueue_embedding:
            enqueue_embed_object(self._session, obj.id, self._user_id)
        return obj

    def cancel(self, activity_id: UUID) -> tuple[Object, bool]:
        obj = self._lock_owned_row(activity_id)
        if obj is None or is_object_tombstoned(obj):
            raise ToolError(f"object not found: {activity_id}")
        if obj.kind != KIND_SCHEDULED_ACTIVITY:
            raise ToolError("operation only supports scheduled_activity objects")
        if obj.status == SCHEDULED_ACTIVITY_STATUS_CANCELLED:
            return obj, False
        if obj.status == SCHEDULED_ACTIVITY_STATUS_COMPLETED:
            return obj, False
        if obj.status != SCHEDULED_ACTIVITY_STATUS_SCHEDULED:
            raise ToolError("scheduled activity cannot be cancelled in the current status")
        obj.status = SCHEDULED_ACTIVITY_STATUS_CANCELLED
        obj.updated_at = utcnow()
        self._complete_pending_run_job(obj.id)
        self._session.flush()
        return obj, True

    def fire(self, activity_id: UUID, payload: dict | None = None) -> None:
        obj = self._lock_owned_row(activity_id)
        if obj is None:
            return
        if obj.kind != KIND_SCHEDULED_ACTIVITY:
            return
        if is_object_tombstoned(obj):
            return
        if obj.status in (
            SCHEDULED_ACTIVITY_STATUS_CANCELLED,
            SCHEDULED_ACTIVITY_STATUS_COMPLETED,
        ):
            return
        if obj.status != SCHEDULED_ACTIVITY_STATUS_SCHEDULED:
            return
        metadata = dict(obj.metadata_ or {})
        schedule_kind = metadata.get(METADATA_SCHEDULE_KIND)
        if schedule_kind == SCHEDULE_KIND_ONCE:
            self._fire_once(obj, metadata)
            return
        if schedule_kind in RECURRING_SCHEDULE_KINDS:
            self._fire_recurring(obj, metadata, payload or {})
            return
        raise ValueError("scheduled activity has unknown schedule_kind")

    def _fire_once(self, obj: Object, metadata: dict) -> None:
        self._emit_notification(obj, metadata, scheduled_for=None)
        now = utcnow()
        obj.status = SCHEDULED_ACTIVITY_STATUS_COMPLETED
        obj.occurred_at = now
        obj.updated_at = now
        self._session.flush()

    def _fire_recurring(self, obj: Object, metadata: dict, payload: dict) -> None:
        spec = spec_from_metadata(metadata)
        if spec is None:
            raise ValueError("scheduled activity has invalid recurrence metadata")
        fence = require_occurrence_fence(payload.get("occurrence_due_at"))
        if not same_instant(fence, obj.due_at):
            return
        now = utcnow()
        next_due = next_occurrence(spec, now)
        self._emit_notification(obj, metadata, scheduled_for=instant_to_iso(obj.due_at))
        obj.occurred_at = now
        obj.due_at = next_due
        obj.updated_at = now
        self._jobs.enqueue(
            JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
            {
                "activity_id": str(obj.id),
                "occurrence_due_at": instant_to_iso(next_due),
            },
            user_id=self._user_id,
            run_after=next_due,
        )
        self._session.flush()

    def _emit_notification(
        self,
        obj: Object,
        metadata: dict,
        *,
        scheduled_for: str | None,
    ) -> None:
        priority = metadata.get(METADATA_PRIORITY, "normal")
        if priority not in NOTIFICATION_PRIORITIES:
            priority = "normal"
        proposal = {
            "type": NOTIFICATION_PROPOSAL_TYPE,
            "activity_id": str(obj.id),
        }
        if scheduled_for is not None:
            proposal["scheduled_for"] = scheduled_for
        NotificationService(self._session, self._user_id).create(
            title=obj.title,
            body=obj.body,
            priority=str(priority),
            proposal=proposal,
            source_object_id=obj.id,
        )

    def _lock_owned_row(self, activity_id: UUID) -> Object | None:
        return self._session.scalar(
            select(Object)
            .where(Object.id == activity_id, Object.user_id == self._user_id)
            .with_for_update()
        )

    def _complete_pending_run_job(self, activity_id: UUID) -> None:
        activity_key = str(activity_id)
        jobs = self._session.scalars(
            select(Job)
            .where(
                Job.user_id == self._user_id,
                Job.type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
                Job.status == JOB_STATUS_PENDING,
            )
            .with_for_update()
        )
        for job in jobs:
            if (job.payload or {}).get("activity_id") != activity_key:
                continue
            self._jobs.mark_done(job.id)
