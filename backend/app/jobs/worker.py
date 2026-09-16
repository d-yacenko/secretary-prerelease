import logging
from collections.abc import Collection
from datetime import UTC, datetime, timedelta

from app.ai_audit.context import reset_current_job_id, set_current_job_id
from app.connectors.teams.constants import DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
from app.connectors.teams.errors import TeamsRateLimitedError
from app.connectors.yandex.errors import classify_yandex_sync_failure
from app.db.session import SessionLocal
from app.jobs.constants import JOB_TYPE_SYNC_YANDEX_CALENDAR, JOB_TYPE_SYNC_YANDEX_MAIL
from app.jobs.handlers import get_handler
from app.jobs.recurring_job_finalization import (
    finalize_recurring_job_failure,
    finalize_recurring_job_success,
)
from app.llm.embedding_service import EmbeddingService
from app.services.job_queue_service import (
    JobQueueService,
    is_job_error_retryable,
    sanitize_job_error,
)
from app.services.openai_daily_budget import (
    OpenAIDailyBudgetExhaustedError,
    OpenAIDailyBudgetGuard,
)
from app.services.source_sync_preference_service import SourceSyncPreferenceService

logger = logging.getLogger(__name__)


def process_one_job(
    embedding_service: EmbeddingService | None = None,
    *,
    include_types: Collection[str] | None = None,
    exclude_types: Collection[str] | None = None,
) -> bool:
    session = SessionLocal()
    try:
        queue = JobQueueService(session)
        claimed = queue.claim_next(
            include_types=include_types,
            exclude_types=exclude_types,
        )
        if claimed is None:
            return False
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    handler = get_handler(claimed.type)
    if handler is None:
        session = SessionLocal()
        try:
            JobQueueService(session).mark_failed(claimed.id, "unknown job type")
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("failed to mark unknown job type as failed")
        finally:
            session.close()
        return True

    session = SessionLocal()
    try:
        queue = JobQueueService(session)
        if queue.is_recurring_source_job(claimed.type):
            preferences = SourceSyncPreferenceService.build(session)
            if not preferences.is_job_type_enabled(claimed.user_id, claimed.type):
                job = queue.get_job(claimed.id)
                if job is not None:
                    queue.retire_recurring_source_job(job)
                session.commit()
                return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    try:
        session = SessionLocal()
        try:
            queue = JobQueueService(session)
            job_token = set_current_job_id(claimed.id)
            try:
                handler(session, embedding_service, claimed.payload, claimed.user_id)
            finally:
                reset_current_job_id(job_token)
            if queue.is_recurring_source_job(claimed.type):
                finalize_recurring_job_success(
                    session,
                    claimed.id,
                    claimed.user_id,
                    claimed.type,
                )
            else:
                queue.mark_done(claimed.id)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    except OpenAIDailyBudgetExhaustedError as exc:
        logger.info(
            "job %s (%s) parked until OpenAI daily budget reset %s",
            claimed.id,
            claimed.type,
            exc.reset_at.isoformat(),
        )
        session = SessionLocal()
        try:
            queue = JobQueueService(session)
            queue.park_until_openai_budget_reset(claimed.id, exc.reset_at)
            OpenAIDailyBudgetGuard(
                session,
                claimed.user_id,
            ).ensure_exhausted_notification()
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("failed to park budget-blocked job %s", claimed.id)
        finally:
            session.close()
    except TeamsRateLimitedError as exc:
        delay = exc.retry_after_seconds
        if delay is None:
            delay = DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
        run_after = datetime.now(UTC) + timedelta(seconds=delay)
        logger.warning(
            "job %s (%s) rate limited; retry after %ss",
            claimed.id,
            claimed.type,
            delay,
        )
        session = SessionLocal()
        try:
            queue = JobQueueService(session)
            if queue.is_recurring_source_job(claimed.type):
                finalize_recurring_job_failure(
                    session,
                    claimed.id,
                    claimed.user_id,
                    claimed.type,
                    sanitize_job_error(exc),
                    retryable=True,
                    run_after=run_after,
                )
            else:
                queue.mark_retry(
                    claimed.id,
                    sanitize_job_error(exc),
                    retryable=True,
                    run_after=run_after,
                )
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("failed to record rate-limit retry for %s", claimed.id)
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("job %s (%s) failed: %s", claimed.id, claimed.type, type(exc).__name__)
        session = SessionLocal()
        try:
            queue = JobQueueService(session)
            failure_kind = None
            failure_retryable = is_job_error_retryable(exc)
            if claimed.type in {
                JOB_TYPE_SYNC_YANDEX_MAIL,
                JOB_TYPE_SYNC_YANDEX_CALENDAR,
            }:
                failure_kind, failure_retryable = classify_yandex_sync_failure(exc)
            if queue.is_recurring_source_job(claimed.type):
                finalize_recurring_job_failure(
                    session,
                    claimed.id,
                    claimed.user_id,
                    claimed.type,
                    sanitize_job_error(exc),
                    retryable=failure_retryable,
                    failure_kind=failure_kind,
                )
            else:
                queue.mark_retry(
                    claimed.id,
                    sanitize_job_error(exc),
                    retryable=is_job_error_retryable(exc),
                )
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("failed to record job failure for %s", claimed.id)
        finally:
            session.close()

    return True
