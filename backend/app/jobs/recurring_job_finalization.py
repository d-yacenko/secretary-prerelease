from uuid import UUID

from sqlalchemy.orm import Session

from app.services.job_queue_service import (
    GOOGLE_TRANSIENT_RETRY_JOB_TYPES,
    YANDEX_TRANSIENT_RETRY_JOB_TYPES,
    JobQueueService,
)
from app.services.source_sync_preference_service import SourceSyncPreferenceService


def finalize_recurring_job_success(
    session: Session,
    job_id: UUID,
    user_id: UUID,
    job_type: str,
) -> None:
    queue = JobQueueService(session)
    preferences = SourceSyncPreferenceService.build(session)
    job = queue.get_job(job_id)
    if job is None:
        return
    if not preferences.is_job_type_enabled(user_id, job_type):
        queue.retire_recurring_source_job(job)
        return
    interval = preferences.effective_interval_seconds_for_job_type(user_id, job_type)
    queue.mark_recurring_success(job_id, interval)


def finalize_recurring_job_failure(
    session: Session,
    job_id: UUID,
    user_id: UUID,
    job_type: str,
    error: str,
    *,
    retryable: bool,
    failure_kind: str | None = None,
    run_after=None,
    retry_after_seconds: int | None = None,
) -> None:
    queue = JobQueueService(session)
    preferences = SourceSyncPreferenceService.build(session)
    job = queue.get_job(job_id)
    if job is None:
        return
    if not preferences.is_job_type_enabled(user_id, job_type):
        queue.retire_recurring_source_job(job)
        return
    if job_type in GOOGLE_TRANSIENT_RETRY_JOB_TYPES:
        if failure_kind == "transient" and retryable:
            queue.mark_google_recurring_transient_retry(
                job_id,
                error,
                retry_after_seconds=retry_after_seconds,
            )
            return
        queue.mark_recurring_failure(
            job_id,
            error,
            failure_kind=failure_kind or "unknown",
            retryable=retryable,
        )
        return
    if job_type in YANDEX_TRANSIENT_RETRY_JOB_TYPES:
        if failure_kind == "transient" and retryable:
            queue.mark_recurring_transient_retry(job_id, error)
            return
        queue.mark_recurring_failure(
            job_id,
            error,
            failure_kind=failure_kind or "unknown",
            retryable=retryable,
        )
        return
    queue.mark_retry(job_id, error, retryable=retryable, run_after=run_after)
