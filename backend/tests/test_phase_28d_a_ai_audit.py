"""PHASE 28D-A — AI execution observability tests."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.ai_audit.constants import (
    EVENT_MODEL_ROUND,
    EVENT_TOOL_CALL,
    EVENT_TRACE_STARTED,
    WORKLOAD_ASSISTANT_INTERACTIVE,
    WORKLOAD_BACKGROUND_SUMMARY,
    WORKLOAD_EMBEDDING,
    WORKLOAD_TRANSCRIPTION,
)
from app.ai_audit.context import ai_trace_session
from app.ai_audit.sanitizer import sanitize_for_audit
from app.ai_audit.trace_service import AITraceService
from app.db.models import AITrace, AITraceEvent, User
from app.llm.embedding_service import OpenAIEmbeddingService
from app.llm.openai_assistant_provider import AssistantProviderError, OpenAIAssistantProvider
from app.tools.executor import ToolExecutionResult
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient


def _usage_response(input_tokens: int, output_tokens: int) -> SimpleNamespace:
    return SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_tokens_details=SimpleNamespace(cached_tokens=0, cache_write_tokens=0),
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
        output=[],
        output_text="hello",
        status="completed",
    )


def test_sanitizer_redacts_api_key_like_values() -> None:
    payload = {"api_key": "sk-secret", "message": "hello"}
    sanitized = sanitize_for_audit(payload)
    assert sanitized["api_key"] == "[redacted]"
    assert sanitized["message"] == "hello"


def test_payload_capture_off_by_default(db_session) -> None:
    service = AITraceService(db_session)
    assert service.is_payload_capture_active(BOOTSTRAP_USER_ID) is False


def test_trace_lifecycle_and_user_isolation(db_session) -> None:
    other_user = User(id=uuid4(), display_name="Other User")
    db_session.add(other_user)
    db_session.flush()

    service = AITraceService(db_session)
    trace = service.start_trace(BOOTSTRAP_USER_ID, WORKLOAD_EMBEDDING, object_id=uuid4())
    service.record_event(
        trace.id,
        BOOTSTRAP_USER_ID,
        1,
        EVENT_TRACE_STARTED,
        {"workload": WORKLOAD_EMBEDDING},
    )
    service.finish_trace(trace.id, BOOTSTRAP_USER_ID, success=True)
    db_session.commit()

    assert service.get_trace(trace.id, BOOTSTRAP_USER_ID) is not None
    assert service.get_trace(trace.id, other_user.id) is None


def test_payload_capture_session_and_cleanup(db_session) -> None:
    service = AITraceService(db_session)
    service.enable_capture(BOOTSTRAP_USER_ID, duration=timedelta(minutes=30))
    assert service.is_payload_capture_active(BOOTSTRAP_USER_ID)
    retention = service.get_payload_retention_until(BOOTSTRAP_USER_ID)

    trace = service.start_trace(BOOTSTRAP_USER_ID, WORKLOAD_TRANSCRIPTION)
    service.record_event(
        trace.id,
        BOOTSTRAP_USER_ID,
        1,
        EVENT_MODEL_ROUND,
        {"payloads": {"instructions": "secret sk-test"}, "input_tokens": 10},
        payload_expires_at=retention,
    )
    db_session.commit()

    events = service.list_trace_events(trace.id, BOOTSTRAP_USER_ID, include_payloads=True)
    assert "payloads" in events[0]["metadata"]

    event = db_session.scalar(select(AITraceEvent).where(AITraceEvent.trace_id == trace.id))
    from app.services.job_queue_service import utcnow

    event.payload_expires_at = utcnow() - timedelta(hours=1)
    db_session.commit()

    stats = service.cleanup_expired()
    db_session.commit()
    assert stats["scrubbed_payload_events"] >= 1

    events_after = service.list_trace_events(trace.id, BOOTSTRAP_USER_ID, include_payloads=True)
    assert "payloads" not in events_after[0]["metadata"]


def test_assistant_provider_records_rounds_and_tools(db_session, monkeypatch) -> None:
    round_tokens = [(100, 20), (50, 30)]
    calls = 0

    class FakeResponses:
        def create(self, **kwargs):
            nonlocal calls
            input_tokens, output_tokens = round_tokens[min(calls, len(round_tokens) - 1)]
            calls += 1
            if calls == 1:
                return SimpleNamespace(
                    usage=SimpleNamespace(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        input_tokens_details=SimpleNamespace(cached_tokens=5, cache_write_tokens=0),
                        output_tokens_details=SimpleNamespace(reasoning_tokens=2),
                    ),
                    output=[
                        SimpleNamespace(
                            type="function_call",
                            call_id="c1",
                            name="get_object",
                            arguments='{"object_id":"550e8400-e29b-41d4-a716-446655440000"}',
                        )
                    ],
                    output_text="",
                    status="completed",
                )
            return _usage_response(input_tokens, output_tokens)

    fake_client = SimpleNamespace(responses=FakeResponses())
    provider = OpenAIAssistantProvider(
        api_key="sk-test",
        model="gpt-test",
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=400,
    )
    provider._client = fake_client

    def tool_runner(name: str, args: dict) -> ToolExecutionResult:
        return ToolExecutionResult(
            success=True,
            tool_name=name,
            output={"id": str(args.get("object_id", "")), "title": "T", "kind": "task"},
        )

    with ai_trace_session(BOOTSTRAP_USER_ID, WORKLOAD_ASSISTANT_INTERACTIVE, session=db_session):
        result = provider.run(
            message="find task",
            history=[],
            ui_context="",
            reference_datetime=__import__("datetime").datetime.now(__import__("datetime").UTC),
            timezone="UTC",
            tool_runner=tool_runner,
        )
    db_session.commit()

    assert result.answer == "hello"
    trace = db_session.scalar(
        select(AITrace).where(AITrace.user_id == BOOTSTRAP_USER_ID).order_by(AITrace.started_at.desc())
    )
    events = list(
        db_session.scalars(
            select(AITraceEvent).where(AITraceEvent.trace_id == trace.id).order_by(AITraceEvent.sequence)
        )
    )
    event_types = [event.event_type for event in events]
    assert EVENT_TRACE_STARTED in event_types
    assert EVENT_MODEL_ROUND in event_types
    assert EVENT_TOOL_CALL in event_types
    round_events = [e for e in events if e.event_type == EVENT_MODEL_ROUND]
    assert len(round_events) == 2
    assert sum(e.metadata_.get("input_tokens", 0) or 0 for e in round_events) == 150


def test_embedding_trace_under_active_session(db_session, monkeypatch) -> None:
    object_id = uuid4()
    fake_embedding = [0.1, 0.2, 0.3]

    class FakeEmbeddings:
        def create(self, **kwargs):
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=fake_embedding)],
                usage=SimpleNamespace(total_tokens=12),
            )

    service = OpenAIEmbeddingService(api_key="sk-test", model="text-embedding-3-small")
    service._client = SimpleNamespace(embeddings=FakeEmbeddings())

    with ai_trace_session(
        BOOTSTRAP_USER_ID,
        WORKLOAD_EMBEDDING,
        object_id=object_id,
        session=db_session,
    ):
        service.embed("sample text for embedding")
    db_session.commit()

    trace = db_session.scalar(select(AITrace).where(AITrace.object_id == object_id))
    assert trace is not None
    events = list(db_session.scalars(select(AITraceEvent).where(AITraceEvent.trace_id == trace.id)))
    assert any(event.event_type == EVENT_MODEL_ROUND for event in events)


def test_audit_summary_endpoint(auth_client: AuthTestClient, db_session) -> None:
    service = AITraceService(db_session)
    trace = service.start_trace(BOOTSTRAP_USER_ID, WORKLOAD_BACKGROUND_SUMMARY)
    service.record_event(
        trace.id,
        BOOTSTRAP_USER_ID,
        1,
        EVENT_MODEL_ROUND,
        {"model": "gpt-test", "input_tokens": 42, "output_tokens": 7},
    )
    service.finish_trace(trace.id, BOOTSTRAP_USER_ID, success=True)
    db_session.commit()

    from datetime import UTC

    now = datetime.now(UTC)
    started_after = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    started_before = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    response = auth_client.get(
        "/me/ai-audit/summary",
        params={"started_after": started_after, "started_before": started_before},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["trace_count"] >= 1
    assert body["total_input_tokens"] >= 42


def test_failed_model_round_recorded(db_session, monkeypatch) -> None:
    class BoomResponses:
        def create(self, **kwargs):
            raise RuntimeError("provider down")

    provider = OpenAIAssistantProvider(api_key="sk-test", model="gpt-test")
    provider._client = SimpleNamespace(responses=BoomResponses())

    with pytest.raises(AssistantProviderError), ai_trace_session(
        BOOTSTRAP_USER_ID,
        WORKLOAD_ASSISTANT_INTERACTIVE,
        session=db_session,
    ):
        provider.run_text_only(message="hi", context="ctx")
    db_session.commit()

    trace = db_session.scalar(
        select(AITrace).where(
            AITrace.user_id == BOOTSTRAP_USER_ID,
            AITrace.workload == WORKLOAD_ASSISTANT_INTERACTIVE,
        ).order_by(AITrace.started_at.desc())
    )
    events = list(db_session.scalars(select(AITraceEvent).where(AITraceEvent.trace_id == trace.id)))
    assert any(event.event_type == "model_round_failed" for event in events)
    assert trace.success is False
