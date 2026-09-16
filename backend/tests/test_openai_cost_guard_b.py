"""OpenAI Cost Guard B — embedding revision idempotency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.api.schemas import ObjectCreate, ObjectUpdate
from app.db.models import Job, Object, Representation, UserSettings
from app.jobs.constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_TYPE_AUTO_LABEL_OBJECT,
    JOB_TYPE_CORRELATE_OBJECT,
    JOB_TYPE_EMBED_OBJECT,
    MAX_JOB_ATTEMPTS,
)
from app.jobs.handlers import handle_embed_object
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.embedding_text import (
    EMBEDDING_INPUT_VERSION,
    canonical_embedding_text,
    embed_job_payload,
    embedding_input_signature,
)
from app.services.auto_label_constants import AUTO_LABEL_VERSION
from app.services.background_ai_errors import is_openai_quota_exhausted
from app.services.correlation_input import correlation_input_signature
from app.services.graph_service import GraphService
from app.services.job_queue_service import JobQueueService, is_job_error_retryable
from app.services.label_service import LabelService
from app.services.pipeline_enqueue import enqueue_correlate_object, enqueue_embed_object
from app.services.representation_service import KIND_CHUNK
from app.users.bootstrap import BOOTSTRAP_USER_ID


class CountingEmbeddingService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._inner = FakeEmbeddingService()

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return self._inner.embed(text)


class _SessionProxy:
    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._session, name)


@pytest.fixture(autouse=True)
def _share_test_session_for_traces(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ai_audit.context.SessionLocal", lambda: _SessionProxy(db_session)
    )
    monkeypatch.setattr(
        "app.jobs.handlers.SessionLocal", lambda: _SessionProxy(db_session)
    )
    monkeypatch.setattr(
        "app.services.representation_embedding_worker.SessionLocal",
        lambda: _SessionProxy(db_session),
    )


def _graph(db_session) -> GraphService:
    return GraphService(db_session, BOOTSTRAP_USER_ID)


def _note(db_session, title: str = "Note", **kwargs) -> Object:
    return _graph(db_session).create_object(
        ObjectCreate(kind="note", title=title, origin="user", **kwargs)
    )


def _yandex_event(db_session, title: str = "Standup") -> Object:
    start = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
    obj = _graph(db_session).create_object(
        ObjectCreate(
            kind="event",
            title=title,
            origin="source",
            provider="yandex_calendar",
            external_id=str(uuid4()),
            body="weekly standup",
            start_at=start,
            due_at=start + timedelta(hours=1),
            metadata={
                "etag": "etag-1",
                "last_modified": "20260910T090000Z",
                "event_href": "/calendars/a/event-1.ics",
                "calendar_href": "/calendars/a/",
                "href": "/calendars/a/event-1.ics",
                "location": "Room 1",
                "organizer": "owner@example.com",
                "attendees": [{"email": "a@example.com"}, {"email": "b@example.com"}],
            },
        )
    )
    obj.occurred_at = start
    db_session.flush()
    return obj


def _google_event(db_session, title: str = "Planning") -> Object:
    start = datetime(2026, 9, 10, 11, 0, tzinfo=UTC)
    obj = _graph(db_session).create_object(
        ObjectCreate(
            kind="event",
            title=title,
            origin="source",
            provider="google_calendar",
            external_id=str(uuid4()),
            body="planning notes",
            start_at=start,
            due_at=start + timedelta(hours=1),
            metadata={
                "calendar_id": "cal-1",
                "event_id": "evt-1",
                "html_link": "https://calendar.google.com/event-1",
                "updated": "2026-09-10T09:00:00Z",
                "location": "HQ",
                "organizer": "host@example.com",
                "attendees": [{"email": "c@example.com", "response_status": "accepted"}],
            },
        )
    )
    obj.occurred_at = start
    db_session.flush()
    return obj


def _embed_jobs(db_session) -> list[Job]:
    return list(
        db_session.scalars(
            select(Job)
            .where(Job.type == JOB_TYPE_EMBED_OBJECT)
            .order_by(Job.created_at, Job.id)
        )
    )


def _job_for_signature(jobs: list[Job], signature: str) -> Job:
    matched = [
        job
        for job in jobs
        if job.payload.get("embedding_input_signature") == signature
    ]
    assert len(matched) == 1
    return matched[0]


def _correlate_jobs(db_session) -> list[Job]:
    return list(
        db_session.scalars(
            select(Job)
            .where(Job.type == JOB_TYPE_CORRELATE_OBJECT)
            .order_by(Job.created_at, Job.id)
        )
    )


def _auto_label_jobs(db_session) -> list[Job]:
    return list(
        db_session.scalars(
            select(Job)
            .where(Job.type == JOB_TYPE_AUTO_LABEL_OBJECT)
            .order_by(Job.created_at, Job.id)
        )
    )


def _run_embed(db_session, payload: dict, service: CountingEmbeddingService) -> None:
    handle_embed_object(db_session, service, payload, BOOTSTRAP_USER_ID)


def _enable_auto_label(db_session) -> None:
    settings = db_session.get(UserSettings, BOOTSTRAP_USER_ID)
    if settings is None:
        settings = UserSettings(user_id=BOOTSTRAP_USER_ID, auto_label_enabled=True)
        db_session.add(settings)
    else:
        settings.auto_label_enabled = True
    db_session.flush()
    LabelService(db_session, BOOTSTRAP_USER_ID).create_label("Work")


def test_repeated_same_semantic_input_one_embedding_call(db_session) -> None:
    note = _note(db_session, "Stable", body="same")
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    jobs = _embed_jobs(db_session)
    assert len(jobs) == 1
    _run_embed(db_session, jobs[0].payload, service)
    jobs[0].status = JOB_STATUS_DONE
    db_session.flush()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    assert len(_embed_jobs(db_session)) == 1
    _run_embed(db_session, jobs[0].payload, service)
    assert len(service.calls) == 1


def test_enqueue_again_after_done_zero_additional_paid_calls(db_session) -> None:
    note = _note(db_session, "Done once", body="body")
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    job = _embed_jobs(db_session)[0]
    _run_embed(db_session, job.payload, service)
    job.status = JOB_STATUS_DONE
    db_session.flush()
    db_session.refresh(note)
    assert note.embedding is not None
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    assert len(_embed_jobs(db_session)) == 1
    assert len(service.calls) == 1


def test_yandex_technical_metadata_churn_one_paid_embedding(db_session) -> None:
    event = _yandex_event(db_session)
    service = CountingEmbeddingService()
    first_sig = embedding_input_signature(event)
    enqueue_embed_object(db_session, event.id, BOOTSTRAP_USER_ID)
    job = _embed_jobs(db_session)[0]
    _run_embed(db_session, job.payload, service)
    job.status = JOB_STATUS_DONE
    db_session.flush()
    for index in range(21):
        event.metadata_ = {
            **event.metadata_,
            "etag": f"etag-{index}",
            "last_modified": f"20260911T09{index:02d}00Z",
            "event_href": f"/calendars/a/event-{index}.ics",
            "calendar_href": f"/calendars/{index}/",
            "href": f"/calendars/a/event-{index}.ics",
            "sync_token": f"sync-{index}",
            "fetched_at": f"2026-09-11T09:{index:02d}:00Z",
        }
        event.updated_at = datetime(2026, 9, 11, 9, index, tzinfo=UTC)
        db_session.flush()
        assert embedding_input_signature(event) == first_sig
        enqueue_embed_object(db_session, event.id, BOOTSTRAP_USER_ID)
    assert len(_embed_jobs(db_session)) == 1
    assert len(service.calls) == 1


def test_google_calendar_housekeeping_churn_zero_new_paid_embedding(db_session) -> None:
    event = _google_event(db_session)
    service = CountingEmbeddingService()
    first_sig = embedding_input_signature(event)
    enqueue_embed_object(db_session, event.id, BOOTSTRAP_USER_ID)
    job = _embed_jobs(db_session)[0]
    _run_embed(db_session, job.payload, service)
    job.status = JOB_STATUS_DONE
    db_session.flush()
    event.metadata_ = {
        **event.metadata_,
        "html_link": "https://calendar.google.com/event-1?updated=1",
        "updated": "2026-09-11T09:00:00Z",
        "calendar_id": "cal-moved",
        "event_id": "evt-moved",
        "recurring_event_id": "series-9",
    }
    event.updated_at = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)
    db_session.flush()
    assert embedding_input_signature(event) == first_sig
    enqueue_embed_object(db_session, event.id, BOOTSTRAP_USER_ID)
    assert len(_embed_jobs(db_session)) == 1
    assert len(service.calls) == 1


def test_etag_href_last_modified_only_identical_signature(db_session) -> None:
    event = _yandex_event(db_session)
    before = embedding_input_signature(event)
    before_text = canonical_embedding_text(event)
    event.metadata_ = {
        **event.metadata_,
        "etag": "etag-changed",
        "href": "/moved.ics",
        "event_href": "/moved.ics",
        "last_modified": "20260912T000000Z",
    }
    event.updated_at = datetime(2026, 9, 12, tzinfo=UTC)
    db_session.flush()
    assert canonical_embedding_text(event) == before_text
    assert embedding_input_signature(event) == before


def test_title_change_new_signature_and_one_new_embedding(db_session) -> None:
    note = _note(db_session, "Title A", body="body")
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    first = _embed_jobs(db_session)[0]
    _run_embed(db_session, first.payload, service)
    first.status = JOB_STATUS_DONE
    db_session.flush()
    note.title = "Title B"
    db_session.flush()
    current_sig = embedding_input_signature(note)
    assert current_sig != first.payload["embedding_input_signature"]
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    jobs = _embed_jobs(db_session)
    assert len(jobs) == 2
    _run_embed(db_session, _job_for_signature(jobs, current_sig).payload, service)
    assert len(service.calls) == 2


def test_body_change_new_signature_and_one_new_embedding(db_session) -> None:
    note = _note(db_session, "Same title", body="body-a")
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    first = _embed_jobs(db_session)[0]
    _run_embed(db_session, first.payload, service)
    first.status = JOB_STATUS_DONE
    db_session.flush()
    note.body = "body-b"
    db_session.flush()
    current_sig = embedding_input_signature(note)
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    jobs = _embed_jobs(db_session)
    assert len(jobs) == 2
    _run_embed(db_session, _job_for_signature(jobs, current_sig).payload, service)
    assert len(service.calls) == 2


def test_allowed_semantic_metadata_change_new_signature(db_session) -> None:
    note = _note(
        db_session,
        "Mail",
        body="hello",
        metadata={"from": "a@x.com", "location": "Room 1", "semantic_summary": "s1"},
    )
    first = embedding_input_signature(note)
    note.metadata_ = {**note.metadata_, "from": "b@x.com"}
    db_session.flush()
    assert embedding_input_signature(note) != first
    note.metadata_ = {**note.metadata_, "location": "Room 2"}
    db_session.flush()
    assert embedding_input_signature(note) != first
    note.metadata_ = {**note.metadata_, "semantic_summary": "s2"}
    db_session.flush()
    assert embedding_input_signature(note) != first


def test_excluded_technical_metadata_same_signature(db_session) -> None:
    event = _yandex_event(db_session)
    first = embedding_input_signature(event)
    event.metadata_ = {
        **event.metadata_,
        "etag": "x",
        "event_uid": "uid-9",
        "calendar_id": "other",
        "html_link": "https://example/x",
        "updated": "later",
        "sync_token": "tok",
        "page_token": "p",
        "dtstart_tzid": "Europe/Moscow",
        "recurrence_id": "rid",
        "rrule": "FREQ=WEEKLY",
        "attendees_truncated": True,
        "organizer_self": True,
        "message_id": "mid",
        "thread_id": "thread-should-not-bind",
    }
    db_session.flush()
    assert embedding_input_signature(event) == first


def test_embedding_model_change_new_signature_and_one_embedding(db_session, monkeypatch) -> None:
    note = _note(db_session, "Model", body="text")
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    first = _embed_jobs(db_session)[0]
    _run_embed(db_session, first.payload, service)
    first.status = JOB_STATUS_DONE
    db_session.flush()
    monkeypatch.setattr(
        "app.llm.embedding_text.effective_embedding_model",
        lambda: "text-embedding-3-large",
    )
    current_sig = embedding_input_signature(note)
    assert current_sig != first.payload["embedding_input_signature"]
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    jobs = _embed_jobs(db_session)
    assert len(jobs) == 2
    current = _job_for_signature(jobs, current_sig)
    assert current.payload["embedding_input_signature"] != first.payload["embedding_input_signature"]
    _run_embed(db_session, current.payload, service)
    assert len(service.calls) == 2


def test_embedding_input_version_change_new_signature_and_one_embedding(
    db_session, monkeypatch
) -> None:
    note = _note(db_session, "Version", body="text")
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    first = _embed_jobs(db_session)[0]
    _run_embed(db_session, first.payload, service)
    first.status = JOB_STATUS_DONE
    db_session.flush()
    monkeypatch.setattr(
        "app.llm.embedding_text.embedding_input_version",
        lambda: "cost_guard_b2",
    )
    current_sig = embedding_input_signature(note)
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    jobs = _embed_jobs(db_session)
    assert len(jobs) == 2
    _run_embed(db_session, _job_for_signature(jobs, current_sig).payload, service)
    assert len(service.calls) == 2
    assert EMBEDDING_INPUT_VERSION == "cost_guard_b"


def test_stale_signed_job_zero_api_and_current_job_ensured(db_session) -> None:
    note = _note(db_session, "S1", body="one")
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    stale = _embed_jobs(db_session)[0]
    note.body = "two"
    db_session.flush()
    _run_embed(db_session, stale.payload, service)
    assert service.calls == []
    jobs = _embed_jobs(db_session)
    assert len(jobs) == 2
    current = next(job for job in jobs if job.id != stale.id)
    _run_embed(db_session, current.payload, service)
    assert len(service.calls) == 1
    _run_embed(db_session, stale.payload, service)
    assert len(service.calls) == 1
    assert len(_embed_jobs(db_session)) == 2


def test_unsigned_legacy_job_zero_api_and_current_signed_job_ensured(db_session) -> None:
    note = _note(db_session, "Legacy", body="body")
    service = CountingEmbeddingService()
    unsigned = JobQueueService(db_session).enqueue(
        JOB_TYPE_EMBED_OBJECT,
        {"object_id": str(note.id)},
        BOOTSTRAP_USER_ID,
    )
    _run_embed(db_session, unsigned.payload, service)
    assert service.calls == []
    jobs = _embed_jobs(db_session)
    assert len(jobs) == 2
    signed = next(job for job in jobs if job.id != unsigned.id)
    assert signed.payload.get("embedding_input_signature") == embedding_input_signature(note)
    _run_embed(db_session, signed.payload, service)
    assert len(service.calls) == 1


def test_many_unsigned_jobs_collapse_to_one_current_signed_job(db_session) -> None:
    note = _note(db_session, "Flood", body="body")
    service = CountingEmbeddingService()
    queue = JobQueueService(db_session)
    unsigned = [
        queue.enqueue(JOB_TYPE_EMBED_OBJECT, {"object_id": str(note.id)}, BOOTSTRAP_USER_ID)
        for _ in range(5)
    ]
    for job in unsigned:
        _run_embed(db_session, job.payload, service)
    jobs = _embed_jobs(db_session)
    signed = [
        job
        for job in jobs
        if job.payload.get("embedding_input_signature") == embedding_input_signature(note)
    ]
    assert len(signed) == 1
    assert service.calls == []
    _run_embed(db_session, signed[0].payload, service)
    assert len(service.calls) == 1


def test_failed_previous_embedding_is_not_done_proof(db_session) -> None:
    note = _note(db_session, "Fail", body="body")
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    first = _embed_jobs(db_session)[0]
    first.status = JOB_STATUS_FAILED
    db_session.flush()
    assert note.embedding is None
    assert note.embedding_signature is None
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    jobs = _embed_jobs(db_session)
    assert len(jobs) == 2
    second = next(job for job in jobs if job.id != first.id)
    assert second.status == JOB_STATUS_PENDING
    _run_embed(db_session, second.payload, service)
    assert len(service.calls) == 1


def test_correlation_significant_embedding_insignificant_still_enqueues_correlate(
    db_session,
) -> None:
    event = _yandex_event(db_session)
    event.metadata_ = {**event.metadata_, "thread_id": "t1"}
    db_session.flush()
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, event.id, BOOTSTRAP_USER_ID)
    embed_job = _embed_jobs(db_session)[0]
    _run_embed(db_session, embed_job.payload, service)
    embed_job.status = JOB_STATUS_DONE
    db_session.flush()
    first_embed_sig = embedding_input_signature(event)
    first_corr_sig = correlation_input_signature(event)
    enqueue_correlate_object(db_session, event.id, BOOTSTRAP_USER_ID, event.kind)
    first_corr = _correlate_jobs(db_session)[0]
    first_corr.status = JOB_STATUS_DONE
    db_session.flush()
    event.metadata_ = {**dict(event.metadata_ or {}), "thread_id": "t2"}
    flag_modified(event, "metadata_")
    event.occurred_at = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    event.start_at = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    db_session.flush()
    db_session.refresh(event)
    assert embedding_input_signature(event) == first_embed_sig
    assert correlation_input_signature(event) != first_corr_sig
    enqueue_embed_object(db_session, event.id, BOOTSTRAP_USER_ID)
    assert len(_embed_jobs(db_session)) == 1
    assert len(service.calls) == 1
    corr_jobs = _correlate_jobs(db_session)
    assert len(corr_jobs) == 2
    current_corr = next(
        job
        for job in corr_jobs
        if job.payload.get("correlation_input_signature") == correlation_input_signature(event)
    )
    assert current_corr.payload["correlation_input_signature"] != first_corr_sig


def test_embedding_suppression_does_not_suppress_auto_label(db_session) -> None:
    _enable_auto_label(db_session)
    note = _note(db_session, "Label me", body="work notes")
    service = CountingEmbeddingService()
    note.embedding = FakeEmbeddingService().embed(canonical_embedding_text(note))
    note.embedding_signature = embedding_input_signature(note)
    done = JobQueueService(db_session).enqueue(
        JOB_TYPE_EMBED_OBJECT,
        embed_job_payload(note),
        BOOTSTRAP_USER_ID,
    )
    done.status = JOB_STATUS_DONE
    db_session.flush()
    unsigned = JobQueueService(db_session).enqueue(
        JOB_TYPE_EMBED_OBJECT,
        {"object_id": str(note.id)},
        BOOTSTRAP_USER_ID,
    )
    _run_embed(db_session, unsigned.payload, service)
    assert service.calls == []
    auto_jobs = list(
        db_session.scalars(select(Job).where(Job.type == JOB_TYPE_AUTO_LABEL_OBJECT))
    )
    assert len(auto_jobs) == 1
    assert "classification_signature" in auto_jobs[0].payload
    assert AUTO_LABEL_VERSION


def test_new_null_chunks_still_embedded_existing_chunks_not_reembedded(db_session) -> None:
    note = _note(db_session, "Chunks", body="object body")
    existing = Representation(
        object_id=note.id,
        kind=KIND_CHUNK,
        part_index=0,
        text="already embedded chunk",
        embedding=FakeEmbeddingService().embed("already embedded chunk"),
    )
    db_session.add(existing)
    db_session.flush()
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    job = _embed_jobs(db_session)[0]
    _run_embed(db_session, job.payload, service)
    job.status = JOB_STATUS_DONE
    db_session.flush()
    assert len(service.calls) == 1
    fresh = Representation(
        object_id=note.id,
        kind=KIND_CHUNK,
        part_index=1,
        text="brand new chunk",
        embedding=None,
    )
    db_session.add(fresh)
    db_session.flush()
    _run_embed(db_session, job.payload, service)
    assert len(service.calls) == 2
    assert service.calls[1] == "brand new chunk"
    db_session.refresh(existing)
    db_session.refresh(fresh)
    assert existing.embedding is not None
    assert fresh.embedding is not None


def test_permanent_quota_exhaustion_still_does_not_retry_three_times(db_session) -> None:
    from openai import RateLimitError

    exc = RateLimitError(
        "You exceeded your current quota",
        response=MagicMock(status_code=429),
        body={"error": {"code": "insufficient_quota", "type": "insufficient_quota"}},
    )
    assert is_openai_quota_exhausted(exc) is True
    assert is_job_error_retryable(exc) is False
    exhausted = RateLimitError(
        "credit_balance_exhausted",
        response=MagicMock(status_code=429),
        body={"error": {"code": "credit_balance_exhausted"}},
    )
    assert is_job_error_retryable(exhausted) is False
    queue = JobQueueService(db_session)
    job = queue.enqueue(
        JOB_TYPE_EMBED_OBJECT,
        {"object_id": str(uuid4()), "embedding_input_signature": "sig"},
        BOOTSTRAP_USER_ID,
    )
    claimed = queue.claim_next()
    assert claimed is not None
    queue.mark_retry(claimed.id, "insufficient_quota", retryable=False)
    stored = queue.get_job(job.id)
    assert stored is not None
    assert stored.status == JOB_STATUS_FAILED
    assert stored.attempts == 1
    assert stored.attempts < MAX_JOB_ATTEMPTS


def test_canonical_text_omits_compact_housekeeping(db_session) -> None:
    event = _yandex_event(db_session)
    text = canonical_embedding_text(event)
    assert "etag" not in text
    assert "event_href" not in text
    assert "last_modified" not in text
    assert "weekly standup" in text
    assert "Room 1" in text
    assert "owner@example.com" in text
    assert "a@example.com" in text


def test_done_without_vector_enqueues_one_recovery_signed_job(db_session) -> None:
    note = _note(db_session, "Recover me", body="body")
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    first = _embed_jobs(db_session)[0]
    _run_embed(db_session, first.payload, service)
    first.status = JOB_STATUS_DONE
    db_session.flush()
    db_session.refresh(note)
    assert note.embedding is not None
    assert note.embedding_signature == embedding_input_signature(note)
    note.embedding = None
    note.embedding_signature = None
    db_session.flush()
    current_sig = embedding_input_signature(note)
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    jobs = _embed_jobs(db_session)
    assert first.status == JOB_STATUS_DONE
    assert any(job.id == first.id and job.status == JOB_STATUS_DONE for job in jobs)
    recovery = [
        job
        for job in jobs
        if job.id != first.id
        and job.payload.get("embedding_input_signature") == current_sig
        and job.status == JOB_STATUS_PENDING
    ]
    assert len(recovery) == 1
    assert len(service.calls) == 1
    _run_embed(db_session, recovery[0].payload, service)
    assert len(service.calls) == 2
    recovery[0].status = JOB_STATUS_DONE
    db_session.flush()
    db_session.refresh(note)
    assert note.embedding is not None
    assert note.embedding_signature == current_sig
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    assert len(_embed_jobs(db_session)) == 2
    _run_embed(db_session, recovery[0].payload, service)
    assert len(service.calls) == 2


def test_unsigned_job_does_not_enqueue_downstream_before_signed_success(db_session) -> None:
    _enable_auto_label(db_session)
    note = _note(db_session, "New unsigned", body="body")
    service = CountingEmbeddingService()
    unsigned = JobQueueService(db_session).enqueue(
        JOB_TYPE_EMBED_OBJECT,
        {"object_id": str(note.id)},
        BOOTSTRAP_USER_ID,
    )
    _run_embed(db_session, unsigned.payload, service)
    assert service.calls == []
    signed = [
        job
        for job in _embed_jobs(db_session)
        if job.payload.get("embedding_input_signature") == embedding_input_signature(note)
    ]
    assert len(signed) == 1
    assert _correlate_jobs(db_session) == []
    assert _auto_label_jobs(db_session) == []
    _run_embed(db_session, signed[0].payload, service)
    assert len(service.calls) == 1
    assert len(_correlate_jobs(db_session)) == 1
    assert len(_auto_label_jobs(db_session)) == 1


def test_stale_signed_job_does_not_enqueue_downstream_before_current_success(
    db_session,
) -> None:
    _enable_auto_label(db_session)
    note = _note(db_session, "S1", body="one")
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    stale = _embed_jobs(db_session)[0]
    _run_embed(db_session, stale.payload, service)
    stale.status = JOB_STATUS_DONE
    db_session.flush()
    first_corr = len(_correlate_jobs(db_session))
    first_auto = len(_auto_label_jobs(db_session))
    note.body = "two"
    db_session.flush()
    _run_embed(db_session, stale.payload, service)
    assert len(service.calls) == 1
    current = next(job for job in _embed_jobs(db_session) if job.id != stale.id)
    assert len(_correlate_jobs(db_session)) == first_corr
    assert len(_auto_label_jobs(db_session)) == first_auto
    _run_embed(db_session, current.payload, service)
    assert len(service.calls) == 2
    assert len(_correlate_jobs(db_session)) == first_corr + 1
    assert len(_auto_label_jobs(db_session)) == first_auto + 1


def test_stale_embedding_model_does_not_enqueue_downstream_before_current_success(
    db_session, monkeypatch
) -> None:
    _enable_auto_label(db_session)
    note = _note(db_session, "Model", body="text")
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    stale = _embed_jobs(db_session)[0]
    _run_embed(db_session, stale.payload, service)
    stale.status = JOB_STATUS_DONE
    db_session.flush()
    first_corr = len(_correlate_jobs(db_session))
    monkeypatch.setattr(
        "app.llm.embedding_text.effective_embedding_model",
        lambda: "text-embedding-3-large",
    )
    monkeypatch.setattr(
        "app.llm.embedding_text.embedding_input_version",
        lambda: "cost_guard_b2",
    )
    _run_embed(db_session, stale.payload, service)
    assert len(service.calls) == 1
    current_sig = embedding_input_signature(note)
    current = next(
        job
        for job in _embed_jobs(db_session)
        if job.payload.get("embedding_input_signature") == current_sig
    )
    assert len(_correlate_jobs(db_session)) == first_corr
    _run_embed(db_session, current.payload, service)
    assert len(service.calls) == 2
    assert len(_correlate_jobs(db_session)) == first_corr


def test_unsigned_housekeeping_churn_with_done_vector_runs_downstream_signature_checks(
    db_session,
) -> None:
    _enable_auto_label(db_session)
    event = _yandex_event(db_session)
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, event.id, BOOTSTRAP_USER_ID)
    done = _embed_jobs(db_session)[0]
    _run_embed(db_session, done.payload, service)
    done.status = JOB_STATUS_DONE
    db_session.flush()
    first_corr_sig = correlation_input_signature(event)
    first_corr_count = len(_correlate_jobs(db_session))
    first_auto_count = len(_auto_label_jobs(db_session))
    event.metadata_ = {
        **dict(event.metadata_ or {}),
        "etag": "etag-churned",
        "href": "/moved.ics",
        "last_modified": "20260912T000000Z",
    }
    flag_modified(event, "metadata_")
    db_session.flush()
    unsigned = JobQueueService(db_session).enqueue(
        JOB_TYPE_EMBED_OBJECT,
        {"object_id": str(event.id)},
        BOOTSTRAP_USER_ID,
    )
    _run_embed(db_session, unsigned.payload, service)
    assert len(service.calls) == 1
    assert len(_embed_jobs(db_session)) == 2
    assert correlation_input_signature(event) == first_corr_sig
    assert len(_correlate_jobs(db_session)) == first_corr_count
    assert len(_auto_label_jobs(db_session)) == first_auto_count


def test_done_current_signature_with_vector_zero_paid_embed_downstream_independent(
    db_session,
) -> None:
    event = _yandex_event(db_session)
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, event.id, BOOTSTRAP_USER_ID)
    job = _embed_jobs(db_session)[0]
    _run_embed(db_session, job.payload, service)
    job.status = JOB_STATUS_DONE
    db_session.flush()
    first_corr = len(_correlate_jobs(db_session))
    event.metadata_ = {**dict(event.metadata_ or {}), "thread_id": "thread-2"}
    flag_modified(event, "metadata_")
    event.occurred_at = datetime(2026, 9, 11, 15, 0, tzinfo=UTC)
    db_session.flush()
    enqueue_embed_object(db_session, event.id, BOOTSTRAP_USER_ID)
    assert len(_embed_jobs(db_session)) == 1
    assert len(service.calls) == 1
    assert len(_correlate_jobs(db_session)) == first_corr + 1


class _FailingEmbeddingService:
    def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding provider unavailable")


def test_aba_semantic_revision_does_not_reuse_stale_vector(db_session) -> None:
    note = _note(db_session, "Title A", body="same-body")
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    job_a = _embed_jobs(db_session)[0]
    _run_embed(db_session, job_a.payload, service)
    job_a.status = JOB_STATUS_DONE
    db_session.flush()
    sig_a = embedding_input_signature(note)
    db_session.refresh(note)
    assert note.embedding_signature == sig_a
    note.title = "Title B"
    db_session.flush()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    job_b = next(job for job in _embed_jobs(db_session) if job.id != job_a.id)
    _run_embed(db_session, job_b.payload, service)
    job_b.status = JOB_STATUS_DONE
    db_session.flush()
    sig_b = embedding_input_signature(note)
    db_session.refresh(note)
    assert note.embedding_signature == sig_b
    assert sig_b != sig_a
    note.title = "Title A"
    db_session.flush()
    assert embedding_input_signature(note) == sig_a
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    pending_a = [
        job
        for job in _embed_jobs(db_session)
        if job.status == JOB_STATUS_PENDING
        and job.payload.get("embedding_input_signature") == sig_a
    ]
    assert len(pending_a) == 1
    _run_embed(db_session, pending_a[0].payload, service)
    assert len(service.calls) == 3
    db_session.refresh(note)
    assert note.embedding_signature == sig_a
    assert note.embedding is not None


def test_model_version_aba_does_not_falsely_prove_current_vector(
    db_session, monkeypatch
) -> None:
    from app.llm.embedding_text import effective_embedding_model

    original_model = effective_embedding_model()
    note = _note(db_session, "Model ABA", body="text")
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    job_m1 = _embed_jobs(db_session)[0]
    _run_embed(db_session, job_m1.payload, service)
    job_m1.status = JOB_STATUS_DONE
    db_session.flush()
    sig_m1 = embedding_input_signature(note)
    monkeypatch.setattr(
        "app.llm.embedding_text.effective_embedding_model",
        lambda: "text-embedding-3-large",
    )
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    job_m2 = next(job for job in _embed_jobs(db_session) if job.id != job_m1.id)
    _run_embed(db_session, job_m2.payload, service)
    job_m2.status = JOB_STATUS_DONE
    db_session.flush()
    db_session.refresh(note)
    assert note.embedding_signature != sig_m1
    monkeypatch.setattr(
        "app.llm.embedding_text.effective_embedding_model",
        lambda: original_model,
    )
    assert embedding_input_signature(note) == sig_m1
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    pending_m1 = [
        job
        for job in _embed_jobs(db_session)
        if job.status == JOB_STATUS_PENDING
        and job.payload.get("embedding_input_signature") == sig_m1
    ]
    assert len(pending_m1) == 1
    _run_embed(db_session, pending_m1[0].payload, service)
    assert len(service.calls) == 3
    db_session.refresh(note)
    assert note.embedding_signature == sig_m1


def test_null_provenance_on_existing_vector_enqueues_lazy_current_job(db_session) -> None:
    note = _note(db_session, "Legacy vector", body="body")
    note.embedding = FakeEmbeddingService().embed(canonical_embedding_text(note))
    note.embedding_signature = None
    db_session.flush()
    service = CountingEmbeddingService()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    jobs = [
        job
        for job in _embed_jobs(db_session)
        if job.payload.get("embedding_input_signature") == embedding_input_signature(note)
    ]
    assert len(jobs) == 1
    _run_embed(db_session, jobs[0].payload, service)
    assert len(service.calls) == 1
    db_session.refresh(note)
    assert note.embedding_signature == embedding_input_signature(note)


def test_sync_graph_write_stores_matching_embedding_signature(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService())
    obj = graph.create_object(
        ObjectCreate(kind="note", title="Sync A", body="body", origin="user")
    )
    assert obj.embedding is not None
    assert obj.embedding_signature == embedding_input_signature(obj)
    graph.update_object(obj.id, ObjectUpdate(title="Sync B"))
    db_session.refresh(obj)
    assert obj.embedding is not None
    assert obj.embedding_signature == embedding_input_signature(obj)


def test_sync_embedding_failure_clears_vector_and_signature(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, FakeEmbeddingService())
    obj = graph.create_object(
        ObjectCreate(kind="note", title="Will fail", body="body", origin="user")
    )
    assert obj.embedding_signature is not None
    failing = GraphService(db_session, BOOTSTRAP_USER_ID, _FailingEmbeddingService())
    failing.update_object(obj.id, ObjectUpdate(title="Changed"))
    db_session.refresh(obj)
    assert obj.embedding is None
    assert obj.embedding_signature is None


def test_semantic_change_during_embedding_api_discards_stale_vector(db_session) -> None:
    _enable_auto_label(db_session)
    note = _note(db_session, "During", body="before")
    inner = FakeEmbeddingService()

    class _MutatingDuringEmbed:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def embed(self, text: str) -> list[float]:
            self.calls.append(text)
            note.body = "after-during-call"
            db_session.flush()
            return inner.embed(text)

    service = _MutatingDuringEmbed()
    enqueue_embed_object(db_session, note.id, BOOTSTRAP_USER_ID)
    stale = _embed_jobs(db_session)[0]
    _run_embed(db_session, stale.payload, service)
    assert len(service.calls) == 1
    db_session.refresh(note)
    assert note.embedding is None
    assert note.embedding_signature is None
    assert _correlate_jobs(db_session) == []
    assert _auto_label_jobs(db_session) == []
    current_sig = embedding_input_signature(note)
    current = [
        job
        for job in _embed_jobs(db_session)
        if job.id != stale.id
        and job.payload.get("embedding_input_signature") == current_sig
    ]
    assert len(current) == 1
    _run_embed(db_session, current[0].payload, service)
    assert len(service.calls) == 2
    db_session.refresh(note)
    assert note.embedding_signature == current_sig
    assert len(_correlate_jobs(db_session)) == 1


def test_sync_technical_metadata_patch_zero_additional_embedding_calls(
    db_session,
) -> None:
    service = CountingEmbeddingService()
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, service)
    obj = graph.create_object(
        ObjectCreate(
            kind="note",
            title="Stable",
            body="body",
            origin="user",
            metadata={"etag": "etag-1", "last_modified": "20260911T090000Z"},
        )
    )
    assert len(service.calls) == 1
    sig = embedding_input_signature(obj)
    graph.update_object(
        obj.id,
        ObjectUpdate(metadata={"etag": "etag-2", "last_modified": "20260911T100000Z"}),
    )
    db_session.refresh(obj)
    assert embedding_input_signature(obj) == sig
    assert len(service.calls) == 1
    assert obj.embedding_signature == sig
    assert obj.embedding is not None


def test_sync_semantic_metadata_patch_one_additional_embedding_call(db_session) -> None:
    service = CountingEmbeddingService()
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, service)
    obj = graph.create_object(
        ObjectCreate(
            kind="note",
            title="Stable",
            body="body",
            origin="user",
            metadata={"location": "Room 1"},
        )
    )
    assert len(service.calls) == 1
    graph.update_object(obj.id, ObjectUpdate(metadata={"location": "Room 2"}))
    db_session.refresh(obj)
    assert len(service.calls) == 2
    assert obj.embedding is not None
    assert obj.embedding_signature == embedding_input_signature(obj)


def test_sync_title_body_change_one_new_provider_call(db_session) -> None:
    service = CountingEmbeddingService()
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, service)
    obj = graph.create_object(
        ObjectCreate(kind="note", title="Title A", body="body-a", origin="user")
    )
    assert len(service.calls) == 1
    graph.update_object(obj.id, ObjectUpdate(title="Title B", body="body-b"))
    db_session.refresh(obj)
    assert len(service.calls) == 2
    assert obj.embedding_signature == embedding_input_signature(obj)


def test_sync_null_provenance_lazy_one_provider_call(db_session) -> None:
    service = CountingEmbeddingService()
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, service)
    obj = graph.create_object(
        ObjectCreate(kind="note", title="Legacy vector", body="body", origin="user")
    )
    assert len(service.calls) == 1
    obj.embedding_signature = None
    db_session.flush()
    graph.update_object(obj.id, ObjectUpdate(metadata={"etag": "noop"}))
    db_session.refresh(obj)
    assert len(service.calls) == 2
    assert obj.embedding is not None
    assert obj.embedding_signature == embedding_input_signature(obj)


def test_sync_aba_does_not_reuse_historical_vector(db_session) -> None:
    service = CountingEmbeddingService()
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, service)
    obj = graph.create_object(
        ObjectCreate(kind="note", title="Title A", body="same-body", origin="user")
    )
    sig_a = embedding_input_signature(obj)
    assert obj.embedding_signature == sig_a
    graph.update_object(obj.id, ObjectUpdate(title="Title B"))
    db_session.refresh(obj)
    sig_b = embedding_input_signature(obj)
    assert sig_b != sig_a
    assert obj.embedding_signature == sig_b
    graph.update_object(obj.id, ObjectUpdate(title="Title A"))
    db_session.refresh(obj)
    assert len(service.calls) == 3
    assert obj.embedding is not None
    assert obj.embedding_signature == sig_a


def test_sync_mutation_during_provider_call_discards_stale_vector(db_session) -> None:
    inner = FakeEmbeddingService()
    created: list[Object] = []

    class _MutatingDuringEmbed:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def embed(self, text: str) -> list[float]:
            self.calls.append(text)
            if len(self.calls) == 2:
                created[0].body = "after-during-call"
                db_session.flush()
            return inner.embed(text)

    service = _MutatingDuringEmbed()
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, service)
    obj = graph.create_object(
        ObjectCreate(kind="note", title="During", body="before", origin="user")
    )
    created.append(obj)
    create_sig = embedding_input_signature(obj)
    assert len(service.calls) == 1
    graph.update_object(obj.id, ObjectUpdate(title="During-updated"))
    db_session.refresh(obj)
    assert len(service.calls) == 2
    assert obj.embedding_signature == create_sig
    current_sig = embedding_input_signature(obj)
    assert current_sig != create_sig
    pending = [
        job
        for job in _embed_jobs(db_session)
        if job.payload.get("embedding_input_signature") == current_sig
    ]
    assert len(pending) == 1


def test_migration_0035_adds_embedding_signature_column(db_session) -> None:
    from pathlib import Path

    from sqlalchemy import inspect

    module_path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/0035_object_embedding_signature.py"
    )
    text_src = module_path.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "0034"' in text_src
    assert "embedding_signature" in text_src
    columns = {col["name"] for col in inspect(db_session.bind).get_columns("objects")}
    assert "embedding_signature" in columns
