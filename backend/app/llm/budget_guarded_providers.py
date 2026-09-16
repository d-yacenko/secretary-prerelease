"""Budget-guarded decorators around the paid OpenAI providers.

Every wrapper does exactly two things and no business logic: ask the single
`OpenAIDailyBudgetGuard` for permission before the provider call, and guarantee
that an AI audit trace is active so the provider's own real usage recording
contributes to the daily total.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from app.ai_audit.constants import (
    WORKLOAD_BACKGROUND_AUTO_LABEL,
    WORKLOAD_BACKGROUND_CORRELATION,
    WORKLOAD_BACKGROUND_SUMMARY,
    WORKLOAD_BACKGROUND_TEMPORAL_SIGNAL,
    WORKLOAD_EMBEDDING,
)
from app.ai_audit.context import ai_trace_session, get_active_trace

if TYPE_CHECKING:
    from app.services.openai_daily_budget import OpenAIDailyBudgetGuard


@contextmanager
def _usage_recorded(guard: OpenAIDailyBudgetGuard, workload: str) -> Iterator[None]:
    """Ensure provider usage lands in the audit even on paths without a trace."""
    if get_active_trace() is not None:
        yield
        return
    with ai_trace_session(guard.user_id, workload):
        yield


class _BudgetGuarded:
    def __init__(self, inner, guard: OpenAIDailyBudgetGuard) -> None:
        self._inner = inner
        self._guard = guard

    @property
    def inner(self):
        """The wrapped paid provider, for callers that inspect provider identity."""
        return self._inner


class BudgetGuardedEmbeddingService(_BudgetGuarded):
    def embed(self, text: str) -> list[float]:
        self._guard.ensure_allowed()
        with _usage_recorded(self._guard, WORKLOAD_EMBEDDING):
            return self._inner.embed(text)


class BudgetGuardedSummarizer(_BudgetGuarded):
    def summarize(self, text: str) -> str:
        self._guard.ensure_allowed()
        with _usage_recorded(self._guard, WORKLOAD_BACKGROUND_SUMMARY):
            return self._inner.summarize(text)


class BudgetGuardedCorrelationJudge(_BudgetGuarded):
    def judge(self, trigger_title, trigger_kind, trigger_summary, candidates):
        self._guard.ensure_allowed()
        with _usage_recorded(self._guard, WORKLOAD_BACKGROUND_CORRELATION):
            return self._inner.judge(
                trigger_title,
                trigger_kind,
                trigger_summary,
                candidates,
            )


class BudgetGuardedAutoLabelClassifier(_BudgetGuarded):
    def classify(self, *, obj, candidates, personal):
        self._guard.ensure_allowed()
        with _usage_recorded(self._guard, WORKLOAD_BACKGROUND_AUTO_LABEL):
            return self._inner.classify(obj=obj, candidates=candidates, personal=personal)


class BudgetGuardedTemporalSignalExtractor(_BudgetGuarded):
    def extract(self, request):
        self._guard.ensure_allowed()
        with _usage_recorded(self._guard, WORKLOAD_BACKGROUND_TEMPORAL_SIGNAL):
            return self._inner.extract(request)


class BudgetGuardedTemporalMatchJudge(_BudgetGuarded):
    def judge(
        self,
        *,
        trigger_title,
        trigger_subject,
        trigger_kind,
        candidates,
        operation="temporal_match",
    ):
        self._guard.ensure_allowed()
        with _usage_recorded(self._guard, WORKLOAD_BACKGROUND_TEMPORAL_SIGNAL):
            return self._inner.judge(
                trigger_title=trigger_title,
                trigger_subject=trigger_subject,
                trigger_kind=trigger_kind,
                candidates=candidates,
                operation=operation,
            )


class BudgetGuardedTranscriptionProvider(_BudgetGuarded):
    @property
    def model(self) -> str | None:
        return getattr(self._inner, "model", None)

    def transcribe(self, audio_bytes: bytes, filename: str, content_type: str | None) -> str:
        self._guard.ensure_allowed()
        # HTTP transcription already opens the audit trace in the request
        # task, then runs this method in a threadpool where that contextvar is
        # not visible. Opening a second SessionLocal trace here would FK-fail
        # for uncommitted test users and would double-count production usage
        # that transcription_service records after the thread returns.
        return self._inner.transcribe(audio_bytes, filename, content_type)


class BudgetGuardedSpeechProvider(_BudgetGuarded):
    @property
    def model(self) -> str | None:
        return getattr(self._inner, "model", None)

    def synthesize(self, text: str):
        self._guard.ensure_allowed()
        # HTTP speech already opens the audit trace in the request task, then
        # runs this method in a threadpool where that contextvar is not visible.
        return self._inner.synthesize(text)
