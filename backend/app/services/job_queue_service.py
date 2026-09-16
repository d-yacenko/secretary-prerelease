from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.connectors.google.api_errors import format_google_api_error
from app.connectors.google.errors import GoogleApiError, GoogleConnectorError
from app.connectors.teams.errors import TeamsRateLimitedError, TeamsReconnectRequiredError
from app.connectors.yandex.caldav_api_errors import format_yandex_caldav_error
from app.connectors.yandex.errors import (
    YandexCalDavError,
    YandexConfigurationError,
    YandexConnectorError,
    YandexImapError,
)
from app.db.models import Job
from app.jobs.constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_INGEST_LOCAL_FILE,
    JOB_TYPE_PROACTIVE_REVIEW,
    MAX_JOB_ATTEMPTS,
    MAX_LAST_ERROR_LENGTH,
    RECURRING_FAILED_REARM_SECONDS,
    RECURRING_SOURCE_JOB_TYPES,
    RETRY_BACKOFF_SECONDS,
    STALE_LOCK_MINUTES,
)
from app.services.background_ai_errors import (
    BackgroundAIConfigurationError,
    is_openai_quota_exhausted,
)
from app.services.openai_daily_budget import OPENAI_DAILY_BUDGET_PARKED_ERROR
from app.services.user_openai_credential_errors import UserOpenAICredentialConfigurationError


def utcnow() -> datetime:
    return datetime.now(UTC)


def sanitize_job_error(exc: BaseException) -> str:
    if isinstance(exc, GoogleApiError):
        return format_google_api_error(exc)
    if isinstance(exc, YandexCalDavError):
        return format_yandex_caldav_error(exc)
    message = str(exc).strip() or type(exc).__name__
    first_line = message.splitlines()[0]
    lowered = first_line.lower()
    sensitive_needles = (
        "bearer ",
        "authorization:",
        "authorization ",
        "access_token",
        "refresh_token",
        "access-token",
        "personal-access",
        "personal access",
        "encrypted",
        "sk-",
    )
    for needle in sensitive_needles:
        if needle in lowered:
            return type(exc).__name__
    return first_line[:MAX_LAST_ERROR_LENGTH]


def is_job_error_retryable(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (UserOpenAICredentialConfigurationError, BackgroundAIConfigurationError),
    ):
        return False
    if is_openai_quota_exhausted(exc):
        return False
    if isinstance(exc, GoogleApiError):
        return exc.retryable
    if isinstance(exc, YandexCalDavError):
        return exc.retryable
    if isinstance(exc, YandexImapError):
        return exc.retryable
    if isinstance(exc, YandexConfigurationError):
        return False
    if isinstance(exc, YandexConnectorError):
        return True
    if isinstance(exc, GoogleConnectorError):
        return exc.retryable
    if isinstance(exc, TeamsReconnectRequiredError):
        return False
    if isinstance(exc, TeamsRateLimitedError):
        return True
    return True


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    type: str
    payload: dict
    attempts: int
    user_id: UUID


class JobQueueService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(
        self,
        job_type: str,
        payload: dict,
        user_id: UUID,
        run_after: datetime | None = None,
    ) -> Job:
        job = Job(
            user_id=user_id,
            type=job_type,
            payload=payload,
            status=JOB_STATUS_PENDING,
            attempts=0,
            run_after=run_after or utcnow(),
        )
        self._session.add(job)
        self._session.flush()
        return job

    def enqueue_once(
        self,
        job_type: str,
        payload: dict,
        user_id: UUID,
        *,
        dedupe_key: str,
        run_after: datetime | None = None,
    ) -> Job:
        for existing in self._session.scalars(
            select(Job).where(Job.user_id == user_id, Job.type == job_type)
        ):
            if existing.payload.get("dedupe_key") == dedupe_key:
                return existing
        return self.enqueue(job_type, {**payload, "dedupe_key": dedupe_key}, user_id, run_after)

    def claim_next(
        self,
        *,
        include_types: Collection[str] | None = None,
        exclude_types: Collection[str] | None = None,
    ) -> ClaimedJob | None:
        if include_types is not None and exclude_types is not None:
            raise ValueError(
                "claim_next include_types and exclude_types are mutually exclusive"
            )
        if include_types is not None and not include_types:
            raise ValueError("claim_next include_types must not be empty")
        if exclude_types is not None and not exclude_types:
            raise ValueError("claim_next exclude_types must not be empty")

        now = utcnow()
        stale_threshold = now - timedelta(minutes=STALE_LOCK_MINUTES)
        conditions = [
            or_(
                and_(Job.status == JOB_STATUS_PENDING, Job.run_after <= now),
                and_(
                    Job.status == JOB_STATUS_RUNNING,
                    Job.locked_at.is_not(None),
                    Job.locked_at < stale_threshold,
                ),
            )
        ]
        if include_types is not None:
            conditions.append(Job.type.in_(tuple(include_types)))
        if exclude_types is not None:
            conditions.append(Job.type.notin_(tuple(exclude_types)))
        stmt = (
            select(Job)
            .where(*conditions)
            .order_by(Job.run_after, Job.created_at, Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = self._session.scalar(stmt)
        if job is None:
            return None

        if (
            job.status == JOB_STATUS_RUNNING
            and job.attempts >= MAX_JOB_ATTEMPTS
        ):
            job.status = JOB_STATUS_FAILED
            job.last_error = (job.last_error or "stale lock exceeded max attempts")[
                :MAX_LAST_ERROR_LENGTH
            ]
            job.locked_at = None
            job.updated_at = now
            self._apply_recurring_failure_cooldown(job)
            self._session.flush()
            return None

        job.status = JOB_STATUS_RUNNING
        job.attempts += 1
        job.locked_at = now
        job.updated_at = now
        self._session.flush()
        return ClaimedJob(
            id=job.id,
            type=job.type,
            payload=dict(job.payload),
            attempts=job.attempts,
            user_id=job.user_id,
        )

    def mark_done(self, job_id: UUID) -> None:
        job = self._require_job(job_id)
        job.status = JOB_STATUS_DONE
        job.locked_at = None
        job.updated_at = utcnow()

    def mark_failed(self, job_id: UUID, error: str) -> None:
        job = self._require_job(job_id)
        job.status = JOB_STATUS_FAILED
        job.last_error = error[:MAX_LAST_ERROR_LENGTH]
        job.locked_at = None
        job.updated_at = utcnow()
        self._apply_recurring_failure_cooldown(job)

    def park_until_openai_budget_reset(self, job_id: UUID, reset_at: datetime) -> None:
        """Defer an AI job to the next local day without burning a retry attempt.

        The claim that just happened incremented `attempts`; parking undoes only
        that increment so genuine earlier failures keep their history and the job
        never hot-loops while the daily cap is exhausted.
        """
        job = self._require_job(job_id)
        now = utcnow()
        job.status = JOB_STATUS_PENDING
        job.attempts = max(job.attempts - 1, 0)
        job.locked_at = None
        job.last_error = OPENAI_DAILY_BUDGET_PARKED_ERROR
        job.run_after = max(reset_at, now)
        job.updated_at = now
        self._session.flush()

    def release_budget_parked_jobs(self, user_id: UUID) -> int:
        """Make budget-parked AI work runnable again after the cap is raised/cleared."""
        now = utcnow()
        parked = list(
            self._session.scalars(
                select(Job).where(
                    Job.user_id == user_id,
                    Job.status == JOB_STATUS_PENDING,
                    Job.last_error == OPENAI_DAILY_BUDGET_PARKED_ERROR,
                    Job.run_after > now,
                )
            )
        )
        for job in parked:
            job.last_error = None
            job.run_after = now
            job.updated_at = now
        self._session.flush()
        return len(parked)

    def mark_retry(
        self,
        job_id: UUID,
        error: str,
        *,
        retryable: bool = True,
        run_after: datetime | None = None,
    ) -> None:
        job = self._require_job(job_id)
        job.last_error = error[:MAX_LAST_ERROR_LENGTH]
        job.updated_at = utcnow()
        if not retryable:
            if job.type in RECURRING_SOURCE_JOB_TYPES:
                job.status = JOB_STATUS_PENDING
                job.attempts = 0
                job.locked_at = None
                self._apply_recurring_failure_cooldown(job)
                self._session.flush()
                return
            job.status = JOB_STATUS_FAILED
            job.locked_at = None
            self._session.flush()
            return
        if job.attempts >= MAX_JOB_ATTEMPTS:
            job.status = JOB_STATUS_FAILED
            job.locked_at = None
            self._apply_recurring_failure_cooldown(job)
            self._session.flush()
            return

        backoff = RETRY_BACKOFF_SECONDS.get(job.attempts, RETRY_BACKOFF_SECONDS[2])
        job.status = JOB_STATUS_PENDING
        job.locked_at = None
        job.run_after = run_after if run_after is not None else utcnow() + timedelta(seconds=backoff)
        self._session.flush()

    def find_recurring_source_job(
        self,
        user_id: UUID,
        job_type: str,
        account_id: UUID,
    ) -> Job | None:
        account_key = str(account_id)
        return self._session.scalar(
            select(Job).where(
                Job.user_id == user_id,
                Job.type == job_type,
                Job.payload["account_id"].as_string() == account_key,
                Job.status.in_(
                    (JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_FAILED)
                ),
            )
        )

    def find_done_recurring_source_job(
        self,
        user_id: UUID,
        job_type: str,
        account_id: UUID,
    ) -> Job | None:
        account_key = str(account_id)
        return self._session.scalar(
            select(Job)
            .where(
                Job.user_id == user_id,
                Job.type == job_type,
                Job.payload["account_id"].as_string() == account_key,
                Job.status == JOB_STATUS_DONE,
            )
            .order_by(Job.updated_at.desc())
            .limit(1)
        )

    def reactivate_recurring_source_job(self, job: Job) -> None:
        now = utcnow()
        job.status = JOB_STATUS_PENDING
        job.attempts = 0
        job.last_error = None
        self._clear_recurring_failure_metadata(job)
        job.locked_at = None
        job.run_after = now
        job.updated_at = now
        self._session.flush()

    def ensure_recurring_source_job(
        self,
        job_type: str,
        account_id: UUID,
        user_id: UUID,
        run_after: datetime | None = None,
    ) -> Job:
        existing = self.find_recurring_source_job(user_id, job_type, account_id)
        now = utcnow()
        if existing is not None:
            return existing
        retired = self.find_done_recurring_source_job(user_id, job_type, account_id)
        if retired is not None:
            self.reactivate_recurring_source_job(retired)
            return retired
        return self.enqueue(
            job_type,
            {"account_id": str(account_id)},
            user_id,
            run_after=run_after or now,
        )

    def retire_recurring_source_job(self, job: Job) -> None:
        job.status = JOB_STATUS_DONE
        job.locked_at = None
        job.last_error = None
        self._clear_recurring_failure_metadata(job)
        job.updated_at = utcnow()
        self._session.flush()

    def trigger_recurring_source_job(
        self,
        user_id: UUID,
        job_type: str,
        account_id: UUID,
    ) -> bool:
        job = self.find_recurring_source_job(user_id, job_type, account_id)
        if job is None:
            retired = self.find_done_recurring_source_job(user_id, job_type, account_id)
            if retired is None:
                return False
            self.reactivate_recurring_source_job(retired)
            job = retired
        now = utcnow()
        job.run_after = now
        if job.status == JOB_STATUS_FAILED:
            job.status = JOB_STATUS_PENDING
            job.attempts = 0
        job.updated_at = now
        self._session.flush()
        return True

    def rearm_failed_recurring_job(
        self,
        job: Job,
        cooldown_seconds: int,
    ) -> bool:
        if job.status != JOB_STATUS_FAILED:
            return False
        now = utcnow()
        if job.run_after > now:
            return False
        job.status = JOB_STATUS_PENDING
        job.attempts = 0
        job.last_error = None
        self._clear_recurring_failure_metadata(job)
        job.run_after = now
        job.updated_at = now
        self._session.flush()
        return True

    def mark_recurring_success(self, job_id: UUID, interval_seconds: int) -> None:
        job = self._require_job(job_id)
        now = utcnow()
        payload = dict(job.payload or {})
        payload["last_success_at"] = now.isoformat()
        payload.pop("last_error_kind", None)
        payload.pop("last_error_retryable", None)
        job.payload = payload
        job.status = JOB_STATUS_PENDING
        job.attempts = 0
        job.last_error = None
        job.locked_at = None
        job.run_after = now + timedelta(seconds=interval_seconds)
        job.updated_at = now

    def mark_recurring_failure(
        self,
        job_id: UUID,
        error: str,
        *,
        failure_kind: str,
        retryable: bool,
    ) -> None:
        job = self._require_job(job_id)
        payload = dict(job.payload or {})
        payload["last_error_kind"] = failure_kind
        payload["last_error_retryable"] = retryable
        job.payload = payload
        job.status = JOB_STATUS_FAILED
        job.last_error = error[:MAX_LAST_ERROR_LENGTH]
        job.locked_at = None
        job.updated_at = utcnow()
        self._apply_recurring_failure_cooldown(job)

    def recurring_interval_seconds(self, job_type: str, user_id: UUID | None = None) -> int:
        if user_id is not None:
            from app.services.source_sync_preference_service import (
                SourceSyncPreferenceService,
            )

            return SourceSyncPreferenceService.build(
                self._session
            ).effective_interval_seconds_for_job_type(user_id, job_type)
        from app.services.source_sync_preference_service import (
            deployment_default_interval_seconds_for_job_type,
        )

        return deployment_default_interval_seconds_for_job_type(job_type)

    def is_recurring_source_job(self, job_type: str) -> bool:
        return job_type in RECURRING_SOURCE_JOB_TYPES

    def _uses_failed_rearm(self, job_type: str) -> bool:
        return job_type in RECURRING_SOURCE_JOB_TYPES or job_type == JOB_TYPE_PROACTIVE_REVIEW

    def _apply_recurring_failure_cooldown(self, job: Job) -> None:
        if not self._uses_failed_rearm(job.type):
            return
        from app.core.config import settings

        if job.type == JOB_TYPE_PROACTIVE_REVIEW:
            seconds = RECURRING_FAILED_REARM_SECONDS
        else:
            seconds = settings.source_sync_failed_rearm_seconds
        job.run_after = utcnow() + timedelta(seconds=seconds)

    def get_job(self, job_id: UUID) -> Job | None:
        return self._session.get(Job, job_id)

    def has_pending_ingest_job(
        self,
        object_id: UUID,
        expected_revision: str | None,
        expected_policy: str | None,
        user_id: UUID,
    ) -> bool:
        jobs = self._session.scalars(
            select(Job).where(
                Job.user_id == user_id,
                Job.type == JOB_TYPE_INGEST_LOCAL_FILE,
                Job.status.in_((JOB_STATUS_PENDING, JOB_STATUS_RUNNING)),
            )
        )
        object_key = str(object_id)
        for job in jobs:
            payload = job.payload or {}
            if payload.get("object_id") != object_key:
                continue
            if payload.get("expected_revision") != expected_revision:
                continue
            if payload.get("expected_policy") != expected_policy:
                continue
            return True
        return False

    def _require_job(self, job_id: UUID) -> Job:
        job = self._session.get(Job, job_id)
        if job is None:
            raise ValueError(f"job not found: {job_id}")
        return job

    @staticmethod
    def _clear_recurring_failure_metadata(job: Job) -> None:
        payload = dict(job.payload or {})
        payload.pop("last_error_kind", None)
        payload.pop("last_error_retryable", None)
        job.payload = payload
