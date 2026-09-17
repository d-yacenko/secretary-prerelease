from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.google.constants import CALENDAR_READONLY_SCOPE, GMAIL_READONLY_SCOPE
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.mattermost.credentials import MattermostAccountStore
from app.connectors.teams.account_store import TeamsAccountStore
from app.connectors.teams.constants import AUTH_STATUS_RECONNECT_REQUIRED
from app.connectors.yandex.calendar_credentials import YandexCalendarAccountStore
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.core.config import settings
from app.db.models import (
    GoogleAccount,
    Job,
    MattermostAccount,
    TeamsAccount,
    TelegramMtprotoAccount,
    YandexCalendarAccount,
    YandexMailAccount,
)
from app.jobs.constants import (
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_SYNC_GOOGLE_CALENDAR,
    JOB_TYPE_SYNC_GOOGLE_GMAIL,
    JOB_TYPE_SYNC_MATTERMOST,
    JOB_TYPE_SYNC_TEAMS,
    JOB_TYPE_SYNC_TELEGRAM_MTPROTO,
    JOB_TYPE_SYNC_YANDEX_CALENDAR,
    JOB_TYPE_SYNC_YANDEX_MAIL,
    RECURRING_SOURCE_JOB_TYPES,
)
from app.services.job_queue_service import JobQueueService, utcnow
from app.services.source_sync_preference_service import SourceSyncPreferenceService
from app.source_sync.constants import (
    SOURCE_GMAIL,
    SOURCE_GOOGLE_CALENDAR,
    SOURCE_MATTERMOST,
    SOURCE_TEAMS,
    SOURCE_TO_JOB_TYPE,
    SOURCE_YANDEX_CALENDAR,
    SOURCE_YANDEX_MAIL,
)


def _telegram_runtime_configured() -> bool:
    return bool(
        settings.secretary_credential_key.strip()
        and settings.telegram_api_id > 0
        and settings.telegram_api_hash.strip()
    )


class SourceSyncScheduler:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._queue = JobQueueService(session)
        self._preferences = SourceSyncPreferenceService.build(session)

    def run_maintenance(self) -> None:
        if not settings.secretary_credential_key:
            self._retire_telegram_jobs()
            return
        encryption = CredentialEncryption(settings.secretary_credential_key)
        self._maintain_google_accounts(GoogleAccountStore(self._session, encryption))
        self._maintain_yandex_mail_accounts(
            YandexMailAccountStore(self._session, encryption)
        )
        self._maintain_yandex_calendar_accounts(
            YandexCalendarAccountStore(self._session, encryption)
        )
        self._maintain_mattermost_accounts(
            MattermostAccountStore(self._session, encryption)
        )
        self._maintain_teams_accounts(
            TeamsAccountStore(self._session, encryption)
        )
        self._maintain_telegram_accounts()
        self._retire_stale_recurring_jobs(encryption)
        self._rearm_failed_recurring_jobs()

    def trigger_all_for_user(self, user_id: UUID) -> list[str]:
        triggered: list[str] = []
        if not settings.secretary_credential_key:
            return triggered
        encryption = CredentialEncryption(settings.secretary_credential_key)
        google_store = GoogleAccountStore(self._session, encryption)
        for account in google_store.list_accounts(user_id):
            scopes = set(account.scopes or [])
            if (
                GMAIL_READONLY_SCOPE in scopes
                and self._preferences.is_job_type_enabled(
                    user_id, JOB_TYPE_SYNC_GOOGLE_GMAIL
                )
                and self._queue.trigger_recurring_source_job(
                    user_id, JOB_TYPE_SYNC_GOOGLE_GMAIL, account.id
                )
            ):
                triggered.append(f"gmail:{account.id}")
            if (
                CALENDAR_READONLY_SCOPE in scopes
                and self._preferences.is_job_type_enabled(
                    user_id, JOB_TYPE_SYNC_GOOGLE_CALENDAR
                )
                and self._queue.trigger_recurring_source_job(
                    user_id, JOB_TYPE_SYNC_GOOGLE_CALENDAR, account.id
                )
            ):
                triggered.append(f"google_calendar:{account.id}")
        yandex_mail_store = YandexMailAccountStore(self._session, encryption)
        for account in yandex_mail_store.list_accounts(user_id):
            if (
                self._preferences.is_job_type_enabled(user_id, JOB_TYPE_SYNC_YANDEX_MAIL)
                and self._queue.trigger_recurring_source_job(
                    user_id, JOB_TYPE_SYNC_YANDEX_MAIL, account.id
                )
            ):
                triggered.append(f"yandex_mail:{account.id}")
        yandex_calendar_store = YandexCalendarAccountStore(self._session, encryption)
        for account in yandex_calendar_store.list_accounts(user_id):
            if (
                self._preferences.is_job_type_enabled(
                    user_id, JOB_TYPE_SYNC_YANDEX_CALENDAR
                )
                and self._queue.trigger_recurring_source_job(
                    user_id, JOB_TYPE_SYNC_YANDEX_CALENDAR, account.id
                )
            ):
                triggered.append(f"yandex_calendar:{account.id}")
        mattermost_store = MattermostAccountStore(self._session, encryption)
        for account in mattermost_store.list_accounts(user_id):
            if (
                self._preferences.is_job_type_enabled(user_id, JOB_TYPE_SYNC_MATTERMOST)
                and self._queue.trigger_recurring_source_job(
                    user_id, JOB_TYPE_SYNC_MATTERMOST, account.id
                )
            ):
                triggered.append(f"mattermost:{account.id}")
        teams_store = TeamsAccountStore(self._session, encryption)
        for account in teams_store.list_accounts(user_id):
            if account.auth_status == AUTH_STATUS_RECONNECT_REQUIRED:
                continue
            if (
                self._preferences.is_job_type_enabled(user_id, JOB_TYPE_SYNC_TEAMS)
                and self._queue.trigger_recurring_source_job(
                    user_id, JOB_TYPE_SYNC_TEAMS, account.id
                )
            ):
                triggered.append(f"teams:{account.id}")
        if _telegram_runtime_configured():
            for account in self._session.scalars(
                select(TelegramMtprotoAccount).where(TelegramMtprotoAccount.user_id == user_id)
            ):
                if self._queue.trigger_recurring_source_job(
                    user_id, JOB_TYPE_SYNC_TELEGRAM_MTPROTO, account.id
                ):
                    triggered.append(f"telegram_mtproto:{account.id}")
        return triggered

    def reconcile_user_source(self, user_id: UUID, source: str) -> None:
        if not settings.secretary_credential_key:
            return
        job_type = SOURCE_TO_JOB_TYPE.get(source)
        if job_type is None:
            return
        encryption = CredentialEncryption(settings.secretary_credential_key)
        account_ids = self._connected_account_ids_for_source(
            user_id,
            source,
            encryption,
        )
        enabled = self._preferences.is_source_enabled(user_id, source)
        for account_id in account_ids:
            if enabled:
                self._queue.ensure_recurring_source_job(job_type, account_id, user_id)
            else:
                job = self._queue.find_recurring_source_job(user_id, job_type, account_id)
                if job is not None and job.status != JOB_STATUS_RUNNING:
                    self._queue.retire_recurring_source_job(job)

    def _connected_account_ids_for_source(
        self,
        user_id: UUID,
        source: str,
        encryption: CredentialEncryption,
    ) -> list[UUID]:
        if source == SOURCE_GMAIL or source == SOURCE_GOOGLE_CALENDAR:
            google_store = GoogleAccountStore(self._session, encryption)
            account_ids: list[UUID] = []
            for account in google_store.list_accounts(user_id):
                scopes = set(account.scopes or [])
                if source == SOURCE_GMAIL and GMAIL_READONLY_SCOPE in scopes:
                    account_ids.append(account.id)
                if source == SOURCE_GOOGLE_CALENDAR and CALENDAR_READONLY_SCOPE in scopes:
                    account_ids.append(account.id)
            return account_ids
        if source == SOURCE_YANDEX_MAIL:
            store = YandexMailAccountStore(self._session, encryption)
            return [account.id for account in store.list_accounts(user_id)]
        if source == SOURCE_YANDEX_CALENDAR:
            store = YandexCalendarAccountStore(self._session, encryption)
            return [account.id for account in store.list_accounts(user_id)]
        if source == SOURCE_MATTERMOST:
            store = MattermostAccountStore(self._session, encryption)
            return [account.id for account in store.list_accounts(user_id)]
        if source == SOURCE_TEAMS:
            store = TeamsAccountStore(self._session, encryption)
            return [
                account.id
                for account in store.list_accounts(user_id)
                if account.auth_status != AUTH_STATUS_RECONNECT_REQUIRED
            ]
        return []

    def _maintain_recurring_job(
        self,
        job_type: str,
        account_id: UUID,
        user_id: UUID,
    ) -> None:
        if self._preferences.is_job_type_enabled(user_id, job_type):
            self._queue.ensure_recurring_source_job(job_type, account_id, user_id)
            return
        job = self._queue.find_recurring_source_job(user_id, job_type, account_id)
        if job is not None and job.status != JOB_STATUS_RUNNING:
            self._queue.retire_recurring_source_job(job)

    def _maintain_google_accounts(self, _store: GoogleAccountStore) -> None:
        accounts = list(self._session.scalars(select(GoogleAccount)))
        for account in accounts:
            scopes = set(account.scopes or [])
            user_id = account.user_id
            if GMAIL_READONLY_SCOPE in scopes:
                self._maintain_recurring_job(
                    JOB_TYPE_SYNC_GOOGLE_GMAIL,
                    account.id,
                    user_id,
                )
            if CALENDAR_READONLY_SCOPE in scopes:
                self._maintain_recurring_job(
                    JOB_TYPE_SYNC_GOOGLE_CALENDAR,
                    account.id,
                    user_id,
                )

    def _maintain_yandex_mail_accounts(self, _store: YandexMailAccountStore) -> None:
        accounts = list(self._session.scalars(select(YandexMailAccount)))
        for account in accounts:
            self._maintain_recurring_job(
                JOB_TYPE_SYNC_YANDEX_MAIL,
                account.id,
                account.user_id,
            )

    def _maintain_yandex_calendar_accounts(self, _store: YandexCalendarAccountStore) -> None:
        accounts = list(self._session.scalars(select(YandexCalendarAccount)))
        for account in accounts:
            self._maintain_recurring_job(
                JOB_TYPE_SYNC_YANDEX_CALENDAR,
                account.id,
                account.user_id,
            )

    def _maintain_mattermost_accounts(self, _store: MattermostAccountStore) -> None:
        accounts = list(self._session.scalars(select(MattermostAccount)))
        for account in accounts:
            self._maintain_recurring_job(
                JOB_TYPE_SYNC_MATTERMOST,
                account.id,
                account.user_id,
            )

    def _maintain_teams_accounts(self, _store: TeamsAccountStore) -> None:
        accounts = list(self._session.scalars(select(TeamsAccount)))
        for account in accounts:
            if account.auth_status == AUTH_STATUS_RECONNECT_REQUIRED:
                job = self._queue.find_recurring_source_job(
                    account.user_id, JOB_TYPE_SYNC_TEAMS, account.id
                )
                if job is not None and job.status != JOB_STATUS_RUNNING:
                    self._queue.retire_recurring_source_job(job)
                continue
            self._maintain_recurring_job(
                JOB_TYPE_SYNC_TEAMS,
                account.id,
                account.user_id,
            )

    def _maintain_telegram_accounts(self) -> None:
        if not _telegram_runtime_configured():
            self._retire_telegram_jobs()
            return
        for account in self._session.scalars(select(TelegramMtprotoAccount)):
            self._maintain_recurring_job(
                JOB_TYPE_SYNC_TELEGRAM_MTPROTO,
                account.id,
                account.user_id,
            )

    def _retire_telegram_jobs(self) -> None:
        jobs = self._session.scalars(
            select(Job).where(
                Job.type == JOB_TYPE_SYNC_TELEGRAM_MTPROTO,
                Job.status.in_((JOB_STATUS_PENDING, JOB_STATUS_FAILED)),
            )
        )
        for job in jobs:
            self._queue.retire_recurring_source_job(job)

    def _collect_expected_recurring_jobs(
        self,
        encryption: CredentialEncryption,
    ) -> set[tuple[str, UUID, UUID]]:
        expected: set[tuple[str, UUID, UUID]] = set()
        for account in self._session.scalars(select(GoogleAccount)):
            scopes = set(account.scopes or [])
            if (
                GMAIL_READONLY_SCOPE in scopes
                and self._preferences.is_job_type_enabled(
                    account.user_id, JOB_TYPE_SYNC_GOOGLE_GMAIL
                )
            ):
                expected.add(
                    (JOB_TYPE_SYNC_GOOGLE_GMAIL, account.id, account.user_id)
                )
            if (
                CALENDAR_READONLY_SCOPE in scopes
                and self._preferences.is_job_type_enabled(
                    account.user_id, JOB_TYPE_SYNC_GOOGLE_CALENDAR
                )
            ):
                expected.add(
                    (JOB_TYPE_SYNC_GOOGLE_CALENDAR, account.id, account.user_id)
                )
        for account in self._session.scalars(select(YandexMailAccount)):
            if self._preferences.is_job_type_enabled(
                account.user_id, JOB_TYPE_SYNC_YANDEX_MAIL
            ):
                expected.add((JOB_TYPE_SYNC_YANDEX_MAIL, account.id, account.user_id))
        for account in self._session.scalars(select(YandexCalendarAccount)):
            if self._preferences.is_job_type_enabled(
                account.user_id, JOB_TYPE_SYNC_YANDEX_CALENDAR
            ):
                expected.add(
                    (JOB_TYPE_SYNC_YANDEX_CALENDAR, account.id, account.user_id)
                )
        for account in self._session.scalars(select(MattermostAccount)):
            if self._preferences.is_job_type_enabled(
                account.user_id, JOB_TYPE_SYNC_MATTERMOST
            ):
                expected.add((JOB_TYPE_SYNC_MATTERMOST, account.id, account.user_id))
        for account in self._session.scalars(select(TeamsAccount)):
            if account.auth_status == AUTH_STATUS_RECONNECT_REQUIRED:
                continue
            if self._preferences.is_job_type_enabled(
                account.user_id, JOB_TYPE_SYNC_TEAMS
            ):
                expected.add((JOB_TYPE_SYNC_TEAMS, account.id, account.user_id))
        if _telegram_runtime_configured():
            for account in self._session.scalars(select(TelegramMtprotoAccount)):
                expected.add((JOB_TYPE_SYNC_TELEGRAM_MTPROTO, account.id, account.user_id))
        return expected

    def _retire_stale_recurring_jobs(self, encryption: CredentialEncryption) -> None:
        expected = self._collect_expected_recurring_jobs(encryption)
        jobs = list(
            self._session.scalars(
                select(Job).where(
                    Job.type.in_(tuple(RECURRING_SOURCE_JOB_TYPES)),
                    Job.status.in_(
                        (
                            JOB_STATUS_PENDING,
                            JOB_STATUS_RUNNING,
                            JOB_STATUS_FAILED,
                        )
                    ),
                )
            )
        )
        for job in jobs:
            raw_account_id = (job.payload or {}).get("account_id")
            if not raw_account_id:
                self._queue.retire_recurring_source_job(job)
                continue
            account_id = UUID(str(raw_account_id))
            key = (job.type, account_id, job.user_id)
            if key not in expected:
                if job.status != JOB_STATUS_RUNNING:
                    self._queue.retire_recurring_source_job(job)
                continue
            if (
                not self._preferences.is_job_type_enabled(job.user_id, job.type)
                and job.status != JOB_STATUS_RUNNING
            ):
                self._queue.retire_recurring_source_job(job)

    def _rearm_failed_recurring_jobs(self) -> None:
        now = utcnow()
        failed_jobs = list(
            self._session.scalars(
                select(Job).where(
                    Job.type.in_(
                        (
                            JOB_TYPE_SYNC_GOOGLE_GMAIL,
                            JOB_TYPE_SYNC_GOOGLE_CALENDAR,
                            JOB_TYPE_SYNC_YANDEX_MAIL,
                            JOB_TYPE_SYNC_YANDEX_CALENDAR,
                            JOB_TYPE_SYNC_MATTERMOST,
                            JOB_TYPE_SYNC_TEAMS,
                            JOB_TYPE_SYNC_TELEGRAM_MTPROTO,
                        )
                    ),
                    Job.status == JOB_STATUS_FAILED,
                    Job.run_after <= now,
                )
            )
        )
        for job in failed_jobs:
            if not self._preferences.is_job_type_enabled(job.user_id, job.type):
                continue
            self._queue.rearm_failed_recurring_job(
                job,
                settings.source_sync_failed_rearm_seconds,
            )
