from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Job, UserSettings
from app.jobs.constants import (
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_PROACTIVE_REVIEW,
    RECURRING_FAILED_REARM_SECONDS,
)
from app.proactive.control import read_proactive_control
from app.services.job_queue_service import JobQueueService, utcnow

_ACTIVE_STATUSES = (JOB_STATUS_PENDING, JOB_STATUS_RUNNING)
_HELD_STATUSES = (JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_FAILED)


class ProactiveScheduler:
    """Ensure at most one held proactive_review job per opted-in user."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._queue = JobQueueService(session)

    def run_maintenance(self) -> None:
        user_ids = set(
            self._session.scalars(
                select(UserSettings.user_id).where(UserSettings.proactive_enabled.is_(True))
            )
        )
        held_user_ids = set(
            self._session.scalars(
                select(Job.user_id).where(
                    Job.type == JOB_TYPE_PROACTIVE_REVIEW,
                    Job.status.in_(_HELD_STATUSES),
                )
            )
        )
        for user_id in user_ids | held_user_ids:
            self.sync_user(user_id)

    def sync_user(self, user_id: UUID) -> None:
        control = read_proactive_control(self._session, user_id, for_update=True)
        jobs = self._held_jobs(user_id)
        if not control.enabled:
            for job in jobs:
                if job.status != JOB_STATUS_RUNNING:
                    self._queue.retire_recurring_source_job(job)
            return
        active = [job for job in jobs if job.status in _ACTIVE_STATUSES]
        failed = [job for job in jobs if job.status == JOB_STATUS_FAILED]
        if len(active) > 1:
            keep = min(active, key=lambda job: (job.created_at, job.id))
            for job in active:
                if job.id != keep.id and job.status != JOB_STATUS_RUNNING:
                    self._queue.retire_recurring_source_job(job)
            return
        if active:
            return
        now = utcnow()
        ready_failed = [job for job in failed if job.run_after <= now]
        waiting_failed = [job for job in failed if job.run_after > now]
        if ready_failed:
            keep = min(ready_failed, key=lambda job: (job.created_at, job.id))
            self._queue.rearm_failed_recurring_job(keep, RECURRING_FAILED_REARM_SECONDS)
            for job in ready_failed:
                if job.id != keep.id:
                    self._queue.retire_recurring_source_job(job)
            return
        if waiting_failed:
            return
        window_start = now - timedelta(minutes=control.interval_minutes)
        self._queue.enqueue(
            JOB_TYPE_PROACTIVE_REVIEW,
            {"window_start": window_start.isoformat()},
            user_id,
            run_after=now,
        )

    def _held_jobs(self, user_id: UUID) -> list[Job]:
        return list(
            self._session.scalars(
                select(Job).where(
                    Job.user_id == user_id,
                    Job.type == JOB_TYPE_PROACTIVE_REVIEW,
                    Job.status.in_(_HELD_STATUSES),
                )
            )
        )
