"""PHASE 28D-A-R1 — AI audit corrective regression tests."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.ai_audit.constants import (
    EVENT_MODEL_ROUND,
    EVENT_MODEL_ROUND_FAILED,
    EVENT_TOOL_CALL,
    WORKLOAD_ASSISTANT_INTERACTIVE,
    WORKLOAD_BACKGROUND_SUMMARY,
    WORKLOAD_EMBEDDING,
    WORKLOAD_TRANSCRIPTION,
)
from app.ai_audit.context import ai_trace_session, reset_current_job_id, set_current_job_id
from app.ai_audit.payload_accounting import compute_assistant_input_component_sizes
from app.ai_audit.trace_service import AITraceService
from app.db.models import AIAuditCaptureSession, AITrace, AITraceEvent, Job, User
from app.llm.correlation_judge import _count_raw_decisions
from app.llm.embedding_service import OpenAIEmbeddingService
from app.llm.openai_assistant_provider import OpenAIAssistantProvider
from app.services.transcription_service import TranscriptionProviderError
from app.tools.results import ToolExecutionResult
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


def test_metadata_only_read_does_not_mutate_stored_payloads(db_session) -> None:
    service = AITraceService(db_session)
    service.enable_capture(BOOTSTRAP_USER_ID, duration=timedelta(minutes=30))
    retention = service.get_payload_retention_until(BOOTSTRAP_USER_ID)
    trace = service.start_trace(BOOTSTRAP_USER_ID, WORKLOAD_TRANSCRIPTION)
    original_payload = {"instructions": "diagnostic secret payload", "input_tokens": 10}
    service.record_event(
        trace.id,
        BOOTSTRAP_USER_ID,
        1,
        EVENT_MODEL_ROUND,
        {"payloads": original_payload, "input_tokens": 10},
        payload_expires_at=retention,
    )
    db_session.commit()

    metadata_view = service.list_trace_events(trace.id, BOOTSTRAP_USER_ID, include_payloads=False)
    assert metadata_view[0]["metadata"]["payloads"] == "[withheld]"

    payload_view = service.list_trace_events(trace.id, BOOTSTRAP_USER_ID, include_payloads=True)
    assert payload_view[0]["metadata"]["payloads"] == original_payload

    persisted = db_session.scalar(
        select(AITraceEvent).where(AITraceEvent.trace_id == trace.id, AITraceEvent.sequence == 1)
    )
    assert persisted is not None
    assert persisted.metadata_["payloads"] == original_payload
    service.disable_capture(BOOTSTRAP_USER_ID)
    db_session.commit()


def test_capture_disable_stops_new_payloads_but_retains_readable(db_session) -> None:
    service = AITraceService(db_session)
    service.disable_capture(BOOTSTRAP_USER_ID)
    db_session.commit()
    service.enable_capture(BOOTSTRAP_USER_ID, duration=timedelta(minutes=30))
    retention = service.get_payload_retention_until(BOOTSTRAP_USER_ID)
    trace = service.start_trace(BOOTSTRAP_USER_ID, WORKLOAD_EMBEDDING)
    service.record_event(
        trace.id,
        BOOTSTRAP_USER_ID,
        1,
        EVENT_MODEL_ROUND,
        {"payloads": {"model_input_text": "keep me"}},
        payload_expires_at=retention,
    )
    db_session.commit()

    service.disable_capture(BOOTSTRAP_USER_ID)
    db_session.commit()
    assert service.is_payload_capture_active(BOOTSTRAP_USER_ID) is False

    with ai_trace_session(BOOTSTRAP_USER_ID, WORKLOAD_EMBEDDING, session=db_session):
        pass
    db_session.commit()

    events = list(
        db_session.scalars(select(AITraceEvent).where(AITraceEvent.trace_id == trace.id))
    )
    assert "payloads" in events[0].metadata_
    readable = service.list_trace_events(trace.id, BOOTSTRAP_USER_ID, include_payloads=True)
    assert readable[0]["metadata"]["payloads"]["model_input_text"] == "keep me"
    service.disable_capture(BOOTSTRAP_USER_ID)
    db_session.commit()


def test_payload_scrub_after_retention_expiry(db_session) -> None:
    service = AITraceService(db_session)
    service.enable_capture(BOOTSTRAP_USER_ID, duration=timedelta(minutes=30))
    retention = service.get_payload_retention_until(BOOTSTRAP_USER_ID)
    trace = service.start_trace(BOOTSTRAP_USER_ID, WORKLOAD_EMBEDDING)
    service.record_event(
        trace.id,
        BOOTSTRAP_USER_ID,
        1,
        EVENT_MODEL_ROUND,
        {"payloads": {"model_input_text": "expire me"}},
        payload_expires_at=retention,
    )
    db_session.commit()

    event = db_session.scalar(select(AITraceEvent).where(AITraceEvent.trace_id == trace.id))
    from app.services.job_queue_service import utcnow

    event.payload_expires_at = utcnow() - timedelta(minutes=1)
    db_session.commit()

    stats = service.cleanup_expired()
    db_session.commit()
    assert stats["scrubbed_payload_events"] >= 1

    readable = service.list_trace_events(trace.id, BOOTSTRAP_USER_ID, include_payloads=True)
    assert "payloads" not in readable[0]["metadata"]
    persisted = db_session.scalar(select(AITraceEvent).where(AITraceEvent.id == event.id))
    assert "payloads" not in persisted.metadata_


def test_second_capture_session_does_not_extend_old_payload_retention(db_session) -> None:
    service = AITraceService(db_session)
    service.enable_capture(BOOTSTRAP_USER_ID, duration=timedelta(minutes=10))
    first_retention = service.get_payload_retention_until(BOOTSTRAP_USER_ID)
    trace = service.start_trace(BOOTSTRAP_USER_ID, WORKLOAD_EMBEDDING)
    service.record_event(
        trace.id,
        BOOTSTRAP_USER_ID,
        1,
        EVENT_MODEL_ROUND,
        {"payloads": {"model_input_text": "first session"}},
        payload_expires_at=first_retention,
    )
    db_session.commit()

    from app.services.job_queue_service import utcnow

    row = db_session.get(AIAuditCaptureSession, BOOTSTRAP_USER_ID)
    row.expires_at = utcnow() - timedelta(minutes=1)
    db_session.commit()

    service.enable_capture(BOOTSTRAP_USER_ID, duration=timedelta(minutes=60))
    second_retention = service.get_payload_retention_until(BOOTSTRAP_USER_ID)
    assert second_retention > first_retention

    event = db_session.scalar(select(AITraceEvent).where(AITraceEvent.trace_id == trace.id))
    assert event.payload_expires_at == first_retention


def test_input_component_accounting_no_user_message_double_count() -> None:
    user_msg = "x" * 40
    history_msg = "y" * 30
    input_items = [
        {"role": "user", "content": history_msg},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": user_msg},
    ]
    sizes = compute_assistant_input_component_sizes(
        instructions="sys",
        input_items=input_items,
        tool_definitions=None,
        user_message=user_msg,
    )
    assert sizes["conversation_history_chars"] == len(history_msg) + len("reply")
    assert sizes["current_user_message_chars"] == len(user_msg)


def test_capture_off_tool_argument_privacy(db_session) -> None:
    calls = 0

    class FakeResponses:
        def create(self, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return SimpleNamespace(
                    usage=SimpleNamespace(
                        input_tokens=80,
                        output_tokens=10,
                        input_tokens_details=SimpleNamespace(cached_tokens=0, cache_write_tokens=0),
                        output_tokens_details=SimpleNamespace(reasoning_tokens=0),
                    ),
                    output=[
                        SimpleNamespace(
                            type="function_call",
                            call_id="c1",
                            name="retrieve",
                            arguments='{"query":"secret user query text","limit":3}',
                        )
                    ],
                    output_text="",
                    status="completed",
                )
            return _usage_response(40, 5)

    provider = OpenAIAssistantProvider(api_key="sk-test", model="gpt-test")
    provider._client = SimpleNamespace(responses=FakeResponses())

    def tool_runner(name: str, args: dict) -> ToolExecutionResult:
        return ToolExecutionResult(
            success=True,
            tool_name=name,
            output={"results": []},
            validated_arguments={"query": "secret user query text", "limit": 3},
        )

    with ai_trace_session(BOOTSTRAP_USER_ID, WORKLOAD_ASSISTANT_INTERACTIVE, session=db_session):
        provider.run(
            message="search",
            history=[],
            ui_context="",
            reference_datetime=datetime.now(__import__("datetime").UTC),
            timezone="UTC",
            tool_runner=tool_runner,
        )
    db_session.commit()

    trace = db_session.scalar(
        select(AITrace).where(AITrace.user_id == BOOTSTRAP_USER_ID).order_by(AITrace.started_at.desc())
    )
    tool_event = db_session.scalar(
        select(AITraceEvent).where(
            AITraceEvent.trace_id == trace.id,
            AITraceEvent.event_type == EVENT_TOOL_CALL,
        )
    )
    meta = tool_event.metadata_
    assert "validated_arguments" not in meta
    assert meta["argument_keys"] == ["limit", "query"]
    assert meta["argument_structure"]["query"] == {"type": "string", "chars": len("secret user query text")}


def test_capture_on_tool_argument_payload(db_session) -> None:
    service = AITraceService(db_session)
    service.enable_capture(BOOTSTRAP_USER_ID, duration=timedelta(minutes=30))
    calls = 0

    class FakeResponses:
        def create(self, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return SimpleNamespace(
                    usage=SimpleNamespace(
                        input_tokens=50,
                        output_tokens=5,
                        input_tokens_details=SimpleNamespace(cached_tokens=0, cache_write_tokens=0),
                        output_tokens_details=SimpleNamespace(reasoning_tokens=0),
                    ),
                    output=[
                        SimpleNamespace(
                            type="function_call",
                            call_id="c1",
                            name="retrieve",
                            arguments='{"query":"exact query","limit":2}',
                        )
                    ],
                    output_text="",
                    status="completed",
                )
            return _usage_response(30, 3)

    provider = OpenAIAssistantProvider(api_key="sk-test", model="gpt-test")
    provider._client = SimpleNamespace(responses=FakeResponses())

    def tool_runner(name: str, args: dict) -> ToolExecutionResult:
        return ToolExecutionResult(
            success=True,
            tool_name=name,
            output={"results": []},
            validated_arguments={"query": "exact query", "limit": 2},
        )

    with ai_trace_session(BOOTSTRAP_USER_ID, WORKLOAD_ASSISTANT_INTERACTIVE, session=db_session):
        provider.run(
            message="search",
            history=[],
            ui_context="",
            reference_datetime=datetime.now(__import__("datetime").UTC),
            timezone="UTC",
            tool_runner=tool_runner,
        )
    db_session.commit()

    trace = db_session.scalar(
        select(AITrace).where(AITrace.user_id == BOOTSTRAP_USER_ID).order_by(AITrace.started_at.desc())
    )
    events = service.list_trace_events(trace.id, BOOTSTRAP_USER_ID, include_payloads=True)
    tool_meta = next(e["metadata"] for e in events if e["event_type"] == EVENT_TOOL_CALL)
    validated = json.loads(tool_meta["payloads"]["validated_arguments"])
    assert validated["query"] == "exact query"


def test_correlation_raw_vs_accepted_decisions() -> None:
    raw_text = (
        '{"decisions":[{"target_object_id":"550e8400-e29b-41d4-a716-446655440000",'
        '"relation_type":"related_to","confidence":0.9,"rationale":"ok"},'
        '{"target_object_id":"bad-id","relation_type":"related_to","confidence":0.5,"rationale":"bad"}]}'
    )
    assert _count_raw_decisions(raw_text) == 2


def test_embedding_input_capture_without_vector(db_session, monkeypatch) -> None:
    service = AITraceService(db_session)
    service.enable_capture(BOOTSTRAP_USER_ID, duration=timedelta(minutes=30))
    object_id = uuid4()
    fake_embedding = [0.1, 0.2, 0.3]

    class FakeEmbeddings:
        def create(self, **kwargs):
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=fake_embedding)],
                usage=SimpleNamespace(total_tokens=12),
            )

    embed_service = OpenAIEmbeddingService(api_key="sk-test", model="text-embedding-3-small")
    embed_service._client = SimpleNamespace(embeddings=FakeEmbeddings())

    with ai_trace_session(
        BOOTSTRAP_USER_ID,
        WORKLOAD_EMBEDDING,
        object_id=object_id,
        session=db_session,
    ):
        embed_service.embed("sample text for embedding")
    db_session.commit()

    trace = db_session.scalar(select(AITrace).where(AITrace.object_id == object_id))
    events = AITraceService(db_session).list_trace_events(trace.id, BOOTSTRAP_USER_ID, include_payloads=True)
    round_meta = next(e["metadata"] for e in events if e["event_type"] == EVENT_MODEL_ROUND)
    payloads = round_meta["payloads"]
    assert json.loads(payloads["model_input_text"]) == "sample text for embedding"
    assert "embedding" not in payloads
    assert "0.1" not in json.dumps(payloads)


def test_transcription_failure_records_model_call_event(db_session) -> None:
    from io import BytesIO

    from fastapi import UploadFile

    from app.services.transcription_service import transcribe_audio_upload

    class FailingProvider:
        model = "gpt-4o-mini-transcribe"

        def transcribe(self, audio_bytes, filename, content_type):
            raise TranscriptionProviderError("transcription call failed")

    upload = UploadFile(file=BytesIO(b"audio-bytes"), filename="note.m4a")

    async def _run():
        with ai_trace_session(BOOTSTRAP_USER_ID, WORKLOAD_TRANSCRIPTION, session=db_session):
            await transcribe_audio_upload(upload, FailingProvider())

    import asyncio

    with pytest.raises(TranscriptionProviderError):
        asyncio.run(_run())
    db_session.commit()

    trace = db_session.scalar(
        select(AITrace).where(
            AITrace.user_id == BOOTSTRAP_USER_ID,
            AITrace.workload == WORKLOAD_TRANSCRIPTION,
        ).order_by(AITrace.started_at.desc())
    )
    events = list(db_session.scalars(select(AITraceEvent).where(AITraceEvent.trace_id == trace.id)))
    assert any(event.event_type == EVENT_MODEL_ROUND_FAILED for event in events)


def test_job_id_provenance_from_worker_context(db_session) -> None:
    job = Job(
        id=uuid4(),
        user_id=BOOTSTRAP_USER_ID,
        type="embed_object",
        status="running",
        payload={"object_id": str(uuid4())},
    )
    db_session.add(job)
    db_session.flush()

    token = set_current_job_id(job.id)
    try:
        with ai_trace_session(BOOTSTRAP_USER_ID, WORKLOAD_EMBEDDING, session=db_session):
            pass
    finally:
        reset_current_job_id(token)
    db_session.commit()

    trace = db_session.scalar(
        select(AITrace).where(AITrace.user_id == BOOTSTRAP_USER_ID).order_by(AITrace.started_at.desc())
    )
    assert trace.job_id == job.id


def test_mixed_workload_summary_metrics(db_session) -> None:
    service = AITraceService(db_session)
    assistant_trace = service.start_trace(BOOTSTRAP_USER_ID, WORKLOAD_ASSISTANT_INTERACTIVE)
    service.record_event(
        assistant_trace.id,
        BOOTSTRAP_USER_ID,
        1,
        EVENT_MODEL_ROUND,
        {"model": "gpt-a", "input_tokens": 100, "output_tokens": 10},
    )
    service.record_event(
        assistant_trace.id,
        BOOTSTRAP_USER_ID,
        2,
        EVENT_MODEL_ROUND,
        {"model": "gpt-a", "input_tokens": 50, "output_tokens": 5},
    )
    service.record_event(assistant_trace.id, BOOTSTRAP_USER_ID, 3, EVENT_TOOL_CALL, {"tool_name": "retrieve"})
    service.finish_trace(assistant_trace.id, BOOTSTRAP_USER_ID, success=True)

    zero_tool_trace = service.start_trace(BOOTSTRAP_USER_ID, WORKLOAD_ASSISTANT_INTERACTIVE)
    service.record_event(
        zero_tool_trace.id,
        BOOTSTRAP_USER_ID,
        1,
        EVENT_MODEL_ROUND,
        {"model": "gpt-a", "input_tokens": 20, "output_tokens": 2},
    )
    service.finish_trace(zero_tool_trace.id, BOOTSTRAP_USER_ID, success=True)

    embed_trace = service.start_trace(BOOTSTRAP_USER_ID, WORKLOAD_EMBEDDING)
    service.record_event(
        embed_trace.id,
        BOOTSTRAP_USER_ID,
        1,
        EVENT_MODEL_ROUND,
        {"model": "embed-model", "input_tokens": 30},
    )
    service.record_event(
        embed_trace.id,
        BOOTSTRAP_USER_ID,
        2,
        EVENT_MODEL_ROUND,
        {"model": "embed-model", "input_tokens": 15},
    )
    service.finish_trace(embed_trace.id, BOOTSTRAP_USER_ID, success=True)

    bg_zero = service.start_trace(BOOTSTRAP_USER_ID, WORKLOAD_BACKGROUND_SUMMARY)
    service.finish_trace(bg_zero.id, BOOTSTRAP_USER_ID, success=True)

    db_session.commit()

    from datetime import UTC

    now = datetime.now(UTC)
    summary = service.build_summary(
        BOOTSTRAP_USER_ID,
        now - timedelta(hours=1),
        now + timedelta(hours=1),
    )
    assert summary["trace_count"] == 4
    assert summary["model_call_count"] == 5
    assert summary["model_calls_by_workload"][WORKLOAD_ASSISTANT_INTERACTIVE] == 3
    assert summary["model_calls_by_workload"][WORKLOAD_EMBEDDING] == 2
    assert summary["assistant_turn_count"] == 2
    assert summary["assistant_avg_rounds"] == 1.5
    assert summary["assistant_avg_tool_calls"] == 0.5
    assert summary["traces_by_workload"][WORKLOAD_BACKGROUND_SUMMARY] == 1


def test_list_traces_api_user_isolation(auth_client: AuthTestClient, db_session) -> None:
    other_user = User(id=uuid4(), display_name="Other")
    db_session.add(other_user)
    db_session.flush()
    service = AITraceService(db_session)
    trace = service.start_trace(other_user.id, WORKLOAD_EMBEDDING)
    service.finish_trace(trace.id, other_user.id, success=True)
    db_session.commit()

    from datetime import UTC

    now = datetime.now(UTC)
    started_after = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    started_before = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    response = auth_client.get(
        "/me/ai-audit/traces",
        params={"started_after": started_after, "started_before": started_before},
    )
    assert response.status_code == 200
    body = response.json()
    assert all(item["trace_id"] != str(trace.id) for item in body)
