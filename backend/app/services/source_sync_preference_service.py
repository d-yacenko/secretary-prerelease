from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import (
    MIN_SOURCE_SYNC_HISTORY_DAYS,
    MIN_SOURCE_SYNC_INTERVAL_SECONDS,
    settings,
)
from app.db.models import UserSourcePreference
from app.source_sync.constants import (
    SOURCE_GMAIL,
    SOURCE_GOOGLE_CALENDAR,
    SOURCE_MATTERMOST,
    SOURCE_TEAMS,
    SOURCE_YANDEX_CALENDAR,
    SOURCE_YANDEX_MAIL,
    SUPPORTED_SOURCE_KEYS,
    SUPPORTED_SOURCE_KEYS_ORDERED,
)


@dataclass(frozen=True)
class EffectiveSourceSyncPreference:
    source: str
    enabled: bool
    sync_interval_seconds: int
    default_sync_interval_seconds: int
    min_sync_interval_seconds: int
    max_sync_interval_seconds: int
    history_days: int
    default_history_days: int
    min_history_days: int
    max_history_days: int


def utcnow() -> datetime:
    return datetime.now(UTC)


def deployment_default_interval_seconds(source: str) -> int:
    mapping = {
        SOURCE_GMAIL: settings.source_sync_gmail_interval_seconds,
        SOURCE_GOOGLE_CALENDAR: settings.source_sync_google_calendar_interval_seconds,
        SOURCE_YANDEX_MAIL: settings.source_sync_yandex_mail_interval_seconds,
        SOURCE_YANDEX_CALENDAR: settings.source_sync_yandex_calendar_interval_seconds,
        SOURCE_MATTERMOST: settings.source_sync_mattermost_interval_seconds,
        SOURCE_TEAMS: settings.source_sync_teams_interval_seconds,
    }
    return mapping[source]


def deployment_default_history_days(source: str) -> int:
    mapping = {
        SOURCE_GMAIL: settings.gmail_sync_days,
        SOURCE_GOOGLE_CALENDAR: settings.calendar_sync_days_back,
        SOURCE_YANDEX_MAIL: settings.yandex_mail_sync_days,
        SOURCE_YANDEX_CALENDAR: settings.calendar_sync_days_back,
        SOURCE_MATTERMOST: settings.mattermost_sync_days,
        SOURCE_TEAMS: settings.source_sync_user_min_history_days,
    }
    return mapping[source]


def deployment_default_interval_seconds_for_job_type(job_type: str) -> int:
    from app.jobs.constants import JOB_TYPE_SYNC_TELEGRAM_MTPROTO
    from app.source_sync.constants import JOB_TYPE_TO_SOURCE

    if job_type == JOB_TYPE_SYNC_TELEGRAM_MTPROTO:
        return settings.source_sync_telegram_mtproto_interval_seconds
    source = JOB_TYPE_TO_SOURCE.get(job_type)
    if source is None:
        return settings.source_sync_gmail_interval_seconds
    return deployment_default_interval_seconds(source)


def _history_policy_bounds() -> tuple[int, int]:
    min_days = max(
        MIN_SOURCE_SYNC_HISTORY_DAYS,
        settings.source_sync_user_min_history_days,
    )
    max_days = max(min_days, settings.source_sync_user_max_history_days)
    return min_days, max_days


def clamp_history_days(value: int) -> int:
    min_days, max_days = _history_policy_bounds()
    return max(min_days, min(max_days, value))


def clamp_sync_interval_seconds(value: int) -> int:
    min_seconds = max(
        MIN_SOURCE_SYNC_INTERVAL_SECONDS,
        settings.source_sync_user_min_interval_seconds,
    )
    max_seconds = max(min_seconds, settings.source_sync_user_max_interval_seconds)
    return max(min_seconds, min(max_seconds, value))


class SourceSyncPreferenceService:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def build(session: Session) -> Self:
        return SourceSyncPreferenceService(session)

    def list_effective_preferences(self, user_id: UUID) -> list[EffectiveSourceSyncPreference]:
        return [
            self.get_effective_preference(user_id, source)
            for source in SUPPORTED_SOURCE_KEYS_ORDERED
        ]

    def get_effective_preference(
        self,
        user_id: UUID,
        source: str,
    ) -> EffectiveSourceSyncPreference:
        if source not in SUPPORTED_SOURCE_KEYS:
            raise ValueError(f"unsupported source: {source}")
        row = self._get_row(user_id, source)
        default_interval = deployment_default_interval_seconds(source)
        min_seconds = max(
            MIN_SOURCE_SYNC_INTERVAL_SECONDS,
            settings.source_sync_user_min_interval_seconds,
        )
        max_seconds = max(min_seconds, settings.source_sync_user_max_interval_seconds)
        enabled = row.enabled if row is not None and row.enabled is not None else True
        if row is not None and row.sync_interval_seconds is not None:
            interval = clamp_sync_interval_seconds(row.sync_interval_seconds)
        else:
            interval = clamp_sync_interval_seconds(default_interval)
        default_history = deployment_default_history_days(source)
        min_history, max_history = _history_policy_bounds()
        if row is not None and row.history_days is not None:
            history = clamp_history_days(row.history_days)
        else:
            history = clamp_history_days(default_history)
        return EffectiveSourceSyncPreference(
            source=source,
            enabled=enabled,
            sync_interval_seconds=interval,
            default_sync_interval_seconds=default_interval,
            min_sync_interval_seconds=min_seconds,
            max_sync_interval_seconds=max_seconds,
            history_days=history,
            default_history_days=default_history,
            min_history_days=min_history,
            max_history_days=max_history,
        )

    def effective_history_days_for_source(self, user_id: UUID, source: str) -> int:
        return self.get_effective_preference(user_id, source).history_days

    def is_source_enabled(self, user_id: UUID, source: str) -> bool:
        return self.get_effective_preference(user_id, source).enabled

    def is_job_type_enabled(self, user_id: UUID, job_type: str) -> bool:
        from app.source_sync.constants import JOB_TYPE_TO_SOURCE

        source = JOB_TYPE_TO_SOURCE.get(job_type)
        if source is None:
            return True
        return self.is_source_enabled(user_id, source)

    def effective_interval_seconds_for_job_type(self, user_id: UUID, job_type: str) -> int:
        from app.source_sync.constants import JOB_TYPE_TO_SOURCE

        source = JOB_TYPE_TO_SOURCE.get(job_type)
        if source is None:
            return deployment_default_interval_seconds_for_job_type(job_type)
        return self.get_effective_preference(user_id, source).sync_interval_seconds

    def update_preference(
        self,
        user_id: UUID,
        source: str,
        *,
        enabled: bool | None = None,
        sync_interval_seconds: int | None = None,
        history_days: int | None = None,
        enabled_specified: bool = False,
        sync_interval_specified: bool = False,
        history_days_specified: bool = False,
    ) -> EffectiveSourceSyncPreference:
        if source not in SUPPORTED_SOURCE_KEYS:
            raise ValueError(f"unsupported source: {source}")
        if (
            not enabled_specified
            and not sync_interval_specified
            and not history_days_specified
        ):
            raise ValueError("no fields to update")
        min_seconds = max(
            MIN_SOURCE_SYNC_INTERVAL_SECONDS,
            settings.source_sync_user_min_interval_seconds,
        )
        max_seconds = max(min_seconds, settings.source_sync_user_max_interval_seconds)
        if (
            sync_interval_specified
            and sync_interval_seconds is not None
            and (
                sync_interval_seconds < min_seconds
                or sync_interval_seconds > max_seconds
            )
        ):
            raise ValueError(
                f"sync_interval_seconds must be between {min_seconds} and {max_seconds}"
            )
        min_history, max_history = _history_policy_bounds()
        if (
            history_days_specified
            and history_days is not None
            and (history_days < min_history or history_days > max_history)
        ):
            raise ValueError(
                f"history_days must be between {min_history} and {max_history}"
            )
        row = self._get_or_create_row(user_id, source)
        if enabled_specified:
            row.enabled = enabled
        if sync_interval_specified:
            row.sync_interval_seconds = sync_interval_seconds
        if history_days_specified:
            row.history_days = history_days
        if (
            row.enabled is None
            and row.sync_interval_seconds is None
            and row.history_days is None
        ):
            self._session.delete(row)
        else:
            row.updated_at = utcnow()
        self._session.flush()
        return self.get_effective_preference(user_id, source)

    def _get_row(self, user_id: UUID, source: str) -> UserSourcePreference | None:
        return self._session.get(UserSourcePreference, (user_id, source))

    def _get_or_create_row(self, user_id: UUID, source: str) -> UserSourcePreference:
        row = self._get_row(user_id, source)
        if row is not None:
            return row
        row = UserSourcePreference(user_id=user_id, source=source)
        self._session.add(row)
        self._session.flush()
        return row
