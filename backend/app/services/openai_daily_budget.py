"""Per-user daily OpenAI token hard cap (OpenAI Cost Guard C).

One policy service owns the whole fuse: the local-day window, the actual-usage
read, the allow/block decision, the once-per-day user warning, and the local-day
reset instant used to park background AI work.

Accounting reuses the existing AI audit as the source of real provider usage.
Only `input_tokens + output_tokens` are charged: `cached_input_tokens` and
`cache_write_tokens` are subsets of the reported input total and
`reasoning_tokens` is a subset of the reported output total, so adding them
again would double-count. No token value is ever estimated from character
counts; paths where OpenAI reports no token usage contribute zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Numeric, case, cast, func, select
from sqlalchemy.orm import Session

from app.ai_audit.constants import EVENT_MODEL_ROUND, EVENT_MODEL_ROUND_FAILED
from app.db.models import AITraceEvent, Notification, UserSettings
from app.notifications.constants import NOTIFICATION_STATUS_NEW
from app.services.errors import ValidationError

MIN_OPENAI_DAILY_TOKEN_LIMIT = 1
MAX_OPENAI_DAILY_TOKEN_LIMIT = 1_000_000_000

BUDGET_USAGE_EVENT_TYPES = (EVENT_MODEL_ROUND, EVENT_MODEL_ROUND_FAILED)
BUDGET_USAGE_FIELDS = ("input_tokens", "output_tokens")

OPENAI_DAILY_BUDGET_PARKED_ERROR = "openai daily token budget exhausted"

BUDGET_EXHAUSTED_NOTIFICATION_TITLE = "Дневной лимит OpenAI исчерпан"
BUDGET_EXHAUSTED_NOTIFICATION_BODY = (
    "Дневной лимит OpenAI исчерпан. AI-функции временно остановлены."
)
BUDGET_EXHAUSTED_NOTIFICATION_PRIORITY = "high"


@dataclass(frozen=True)
class OpenAIDailyBudgetStatus:
    daily_token_limit: int | None
    tokens_used_today: int
    exhausted: bool
    day_start: datetime
    reset_at: datetime

    def to_payload(self) -> dict:
        return {
            "daily_token_limit": self.daily_token_limit,
            "tokens_used_today": self.tokens_used_today,
            "exhausted": self.exhausted,
            "reset_at": self.reset_at.isoformat(),
        }


class OpenAIDailyBudgetExhaustedError(Exception):
    """Raised instead of making a paid OpenAI call once the daily cap is reached."""

    def __init__(self, status: OpenAIDailyBudgetStatus) -> None:
        self.status = status
        super().__init__(OPENAI_DAILY_BUDGET_PARKED_ERROR)

    @property
    def reset_at(self) -> datetime:
        return self.status.reset_at


def validate_openai_daily_token_limit(value: int) -> int:
    if value < MIN_OPENAI_DAILY_TOKEN_LIMIT or value > MAX_OPENAI_DAILY_TOKEN_LIMIT:
        raise ValidationError(
            "openai_daily_token_limit must be between "
            f"{MIN_OPENAI_DAILY_TOKEN_LIMIT} and {MAX_OPENAI_DAILY_TOKEN_LIMIT}"
        )
    return value


def _usage_token_expression(field: str):
    value = AITraceEvent.metadata_[field]
    return case(
        (func.jsonb_typeof(value) == "number", cast(value.astext, Numeric)),
        else_=0,
    )


class OpenAIDailyBudgetGuard:
    """Single allow/block authority in front of every paid OpenAI call."""

    def __init__(
        self,
        session: Session,
        user_id: UUID,
        *,
        timezone: str | None = None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._timezone = timezone

    @property
    def user_id(self) -> UUID:
        return self._user_id

    def ensure_allowed(self, extra_tokens: int = 0) -> OpenAIDailyBudgetStatus:
        """Allow or block before a paid provider call.

        `extra_tokens` is Assistant's already-charged Responses usage for the
        current turn. Those same tokens are also recorded on the active trace.
        The guard takes the larger of extra vs in-flight so they are never
        summed twice, while still covering tool/embedding usage recorded on the
        same unfinished trace.
        """
        status = self.status(extra_tokens=extra_tokens)
        if status.exhausted:
            raise OpenAIDailyBudgetExhaustedError(status)
        return status

    def status(self, extra_tokens: int = 0) -> OpenAIDailyBudgetStatus:
        from app.ai_audit.context import (
            active_trace_in_flight_budget_tokens,
            get_active_trace,
        )

        day_start, reset_at = self.local_day_window()
        limit = self.daily_token_limit()
        active = get_active_trace()
        exclude_trace_id = active.trace_id if active is not None else None
        used = self.tokens_used_between(
            day_start, reset_at, exclude_trace_id=exclude_trace_id
        )
        in_flight = active_trace_in_flight_budget_tokens()
        extra = max(extra_tokens, 0)
        # Assistant extra_tokens and ActiveTrace in-flight describe the same
        # already-recorded rounds; take max so they are not double-counted.
        used += max(extra, in_flight)
        exhausted = limit is not None and used >= limit
        return OpenAIDailyBudgetStatus(
            daily_token_limit=limit,
            tokens_used_today=used,
            exhausted=exhausted,
            day_start=day_start,
            reset_at=reset_at,
        )

    def daily_token_limit(self) -> int | None:
        row = self._session.get(UserSettings, self._user_id)
        if row is None or row.openai_daily_token_limit is None:
            return None
        stored = int(row.openai_daily_token_limit)
        if stored < MIN_OPENAI_DAILY_TOKEN_LIMIT:
            return None
        return stored

    def tokens_used_between(
        self,
        start: datetime,
        end: datetime,
        *,
        exclude_trace_id: UUID | None = None,
    ) -> int:
        charged = _usage_token_expression(BUDGET_USAGE_FIELDS[0])
        for field in BUDGET_USAGE_FIELDS[1:]:
            charged = charged + _usage_token_expression(field)
        conditions = [
            AITraceEvent.user_id == self._user_id,
            AITraceEvent.event_type.in_(BUDGET_USAGE_EVENT_TYPES),
            AITraceEvent.created_at >= start,
            AITraceEvent.created_at < end,
        ]
        if exclude_trace_id is not None:
            conditions.append(AITraceEvent.trace_id != exclude_trace_id)
        total = self._session.scalar(
            select(func.coalesce(func.sum(charged), 0)).where(*conditions)
        )
        return int(total or 0)

    def local_day_window(self) -> tuple[datetime, datetime]:
        zone = self._zone()
        today = datetime.now(UTC).astimezone(zone).date()
        start_local = datetime.combine(today, time.min, tzinfo=zone)
        end_local = datetime.combine(today + timedelta(days=1), time.min, tzinfo=zone)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)

    def ensure_exhausted_notification(self, session: Session | None = None) -> bool:
        """Create at most one user-visible warning per local day. No OpenAI call."""
        target = session if session is not None else self._session
        day_start, _ = self.local_day_window()
        existing = target.scalar(
            select(Notification.id)
            .where(
                Notification.user_id == self._user_id,
                Notification.title == BUDGET_EXHAUSTED_NOTIFICATION_TITLE,
                Notification.created_at >= day_start,
            )
            .limit(1)
        )
        if existing is not None:
            return False
        target.add(
            Notification(
                user_id=self._user_id,
                title=BUDGET_EXHAUSTED_NOTIFICATION_TITLE,
                body=BUDGET_EXHAUSTED_NOTIFICATION_BODY,
                priority=BUDGET_EXHAUSTED_NOTIFICATION_PRIORITY,
                status=NOTIFICATION_STATUS_NEW,
                proposal_={},
            )
        )
        target.flush()
        return True

    def guard_assistant_provider(self, provider):
        """Install the per-round budget check on a real OpenAI Assistant provider."""
        if hasattr(provider, "budget_round_check"):
            provider.budget_round_check = self.ensure_allowed
        return provider

    def guard_embedding_service(self, service):
        from app.llm.budget_guarded_providers import BudgetGuardedEmbeddingService

        return BudgetGuardedEmbeddingService(service, self)

    def guard_summarizer(self, summarizer):
        from app.llm.budget_guarded_providers import BudgetGuardedSummarizer

        return BudgetGuardedSummarizer(summarizer, self)

    def guard_correlation_judge(self, judge):
        from app.llm.budget_guarded_providers import BudgetGuardedCorrelationJudge

        return BudgetGuardedCorrelationJudge(judge, self)

    def guard_auto_label_classifier(self, classifier):
        from app.llm.budget_guarded_providers import BudgetGuardedAutoLabelClassifier

        return BudgetGuardedAutoLabelClassifier(classifier, self)

    def guard_transcription_provider(self, provider):
        from app.llm.budget_guarded_providers import BudgetGuardedTranscriptionProvider

        return BudgetGuardedTranscriptionProvider(provider, self)

    def guard_speech_provider(self, provider):
        from app.llm.budget_guarded_providers import BudgetGuardedSpeechProvider

        return BudgetGuardedSpeechProvider(provider, self)

    def guard_temporal_signal_extractor(self, extractor):
        from app.llm.budget_guarded_providers import BudgetGuardedTemporalSignalExtractor

        return BudgetGuardedTemporalSignalExtractor(extractor, self)

    def guard_temporal_match_judge(self, judge):
        from app.llm.budget_guarded_providers import BudgetGuardedTemporalMatchJudge

        return BudgetGuardedTemporalMatchJudge(judge, self)

    def _zone(self) -> ZoneInfo:
        from app.services.effective_user_settings_service import resolve_user_timezone

        name = self._timezone or resolve_user_timezone(self._session, self._user_id)
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    @staticmethod
    def build(session: Session, user_id: UUID) -> OpenAIDailyBudgetGuard:
        return OpenAIDailyBudgetGuard(session, user_id)
