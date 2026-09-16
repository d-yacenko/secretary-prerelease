"""OpenAI Cost Guard C-R1 — in-flight usage, transcription tokens, timezone release."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.ai_audit.constants import WORKLOAD_EMBEDDING, WORKLOAD_TRANSCRIPTION
from app.ai_audit.context import ai_trace_session
from app.ai_audit.instrumentation import record_simple_model_call
from app.api.deps import get_db
from app.db.models import Job, User
from app.jobs.constants import JOB_STATUS_PENDING, JOB_TYPE_EMBED_OBJECT
from app.jobs.handlers import _embed_chunk_targets
from app.llm.openai_transcription_provider import (
    TranscriptionCallResult,
    extract_transcription_token_usage,
)
from app.main import app
from app.services.job_queue_service import JobQueueService
from app.services.openai_daily_budget import (
    OPENAI_DAILY_BUDGET_PARKED_ERROR,
    OpenAIDailyBudgetExhaustedError,
)
from tests.conftest import AuthTestClient
from tests.test_openai_cost_guard_c import (
    CountingEmbeddingService,
    _guard,
    _seed_usage,
    _SessionProxy,
    _set_limit,
)


@pytest.fixture(autouse=True)
def _share_test_session(db_session, monkeypatch):
    def proxy() -> _SessionProxy:
        return _SessionProxy(db_session)

    monkeypatch.setattr("app.ai_audit.context.SessionLocal", proxy)
    monkeypatch.setattr("app.jobs.worker.SessionLocal", proxy)
    monkeypatch.setattr("app.jobs.handlers.SessionLocal", proxy)
    monkeypatch.setattr("app.api.assistant.SessionLocal", proxy)


@pytest.fixture
def budget_user_id(db_session):
    user_id = uuid4()
    db_session.add(User(id=user_id, display_name="Cost Guard C-R1 user"))
    db_session.flush()
    return user_id


@pytest.fixture
def budget_client(db_session, issue_bearer, budget_user_id):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    token = issue_bearer(budget_user_id, label="cost-guard-c-r1")
    with TestClient(app) as raw:
        yield AuthTestClient(raw, {"Authorization": f"Bearer {token}"})
    app.dependency_overrides.clear()


class TokenRecordingEmbedding:
    def __init__(self, tokens_per_call: int = 80) -> None:
        self.calls: list[str] = []
        self.tokens_per_call = tokens_per_call
        self._inner = CountingEmbeddingService()

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        record_simple_model_call(
            model="text-embedding-3-small",
            input_chars=len(text),
            output_chars=0,
            elapsed_ms=1,
            extra={"input_tokens": self.tokens_per_call},
        )
        return self._inner.embed(text)


class FailingTokenEmbedding:
    def __init__(self, tokens: int = 80) -> None:
        self.calls = 0
        self.tokens = tokens

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        record_simple_model_call(
            model="text-embedding-3-small",
            input_chars=len(text),
            output_chars=0,
            elapsed_ms=1,
            failed=True,
            error_category="ProviderError",
            extra={"input_tokens": self.tokens, "output_tokens": 0},
        )
        raise RuntimeError("provider failed")


def test_second_sequential_call_in_same_trace_is_blocked(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 100)
    _seed_usage(db_session, budget_user_id, input_tokens=40)
    inner = TokenRecordingEmbedding(tokens_per_call=80)
    guarded = _guard(db_session, budget_user_id).guard_embedding_service(inner)

    with ai_trace_session(budget_user_id, WORKLOAD_EMBEDDING, session=db_session):
        guarded.embed("first")
        with pytest.raises(OpenAIDailyBudgetExhaustedError):
            guarded.embed("second")

    assert inner.calls == ["first"]


def test_embedding_chunk_loop_blocks_after_crossing_limit(db_session, budget_user_id, monkeypatch) -> None:
    _set_limit(db_session, budget_user_id, 100)
    _seed_usage(db_session, budget_user_id, input_tokens=40)
    inner = TokenRecordingEmbedding(tokens_per_call=80)
    guarded = _guard(db_session, budget_user_id).guard_embedding_service(inner)

    class Target:
        def __init__(self, text: str) -> None:
            self.representation_id = uuid4()
            self.text = text

    monkeypatch.setattr(
        "app.jobs.handlers.load_unembedded_chunk_targets",
        lambda object_id, user_id: [Target("chunk-a"), Target("chunk-b")],
    )
    stored: list = []
    monkeypatch.setattr(
        "app.jobs.handlers.store_representation_embeddings",
        lambda object_id, user_id, embeddings: stored.extend(embeddings),
    )

    with (
        ai_trace_session(budget_user_id, WORKLOAD_EMBEDDING, session=db_session),
        pytest.raises(OpenAIDailyBudgetExhaustedError),
    ):
        _embed_chunk_targets(guarded, uuid4(), budget_user_id)

    assert inner.calls == ["chunk-a"]
    assert stored == []


def test_failed_call_with_reported_tokens_counts_in_flight(db_session, budget_user_id) -> None:
    _set_limit(db_session, budget_user_id, 100)
    _seed_usage(db_session, budget_user_id, input_tokens=40)
    failing = FailingTokenEmbedding(tokens=80)
    next_call = TokenRecordingEmbedding(tokens_per_call=1)
    guard = _guard(db_session, budget_user_id)

    with ai_trace_session(budget_user_id, WORKLOAD_EMBEDDING, session=db_session):
        with pytest.raises(RuntimeError, match="provider failed"):
            guard.guard_embedding_service(failing).embed("boom")
        with pytest.raises(OpenAIDailyBudgetExhaustedError):
            guard.guard_embedding_service(next_call).embed("next")

    assert failing.calls == 1
    assert next_call.calls == []


def test_extract_transcription_token_usage_from_sdk_tokens_variant() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(type="tokens", input_tokens=90, output_tokens=12)
    )
    assert extract_transcription_token_usage(response) == (90, 12)


def test_extract_transcription_duration_usage_is_not_estimated() -> None:
    response = SimpleNamespace(usage=SimpleNamespace(type="duration", seconds=3.5))
    assert extract_transcription_token_usage(response) == (None, None)


def test_transcription_actual_usage_blocks_the_next_paid_call(
    db_session, budget_user_id
) -> None:
    from app.services.transcription_service import transcribe_audio_upload

    _set_limit(db_session, budget_user_id, 100)
    _seed_usage(db_session, budget_user_id, input_tokens=20)

    class UsageTranscription:
        model = "gpt-4o-mini-transcribe"
        calls = 0

        def transcribe(self, audio_bytes, filename, content_type):
            self.calls += 1
            return TranscriptionCallResult(
                text="hello",
                input_tokens=70,
                output_tokens=15,
            )

    class FakeUpload:
        filename = "clip.wav"
        content_type = "audio/wav"

        async def read(self, size: int) -> bytes:
            return b"audio-bytes"

    provider = UsageTranscription()
    next_call = TokenRecordingEmbedding(tokens_per_call=1)
    guard = _guard(db_session, budget_user_id)

    async def _run() -> None:
        with ai_trace_session(budget_user_id, WORKLOAD_TRANSCRIPTION, session=db_session):
            text = await transcribe_audio_upload(FakeUpload(), provider)
            assert text == "hello"
            with pytest.raises(OpenAIDailyBudgetExhaustedError):
                guard.guard_embedding_service(next_call).embed("after-transcribe")

    asyncio.run(_run())
    assert provider.calls == 1
    assert next_call.calls == []
    assert guard.status().tokens_used_today == 20 + 70 + 15


def test_openai_transcription_provider_preserves_token_usage(monkeypatch) -> None:
    from app.llm.openai_transcription_provider import OpenAITranscriptionProvider

    class FakeAudio:
        def create(self, **kwargs):
            return SimpleNamespace(
                text="recognized",
                usage=SimpleNamespace(type="tokens", input_tokens=44, output_tokens=6),
            )

    class FakeClient:
        def __init__(self, api_key):
            self.audio = SimpleNamespace(transcriptions=FakeAudio())

    monkeypatch.setattr("openai.OpenAI", lambda api_key: FakeClient(api_key))
    result = OpenAITranscriptionProvider(api_key="sk-test", model="gpt-4o-mini-transcribe").transcribe(
        b"bytes", "clip.wav", "audio/wav"
    )
    assert result == TranscriptionCallResult(
        text="recognized",
        input_tokens=44,
        output_tokens=6,
    )


def test_timezone_change_releases_parked_jobs_off_old_reset(
    db_session, budget_user_id, budget_client
) -> None:
    _set_limit(db_session, budget_user_id, 10, timezone="UTC")
    _seed_usage(db_session, budget_user_id, input_tokens=10)
    queue = JobQueueService(db_session)
    job = queue.enqueue(JOB_TYPE_EMBED_OBJECT, {"object_id": str(budget_user_id)}, budget_user_id)
    old_reset = datetime.now(UTC) + timedelta(days=1)
    queue.park_until_openai_budget_reset(job.id, old_reset)
    job_id = job.id

    response = budget_client.patch("/me/settings", json={"timezone": "Pacific/Auckland"})
    assert response.status_code == 200

    db_session.expire_all()
    released = db_session.get(Job, job_id)
    assert released.status == JOB_STATUS_PENDING
    assert released.last_error is None
    assert released.run_after <= datetime.now(UTC)


def test_timezone_change_lets_worker_repark_with_new_reset(
    db_session, budget_user_id, budget_client
) -> None:
    _set_limit(db_session, budget_user_id, 10, timezone="UTC")
    _seed_usage(db_session, budget_user_id, input_tokens=10)
    queue = JobQueueService(db_session)
    job = queue.enqueue(JOB_TYPE_EMBED_OBJECT, {"object_id": str(budget_user_id)}, budget_user_id)
    old_reset = datetime.now(UTC) + timedelta(hours=20)
    queue.park_until_openai_budget_reset(job.id, old_reset)
    job_id = job.id

    response = budget_client.patch("/me/settings", json={"timezone": "America/Los_Angeles"})
    assert response.status_code == 200

    db_session.expire_all()
    released = db_session.get(Job, job_id)
    assert released.last_error is None
    assert released.run_after <= datetime.now(UTC)

    with pytest.raises(OpenAIDailyBudgetExhaustedError) as excinfo:
        _guard(db_session, budget_user_id).ensure_allowed()
    JobQueueService(db_session).park_until_openai_budget_reset(job_id, excinfo.value.reset_at)

    db_session.expire_all()
    parked = db_session.get(Job, job_id)
    new_reset = _guard(db_session, budget_user_id).status().reset_at
    assert parked.status == JOB_STATUS_PENDING
    assert parked.last_error == OPENAI_DAILY_BUDGET_PARKED_ERROR
    assert parked.run_after >= new_reset
    assert parked.run_after != old_reset
    assert new_reset != old_reset
