from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.google.constants import CALENDAR_READONLY_SCOPE, GMAIL_READONLY_SCOPE
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.mattermost.credentials import MattermostAccountStore
from app.connectors.teams.account_store import TeamsAccountStore
from app.connectors.yandex.calendar_credentials import YandexCalendarAccountStore
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.core.config import settings
from app.db.models import Job
from app.jobs.constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_SYNC_GOOGLE_CALENDAR,
    JOB_TYPE_SYNC_GOOGLE_GMAIL,
    JOB_TYPE_SYNC_MATTERMOST,
    JOB_TYPE_SYNC_TEAMS,
    JOB_TYPE_SYNC_YANDEX_CALENDAR,
    JOB_TYPE_SYNC_YANDEX_MAIL,
    RECURRING_SOURCE_JOB_TYPES,
)
from app.services.job_queue_service import utcnow
from app.services.source_sync_preference_service import SourceSyncPreferenceService
from app.source_sync.constants import (
    SOURCE_GMAIL,
    SOURCE_GOOGLE_CALENDAR,
    SOURCE_MATTERMOST,
    SOURCE_TEAMS,
    SOURCE_YANDEX_CALENDAR,
    SOURCE_YANDEX_MAIL,
)

SOURCE_TYPE_LABELS = {
    JOB_TYPE_SYNC_GOOGLE_GMAIL: SOURCE_GMAIL,
    JOB_TYPE_SYNC_GOOGLE_CALENDAR: SOURCE_GOOGLE_CALENDAR,
    JOB_TYPE_SYNC_YANDEX_MAIL: SOURCE_YANDEX_MAIL,
    JOB_TYPE_SYNC_YANDEX_CALENDAR: SOURCE_YANDEX_CALENDAR,
    JOB_TYPE_SYNC_MATTERMOST: SOURCE_MATTERMOST,
    JOB_TYPE_SYNC_TEAMS: SOURCE_TEAMS,
}

_STATUS_PRIORITY = {
    JOB_STATUS_RUNNING: 0,
    JOB_STATUS_PENDING: 1,
    JOB_STATUS_FAILED: 2,
    JOB_STATUS_DONE: 3,
}


@dataclass(frozen=True)
class SourceStatusRow:
    source: str
    provider: str
    account_id: UUID
    account_label: str
    enabled: bool
    status: str
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    next_sync_at: datetime | None
    last_error: str | None
    error_kind: str | None
    retryable: bool


@dataclass(frozen=True)
class _ConnectedSourceAccount:
    source_key: str
    job_type: str
    account_id: UUID
    account_label: str


class SourceStatusService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._preferences = SourceSyncPreferenceService.build(session)

    def list_status(self) -> list[SourceStatusRow]:
        jobs = list(
            self._session.scalars(
                select(Job).where(
                    Job.user_id == self._user_id,
                    Job.type.in_(tuple(RECURRING_SOURCE_JOB_TYPES)),
                )
            )
        )
        jobs_by_key: dict[tuple[str, UUID], list[Job]] = {}
        for job in jobs:
            raw_account_id = (job.payload or {}).get("account_id")
            if not raw_account_id:
                continue
            account_id = UUID(str(raw_account_id))
            jobs_by_key.setdefault((job.type, account_id), []).append(job)

        rows: list[SourceStatusRow] = []
        for account in self._connected_accounts():
            job_group = jobs_by_key.get((account.job_type, account.account_id), [])
            history_job = self._pick_history_job(job_group)
            active_job = self._pick_active_job(job_group)
            effective = self._preferences.get_effective_preference(
                self._user_id,
                account.source_key,
            )
            last_success_at, last_attempt_at = self._history_timestamps(history_job)
            if not effective.enabled:
                rows.append(
                    SourceStatusRow(
                        source=account.source_key,
                        provider=account.source_key,
                        account_id=account.account_id,
                        account_label=account.account_label,
                        enabled=False,
                        status="disabled",
                        last_success_at=last_success_at,
                        last_attempt_at=last_attempt_at,
                        next_sync_at=None,
                        last_error=None,
                        error_kind=None,
                        retryable=False,
                    )
                )
                continue
            if active_job is None:
                rows.append(
                    SourceStatusRow(
                        source=account.source_key,
                        provider=account.source_key,
                        account_id=account.account_id,
                        account_label=account.account_label,
                        enabled=True,
                        status="scheduled",
                        last_success_at=last_success_at,
                        last_attempt_at=last_attempt_at,
                        next_sync_at=None,
                        last_error=None,
                        error_kind=None,
                        retryable=False,
                    )
                )
                continue
            error_kind, retryable = self._failure_metadata(active_job)
            rows.append(
                SourceStatusRow(
                    source=account.source_key,
                    provider=account.source_key,
                    account_id=account.account_id,
                    account_label=account.account_label,
                    enabled=True,
                    status=self._derive_status(active_job),
                    last_success_at=last_success_at,
                    last_attempt_at=last_attempt_at,
                    next_sync_at=(
                        active_job.run_after
                        if active_job.status in (JOB_STATUS_PENDING, JOB_STATUS_FAILED)
                        else None
                    ),
                    last_error=active_job.last_error,
                    error_kind=error_kind,
                    retryable=retryable,
                )
            )
        rows.sort(key=lambda row: (row.provider, row.account_label))
        return rows

    def _connected_accounts(self) -> list[_ConnectedSourceAccount]:
        if not settings.secretary_credential_key:
            return []
        encryption = CredentialEncryption(settings.secretary_credential_key)
        accounts: list[_ConnectedSourceAccount] = []
        google_store = GoogleAccountStore(self._session, encryption)
        for account in google_store.list_accounts(self._user_id):
            scopes = set(account.scopes or [])
            if GMAIL_READONLY_SCOPE in scopes:
                accounts.append(
                    _ConnectedSourceAccount(
                        source_key=SOURCE_GMAIL,
                        job_type=JOB_TYPE_SYNC_GOOGLE_GMAIL,
                        account_id=account.id,
                        account_label=account.email,
                    )
                )
            if CALENDAR_READONLY_SCOPE in scopes:
                accounts.append(
                    _ConnectedSourceAccount(
                        source_key=SOURCE_GOOGLE_CALENDAR,
                        job_type=JOB_TYPE_SYNC_GOOGLE_CALENDAR,
                        account_id=account.id,
                        account_label=account.email,
                    )
                )
        yandex_mail_store = YandexMailAccountStore(self._session, encryption)
        for account in yandex_mail_store.list_accounts(self._user_id):
            accounts.append(
                _ConnectedSourceAccount(
                    source_key=SOURCE_YANDEX_MAIL,
                    job_type=JOB_TYPE_SYNC_YANDEX_MAIL,
                    account_id=account.id,
                    account_label=account.email,
                )
            )
        yandex_calendar_store = YandexCalendarAccountStore(self._session, encryption)
        for account in yandex_calendar_store.list_accounts(self._user_id):
            accounts.append(
                _ConnectedSourceAccount(
                    source_key=SOURCE_YANDEX_CALENDAR,
                    job_type=JOB_TYPE_SYNC_YANDEX_CALENDAR,
                    account_id=account.id,
                    account_label=account.email,
                )
            )
        mattermost_store = MattermostAccountStore(self._session, encryption)
        for account in mattermost_store.list_accounts(self._user_id):
            accounts.append(
                _ConnectedSourceAccount(
                    source_key=SOURCE_MATTERMOST,
                    job_type=JOB_TYPE_SYNC_MATTERMOST,
                    account_id=account.id,
                    account_label=self._mattermost_account_label(account),
                )
            )
        teams_store = TeamsAccountStore(self._session, encryption)
        for account in teams_store.list_accounts(self._user_id):
            accounts.append(
                _ConnectedSourceAccount(
                    source_key=SOURCE_TEAMS,
                    job_type=JOB_TYPE_SYNC_TEAMS,
                    account_id=account.id,
                    account_label=self._teams_account_label(account),
                )
            )
        return accounts

    @staticmethod
    def _pick_active_job(jobs: list[Job]) -> Job | None:
        active = [
            job
            for job in jobs
            if job.status in (JOB_STATUS_RUNNING, JOB_STATUS_PENDING, JOB_STATUS_FAILED)
        ]
        if not active:
            return None
        return min(
            active,
            key=lambda job: (
                _STATUS_PRIORITY.get(job.status, 99),
                -(job.updated_at.timestamp()),
            ),
        )

    @staticmethod
    def _pick_history_job(jobs: list[Job]) -> Job | None:
        if not jobs:
            return None
        return max(jobs, key=lambda job: job.updated_at.timestamp())

    @staticmethod
    def _history_timestamps(job: Job | None) -> tuple[datetime | None, datetime | None]:
        if job is None:
            return None, None
        payload = job.payload or {}
        last_success_raw = payload.get("last_success_at")
        last_success_at = None
        if isinstance(last_success_raw, str):
            try:
                last_success_at = datetime.fromisoformat(last_success_raw)
            except ValueError:
                last_success_at = None
        last_attempt_at = job.locked_at or (
            job.updated_at if job.attempts > 0 else None
        )
        return last_success_at, last_attempt_at

    def _derive_status(self, job: Job) -> str:
        if job.status == JOB_STATUS_RUNNING:
            return "syncing"
        if job.status == JOB_STATUS_FAILED:
            return "error"
        if job.last_error:
            return "error"
        now = utcnow()
        if job.status == JOB_STATUS_PENDING and job.run_after > now:
            return "scheduled"
        return "pending"

    @staticmethod
    def _failure_metadata(job: Job) -> tuple[str | None, bool]:
        if not job.last_error:
            return None, False
        payload = job.payload or {}
        kind = payload.get("last_error_kind")
        if not isinstance(kind, str) or kind not in {
            "transient",
            "authentication",
            "permission",
            "unknown",
        }:
            return "unknown", False
        retryable = payload.get("last_error_retryable")
        return kind, retryable if isinstance(retryable, bool) else False

    @staticmethod
    def _mattermost_account_label(account) -> str:
        display_name = (account.display_name or "").strip()
        username = (account.username or "").strip()
        server = (account.server_url or "").strip()
        if display_name and server:
            return f"{display_name} @ {server}"
        if username and server:
            return f"{username} @ {server}"
        if display_name:
            return display_name
        if username:
            return username
        return server or str(account.id)

    @staticmethod
    def _teams_account_label(account) -> str:
        display_name = (account.display_name or "").strip()
        upn = (account.upn or "").strip()
        if display_name and upn:
            return f"{display_name} ({upn})"
        return display_name or upn or str(account.id)
