"""OpenAI Cost Guard C — per-user daily OpenAI token hard cap."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai_audit.constants import (
    EVENT_MODEL_ROUND,
    EVENT_MODEL_ROUND_FAILED,
    WORKLOAD_EMBEDDING,
)
from app.api.assistant import AssistantRuntime, get_assistant_runtime
from app.api.deps import get_db
from app.api.schemas import ObjectCreate
from app.db.models import AITrace, AITraceEvent, Job, Notification, Object, User, UserSettings
from app.jobs.constants import (
    JOB_STATUS_PENDING,
    JOB_TYPE_CORRELATE_OBJECT,
    JOB_TYPE_EMBED_OBJECT,
    JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL,
    JOB_TYPE_SYNC_GOOGLE_GMAIL,
)
from app.jobs.worker import process_one_job
from app.llm.assistant_provider_errors import OPENAI_DAILY_BUDGET_EXHAUSTED
from app.llm.auto_label_classifier import FakeAutoLabelClassifier
from app.llm.correlation_judge import FakeCorrelationJudge
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.openai_assistant_provider import OpenAIAssistantProvider
from app.llm.temporal_match_judge import FakeTemporalMatchJudge
from app.llm.temporal_signal_extractor import FakeTemporalSignalExtractor
from app.main import app
from app.services.auto_label_models import AutoLabelObjectInput
from app.services.effective_user_settings_service import EffectiveUserSettingsService
from app.services.graph_service import GraphService
from app.services.job_queue_service import JobQueueService
from app.services.openai_daily_budget import (
    BUDGET_EXHAUSTED_NOTIFICATION_TITLE,
    OPENAI_DAILY_BUDGET_PARKED_ERROR,
    OpenAIDailyBudgetExhaustedError,
    OpenAIDailyBudgetGuard,
)
from app.services.personal_semantic_context_service import PersonalSemanticContext
from app.services.temporal_signals_models import TemporalExtractionRequest
from tests.conftest import AuthTestClient


class CountingEmbeddingService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._inner = FakeEmbeddingService()

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return self._inner.embed(text)


class CountingSummarizer:
    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, text: str) -> str:
        self.calls += 1
        return "summary"


class _SessionProxy:
    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._session, name)


@pytest.fixture(autouse=True)
def _share_test_session(db_session, monkeypatch):
    """Keep audit traces, worker sessions and notifications on the test session."""
    def proxy() -> _SessionProxy:
        return _SessionProxy(db_session)

    monkeypatch.setattr("app.ai_audit.context.SessionLocal", proxy)
    monkeypatch.setattr("app.jobs.worker.SessionLocal", proxy)
    monkeypatch.setattr("app.jobs.handlers.SessionLocal", proxy)
    monkeypatch.setattr("app.api.assistant.SessionLocal", proxy)


@pytest.fixture
def budget_user_id(db_session) -> UUID:
    """A user of its own: other modules commit audit rows for the bootstrap user."""
    user_id = uuid4()
    db_session.add(User(id=user_id, display_name="Cost Guard C user"))
    db_session.flush()
    return user_id


@pytest.fixture
def budget_client(db_session, issue_bearer, budget_user_id):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    token = issue_bearer(budget_user_id, label="cost-guard-c")
    with TestClient(app) as raw:
        yield AuthTestClient(raw, {"Authorization": f"Bearer {token}"})
    app.dependency_overrides.clear()


def _guard(db_session, user_id: UUID) -> OpenAIDailyBudgetGuard:
    return OpenAIDailyBudgetGuard.build(db_session, user_id)


def _settings_row(db_session, user_id: UUID) -> UserSettings:
    row = db_session.get(UserSettings, user_id)
    if row is None:
        row = UserSettings(user_id=user_id)
        db_session.add(row)
        db_session.flush()
    return row


def _set_limit(
    db_session,
    user_id: UUID,
    limit: int | None,
    *,
    timezone: str | None = None,
) -> None:
    row = _settings_row(db_session, user_id)
    row.openai_daily_token_limit = limit
    if timezone is not None:
        row.timezone = timezone
    db_session.flush()


def _seed_usage(
    db_session,
    user_id: UUID,
    *,
    input_tokens: int | None = 0,
    output_tokens: int | None = 0,
    created_at: datetime | None = None,
    event_type: str = EVENT_MODEL_ROUND,
    extra: dict | None = None,
) -> AITraceEvent:
    """Record real-usage audit metadata exactly as the instrumentation would."""
    moment = created_at or datetime.now(UTC)
    trace = AITrace(
        user_id=user_id,
        workload=WORKLOAD_EMBEDDING,
        started_at=moment,
        success=True,
    )
    db_session.add(trace)
    db_session.flush()
    metadata = {
        "model": "text-embedding-3-small",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if extra:
        metadata.update(extra)
    event = AITraceEvent(
        trace_id=trace.id,
        user_id=user_id,
        sequence=1,
        event_type=event_type,
        metadata_=metadata,
        created_at=moment,
    )
    db_session.add(event)
    db_session.flush()
    return event


def _fake_openai_client(monkeypatch, calls: list[dict]) -> None:
    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            response = MagicMock()
            response.status = "completed"
            response.usage = MagicMock(
                input_tokens=10,
                output_tokens=5,
                input_tokens_details=None,
                output_tokens_details=None,
            )
            response.output = []
            response.output_text = "ok"
            return response

    class FakeClient:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))


def _run_provider(provider: OpenAIAssistantProvider):
    return provider.run(
        message="hello",
        history=[],
        ui_context="",
        reference_datetime=datetime.now(UTC),
        timezone="Europe/Amsterdam",
        tool_runner=lambda name, args: None,
    )


# --- gate 1: NULL limit disables the fuse -----------------------------------


def test_null_limit_allows_calls(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, None)
    _seed_usage(db_session, budget_user_id, input_tokens=10_000, output_tokens=10_000)

    service = CountingEmbeddingService()
    guarded = _guard(db_session, budget_user_id).guard_embedding_service(service)
    guarded.embed("text")

    status = _guard(db_session, budget_user_id).status()
    assert status.daily_token_limit is None
    assert status.exhausted is False
    assert service.calls == ["text"]


# --- gates 2-4: below / at / above the threshold ----------------------------


def test_usage_below_limit_allows_call(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 1_000)
    _seed_usage(db_session, budget_user_id, input_tokens=400, output_tokens=100)

    service = CountingEmbeddingService()
    _guard(db_session, budget_user_id).guard_embedding_service(service).embed("text")

    assert service.calls == ["text"]
    assert _guard(db_session, budget_user_id).status().tokens_used_today == 500


def test_usage_equal_to_limit_blocks_before_provider_call(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 500)
    _seed_usage(db_session, budget_user_id, input_tokens=400, output_tokens=100)

    service = CountingEmbeddingService()
    guarded = _guard(db_session, budget_user_id).guard_embedding_service(service)

    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        guarded.embed("text")
    assert service.calls == []


def test_usage_above_limit_blocks_before_provider_call(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 500)
    _seed_usage(db_session, budget_user_id, input_tokens=900, output_tokens=100)

    service = CountingEmbeddingService()
    guarded = _guard(db_session, budget_user_id).guard_embedding_service(service)

    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        guarded.embed("text")
    assert service.calls == []


# --- gate 5: the crossing call completes, the next one is blocked -----------


def test_call_that_crosses_threshold_completes_then_next_is_blocked(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 1_000)
    _seed_usage(db_session, budget_user_id, input_tokens=900, output_tokens=0)

    service = CountingEmbeddingService()
    guarded = _guard(db_session, budget_user_id).guard_embedding_service(service)

    guarded.embed("first")
    assert service.calls == ["first"]

    # the already-paid call reported real usage that crosses the cap
    _seed_usage(db_session, budget_user_id, input_tokens=150, output_tokens=0)

    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        guarded.embed("second")
    assert service.calls == ["first"]


# --- gate 6: no double counting of cached / reasoning tokens ----------------


def test_cached_and_reasoning_tokens_are_not_double_counted(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 1_000)
    _seed_usage(
        db_session,
        budget_user_id,
        input_tokens=100,
        output_tokens=50,
        extra={
            "cached_input_tokens": 90,
            "cache_write_tokens": 10,
            "reasoning_tokens": 40,
        },
    )

    assert _guard(db_session, budget_user_id).status().tokens_used_today == 150


def test_failed_model_rounds_still_count_real_usage(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 1_000)
    _seed_usage(
        db_session,
        budget_user_id,
        input_tokens=70,
        output_tokens=30,
        event_type=EVENT_MODEL_ROUND_FAILED,
    )

    assert _guard(db_session, budget_user_id).status().tokens_used_today == 100


def test_usage_without_reported_tokens_contributes_zero(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 1_000)
    _seed_usage(db_session, budget_user_id, input_tokens=None, output_tokens=None)

    assert _guard(db_session, budget_user_id).status().tokens_used_today == 0


# --- gate 7: local-day boundary uses the user's timezone -------------------


def test_local_day_window_uses_user_timezone(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 1_000, timezone="Asia/Tokyo")
    tokyo_start, tokyo_reset = _guard(db_session, budget_user_id).local_day_window()

    _set_limit(db_session, budget_user_id, 1_000, timezone="America/Los_Angeles")
    la_start, la_reset = _guard(db_session, budget_user_id).local_day_window()

    assert tokyo_start != la_start
    assert tokyo_reset - tokyo_start == timedelta(days=1)
    assert la_reset - la_start == timedelta(days=1)


def test_usage_just_before_local_midnight_is_not_counted(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 100, timezone="Asia/Tokyo")
    day_start, _ = _guard(db_session, budget_user_id).local_day_window()

    _seed_usage(
        db_session,
        budget_user_id,
        input_tokens=5_000,
        created_at=day_start - timedelta(minutes=1),
    )
    assert _guard(db_session, budget_user_id).status().tokens_used_today == 0

    _seed_usage(db_session, budget_user_id, input_tokens=7, created_at=day_start + timedelta(minutes=1))
    assert _guard(db_session, budget_user_id).status().tokens_used_today == 7


# --- gate 8: the next local day unlocks automatically ----------------------


def test_next_local_day_unlocks_automatically(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 100)
    day_start, reset_at = _guard(db_session, budget_user_id).local_day_window()
    _seed_usage(db_session, budget_user_id, input_tokens=500, created_at=day_start - timedelta(hours=1))

    service = CountingEmbeddingService()
    _guard(db_session, budget_user_id).guard_embedding_service(service).embed("text")

    assert service.calls == ["text"]
    assert reset_at > datetime.now(UTC)


# --- gates 9-11: threshold changes take effect immediately ----------------


def test_raising_limit_unlocks_immediately(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 100)
    _seed_usage(db_session, budget_user_id, input_tokens=150)
    service = CountingEmbeddingService()
    guarded = _guard(db_session, budget_user_id).guard_embedding_service(service)

    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        guarded.embed("blocked")

    _set_limit(db_session, budget_user_id, 10_000)
    guarded.embed("allowed")

    assert service.calls == ["allowed"]


def test_clearing_limit_unlocks_immediately(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 100)
    _seed_usage(db_session, budget_user_id, input_tokens=150)
    service = CountingEmbeddingService()
    guarded = _guard(db_session, budget_user_id).guard_embedding_service(service)

    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        guarded.embed("blocked")

    _set_limit(db_session, budget_user_id, None)
    guarded.embed("allowed")

    assert service.calls == ["allowed"]


def test_lowering_limit_below_usage_blocks_next_call(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 10_000)
    _seed_usage(db_session, budget_user_id, input_tokens=150)
    service = CountingEmbeddingService()
    guarded = _guard(db_session, budget_user_id).guard_embedding_service(service)

    guarded.embed("allowed")

    _set_limit(db_session, budget_user_id, 100)
    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        guarded.embed("blocked")

    assert service.calls == ["allowed"]


# --- gate 12: interactive assistant blocked locally, zero provider calls ---


def test_assistant_provider_blocked_before_any_openai_call(db_session, monkeypatch, budget_user_id) -> None:
    calls: list[dict] = []
    _fake_openai_client(monkeypatch, calls)
    _set_limit(db_session, budget_user_id, 100)
    _seed_usage(db_session, budget_user_id, input_tokens=150)

    provider = _guard(db_session, budget_user_id).guard_assistant_provider(
        OpenAIAssistantProvider(api_key="test", model="gpt-5.6-luna")
    )

    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        _run_provider(provider)
    assert calls == []


def test_assistant_provider_allowed_when_under_limit(db_session, monkeypatch, budget_user_id) -> None:
    calls: list[dict] = []
    _fake_openai_client(monkeypatch, calls)
    _set_limit(db_session, budget_user_id, 10_000)

    provider = _guard(db_session, budget_user_id).guard_assistant_provider(
        OpenAIAssistantProvider(api_key="test", model="gpt-5.6-luna")
    )
    result = _run_provider(provider)

    assert result.answer == "ok"
    assert len(calls) == 1


def test_assistant_message_returns_typed_budget_error(
    db_session,
    budget_user_id,
    issue_bearer,
    fake_embedding_service,
    monkeypatch,
) -> None:
    from tests.conftest import apply_embedding_service_overrides

    calls: list[dict] = []
    _fake_openai_client(monkeypatch, calls)
    _set_limit(db_session, budget_user_id, 100)
    _seed_usage(db_session, budget_user_id, input_tokens=150)

    provider = _guard(db_session, budget_user_id).guard_assistant_provider(
        OpenAIAssistantProvider(api_key="test", model="gpt-5.6-luna")
    )
    effective = EffectiveUserSettingsService.build(db_session).get_settings_view(
        budget_user_id
    )

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_assistant_runtime] = lambda: AssistantRuntime(
        provider=provider,
        effective=effective,
    )
    apply_embedding_service_overrides(fake_embedding_service)
    token = issue_bearer(budget_user_id, label="cost-guard-c")
    try:
        with TestClient(app) as raw:
            client = AuthTestClient(raw, {"Authorization": f"Bearer {token}"})
            response = client.post("/assistant/message", json={"message": "привет"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["code"] == OPENAI_DAILY_BUDGET_EXHAUSTED
    assert detail["daily_token_limit"] == 100
    assert detail["tokens_used_today"] == 150
    assert detail["exhausted"] is True
    assert detail["reset_at"]
    assert calls == []


# --- gates 13-14: embeddings, correlation and auto-label all blocked -------


def test_blocked_embedding_makes_zero_provider_calls(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=10)

    service = CountingEmbeddingService()
    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        _guard(db_session, budget_user_id).guard_embedding_service(service).embed("text")
    assert service.calls == []


def test_blocked_correlation_judge_makes_zero_provider_calls(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=10)

    judge = FakeCorrelationJudge()
    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        _guard(db_session, budget_user_id).guard_correlation_judge(judge).judge("t", "note", "s", [])
    assert judge.calls == 0


def test_blocked_auto_label_classifier_makes_zero_provider_calls(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=10)

    classifier = FakeAutoLabelClassifier()
    guarded = _guard(db_session, budget_user_id).guard_auto_label_classifier(classifier)
    obj_input = AutoLabelObjectInput(
        object_id=budget_user_id,
        kind="note",
        title="t",
        provider=None,
        content="c",
        content_source="body",
    )
    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        guarded.classify(
            obj=obj_input,
            candidates=[],
            personal=PersonalSemanticContext(),
        )
    assert classifier.calls == 0


def test_blocked_summarizer_makes_zero_provider_calls(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=10)

    summarizer = CountingSummarizer()
    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        _guard(db_session, budget_user_id).guard_summarizer(summarizer).summarize("text")
    assert summarizer.calls == 0


def test_blocked_temporal_extractor_makes_zero_provider_calls(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=10)

    extractor = FakeTemporalSignalExtractor()
    request = TemporalExtractionRequest(
        object_id=budget_user_id,
        kind="email",
        provider="gmail",
        title="t",
        body="b",
        source_reference_at=datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
        timezone="Europe/Moscow",
        participation_roles=(),
        is_channel_message=False,
        has_other_participants=True,
    )
    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        _guard(db_session, budget_user_id).guard_temporal_signal_extractor(extractor).extract(
            request
        )
    assert extractor.calls == 0


def test_blocked_temporal_match_judge_makes_zero_provider_calls(
    db_session, budget_user_id
) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=10)

    judge = FakeTemporalMatchJudge()
    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        _guard(db_session, budget_user_id).guard_temporal_match_judge(judge).judge(
            trigger_title="t",
            trigger_subject="s",
            trigger_kind="event",
            candidates=[],
        )
    assert judge.calls == 0


def test_blocked_transcription_makes_zero_provider_calls(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=10)

    class CountingTranscription:
        model = "gpt-4o-mini-transcribe"

        def __init__(self) -> None:
            self.calls = 0

        def transcribe(self, audio_bytes, filename, content_type):
            self.calls += 1
            return "text"

    provider = CountingTranscription()
    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        _guard(db_session, budget_user_id).guard_transcription_provider(provider).transcribe(
            b"audio", "a.wav", "audio/wav"
        )
    assert provider.calls == 0


def test_blocked_speech_makes_zero_provider_calls(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=10)

    class CountingSpeech:
        model = "gpt-4o-mini-tts"

        def __init__(self) -> None:
            self.calls = 0

        def synthesize(self, text):
            self.calls += 1
            return b"audio"

    provider = CountingSpeech()
    with pytest.raises(OpenAIDailyBudgetExhaustedError):
        _guard(db_session, budget_user_id).guard_speech_provider(provider).synthesize("привет")
    assert provider.calls == 0


def test_request_time_embedding_defers_instead_of_clearing_vector(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=10)

    graph = GraphService(db_session, budget_user_id)
    obj = graph.create_object(ObjectCreate(kind="note", title="Note", origin="user"))
    db_session.flush()

    guarded = _guard(db_session, budget_user_id).guard_embedding_service(CountingEmbeddingService())
    obj.title = "Note changed"
    db_session.flush()

    from app.services.embedding_index import refresh_object_embedding

    refresh_object_embedding(obj, guarded)

    live = db_session.get(Object, obj.id)
    assert live.embedding_signature is None
    queued = db_session.scalars(
        select(Job).where(
            Job.user_id == budget_user_id,
            Job.type == JOB_TYPE_EMBED_OBJECT,
            Job.status == JOB_STATUS_PENDING,
        )
    ).all()
    assert any(job.payload.get("object_id") == str(obj.id) for job in queued)


# --- gate 15: background AI work is parked, not hot-retried or lost -------


def test_background_ai_job_is_parked_without_burning_retries(db_session, monkeypatch, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=10)
    queue = JobQueueService(db_session)
    job = queue.enqueue(JOB_TYPE_EMBED_OBJECT, {"object_id": str(budget_user_id)}, budget_user_id)
    job_id = job.id
    status = _guard(db_session, budget_user_id).status()

    def blocked_handler(session, embedding_service, payload, user_id):
        raise OpenAIDailyBudgetExhaustedError(status)

    monkeypatch.setattr("app.jobs.worker.get_handler", lambda job_type: blocked_handler)

    assert process_one_job() is True

    db_session.expire_all()
    parked = db_session.get(Job, job_id)
    assert parked.status == JOB_STATUS_PENDING
    assert parked.attempts == 0
    assert parked.last_error == OPENAI_DAILY_BUDGET_PARKED_ERROR
    assert parked.run_after >= status.reset_at

    # no hot retry loop: the parked job is not claimable again today
    assert process_one_job() is False


def test_background_temporal_job_is_parked_without_burning_retries(
    db_session, monkeypatch, budget_user_id
) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=10)
    queue = JobQueueService(db_session)
    job = queue.enqueue(
        JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL,
        {"object_id": str(budget_user_id)},
        budget_user_id,
    )
    job_id = job.id
    status = _guard(db_session, budget_user_id).status()

    def blocked_handler(session, embedding_service, payload, user_id):
        raise OpenAIDailyBudgetExhaustedError(status)

    monkeypatch.setattr("app.jobs.worker.get_handler", lambda job_type: blocked_handler)

    assert process_one_job() is True

    db_session.expire_all()
    parked = db_session.get(Job, job_id)
    assert parked.status == JOB_STATUS_PENDING
    assert parked.attempts == 0
    assert parked.last_error == OPENAI_DAILY_BUDGET_PARKED_ERROR
    assert parked.run_after >= status.reset_at
    assert process_one_job() is False


def test_raising_limit_releases_budget_parked_jobs(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 10)
    queue = JobQueueService(db_session)
    job = queue.enqueue(JOB_TYPE_CORRELATE_OBJECT, {"object_id": str(budget_user_id)}, budget_user_id)
    _, reset_at = _guard(db_session, budget_user_id).local_day_window()
    queue.park_until_openai_budget_reset(job.id, reset_at)

    released = JobQueueService(db_session).release_budget_parked_jobs(budget_user_id)

    db_session.expire_all()
    resumed = db_session.get(Job, job.id)
    assert released == 1
    assert resumed.status == JOB_STATUS_PENDING
    assert resumed.last_error is None
    assert resumed.run_after <= datetime.now(UTC)


# --- gate 16: source synchronization keeps running -------------------------


def test_source_sync_still_runs_while_ai_budget_exhausted(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=10)
    queue = JobQueueService(db_session)
    ai_job = queue.enqueue(JOB_TYPE_EMBED_OBJECT, {"object_id": str(budget_user_id)}, budget_user_id)
    _, reset_at = _guard(db_session, budget_user_id).local_day_window()
    queue.park_until_openai_budget_reset(ai_job.id, reset_at)
    sync_job = queue.enqueue(
        JOB_TYPE_SYNC_GOOGLE_GMAIL,
        {"account_id": str(budget_user_id)},
        budget_user_id,
    )

    claimed = JobQueueService(db_session).claim_next()

    assert claimed is not None
    assert claimed.id == sync_job.id
    assert claimed.type == JOB_TYPE_SYNC_GOOGLE_GMAIL


# --- gate 17: at most one warning per local day ---------------------------


def test_exhausted_warning_is_created_at_most_once_per_local_day(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=10)
    guard = _guard(db_session, budget_user_id)

    assert guard.ensure_exhausted_notification() is True
    assert guard.ensure_exhausted_notification() is False
    assert _guard(db_session, budget_user_id).ensure_exhausted_notification() is False

    count = db_session.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == budget_user_id,
            Notification.title == BUDGET_EXHAUSTED_NOTIFICATION_TITLE,
        )
    )
    assert count == 1


# --- profile read / write --------------------------------------------------


def test_settings_api_reads_and_updates_daily_token_limit(
    budget_client,
    db_session,
    budget_user_id,
) -> None:
    _set_limit(db_session, budget_user_id, None)
    _seed_usage(db_session, budget_user_id, input_tokens=120, output_tokens=30)

    initial = budget_client.get("/me/settings")
    assert initial.status_code == 200
    assert initial.json()["openai_daily_token_limit"] is None
    assert initial.json()["openai_daily_budget"]["tokens_used_today"] == 150
    assert initial.json()["openai_daily_budget"]["exhausted"] is False

    updated = budget_client.patch(
        "/me/settings",
        json={"openai_daily_token_limit": 100},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["openai_daily_token_limit"] == 100
    assert body["openai_daily_budget"]["exhausted"] is True
    assert body["openai_daily_budget"]["daily_token_limit"] == 100
    assert body["openai_daily_budget"]["reset_at"]

    cleared = budget_client.patch("/me/settings", json={"openai_daily_token_limit": None})
    assert cleared.status_code == 200
    assert cleared.json()["openai_daily_token_limit"] is None
    assert cleared.json()["openai_daily_budget"]["exhausted"] is False


def test_settings_api_rejects_non_positive_daily_token_limit(budget_client) -> None:
    response = budget_client.patch("/me/settings", json={"openai_daily_token_limit": 0})
    assert response.status_code == 422


def test_settings_patch_releases_budget_parked_jobs(
    budget_client,
    db_session,
    budget_user_id,
) -> None:
    _set_limit(db_session, budget_user_id, 10)
    _seed_usage(db_session, budget_user_id, input_tokens=50)
    queue = JobQueueService(db_session)
    job = queue.enqueue(JOB_TYPE_EMBED_OBJECT, {"object_id": str(budget_user_id)}, budget_user_id)
    _, reset_at = _guard(db_session, budget_user_id).local_day_window()
    queue.park_until_openai_budget_reset(job.id, reset_at)

    response = budget_client.patch(
        "/me/settings",
        json={"openai_daily_token_limit": 1_000_000},
    )
    assert response.status_code == 200

    db_session.expire_all()
    resumed = db_session.get(Job, job.id)
    assert resumed.last_error is None
    assert resumed.run_after <= datetime.now(UTC)


def test_budget_is_isolated_per_user(db_session, nornickel_user_id, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 100)
    _set_limit(db_session, nornickel_user_id, 100)
    _seed_usage(db_session, budget_user_id, input_tokens=500)

    assert _guard(db_session, budget_user_id).status().exhausted is True
    assert _guard(db_session, nornickel_user_id).status().exhausted is False
