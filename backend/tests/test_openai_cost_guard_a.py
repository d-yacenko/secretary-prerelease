"""OpenAI Cost Guard A — correlation input signature idempotency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ObjectCreate
from app.db.models import Job, Object
from app.jobs.constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_TYPE_CORRELATE_OBJECT,
    MAX_JOB_ATTEMPTS,
)
from app.jobs.handlers import handle_correlate_object
from app.llm.correlation_judge import (
    JUDGE_INSTRUCTIONS,
    FakeCorrelationJudge,
    _parse_judge_response,
)
from app.services.auto_label_constants import AUTO_LABEL_VERSION
from app.services.background_ai_errors import is_openai_quota_exhausted
from app.services.correlation_constants import (
    CORRELATION_BACKGROUND_REASONING_EFFORT,
    CORRELATION_BACKGROUND_VERBOSITY,
    CORRELATION_MAX_PROPOSED_EDGES,
    CORRELATION_MIN_CONFIDENCE,
    SEMANTIC_SUMMARY_METADATA_KEY,
)
from app.services.correlation_input import correlation_input_signature
from app.services.graph_service import GraphService
from app.services.job_queue_service import JobQueueService, is_job_error_retryable
from app.services.pipeline_enqueue import enqueue_correlate_object
from app.users.bootstrap import BOOTSTRAP_USER_ID


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


def _graph(db_session) -> GraphService:
    return GraphService(db_session, BOOTSTRAP_USER_ID)


def _note(db_session, title: str = "Note", **kwargs) -> Object:
    return _graph(db_session).create_object(
        ObjectCreate(kind="note", title=title, origin="user", **kwargs)
    )


def _calendar_event(db_session, title: str = "Standup") -> Object:
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
                "updated": "2026-09-10T09:00:00Z",
                "html_link": "https://calendar.example/event-1",
            },
        )
    )
    obj.occurred_at = start
    db_session.flush()
    return obj


def _correlate_jobs(db_session) -> list[Job]:
    return list(
        db_session.scalars(
            select(Job)
            .where(Job.type == JOB_TYPE_CORRELATE_OBJECT)
            .order_by(Job.created_at, Job.id)
        )
    )


def _run_correlate(db_session, job: Job, judge: FakeCorrelationJudge) -> None:
    with patch(
        "app.jobs.handlers.create_correlation_judge_from_effective",
        return_value=judge,
    ), patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch.object(
        db_session, "close", lambda: None
    ):
        handle_correlate_object(db_session, None, job.payload, BOOTSTRAP_USER_ID)


def test_done_signature_is_idempotent_one_model_call(db_session) -> None:
    note = _note(db_session, "Stable")
    peer = _note(db_session, "Peer", metadata={"sender": "a@example.com"})
    note.metadata_ = {"sender": "a@example.com"}
    note.occurred_at = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    peer.occurred_at = datetime(2026, 9, 10, 12, 30, tzinfo=UTC)
    db_session.flush()
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)
    jobs = _correlate_jobs(db_session)
    assert len(jobs) == 1
    judge = FakeCorrelationJudge()
    _run_correlate(db_session, jobs[0], judge)
    jobs[0].status = JOB_STATUS_DONE
    db_session.flush()
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)
    assert len(_correlate_jobs(db_session)) == 1
    assert judge.calls == 1


def test_calendar_metadata_only_churn_does_not_enqueue(db_session) -> None:
    event = _calendar_event(db_session)
    enqueue_correlate_object(db_session, event.id, BOOTSTRAP_USER_ID, event.kind)
    job = _correlate_jobs(db_session)[0]
    first_sig = job.payload["correlation_input_signature"]
    job.status = JOB_STATUS_DONE
    db_session.flush()
    event.metadata_ = {
        **event.metadata_,
        "etag": "etag-2",
        "last_modified": "20260911T090000Z",
        "event_href": "/calendars/a/event-1-moved.ics",
        "updated": "2026-09-11T09:00:00Z",
        "html_link": "https://calendar.example/event-1?updated=1",
        "operational_href_cursor": "cursor-9",
    }
    event.updated_at = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)
    db_session.flush()
    assert correlation_input_signature(event) == first_sig
    enqueue_correlate_object(db_session, event.id, BOOTSTRAP_USER_ID, event.kind)
    assert len(_correlate_jobs(db_session)) == 1


def test_semantic_field_change_enqueues_new_signature(db_session) -> None:
    note = _note(db_session, "Title A", body="body-a", metadata={"thread_id": "t1", "from": "a@x.com"})
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)
    first = _correlate_jobs(db_session)[0]
    first.status = JOB_STATUS_DONE
    db_session.flush()

    note.title = "Title B"
    db_session.flush()
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)
    note.body = "body-b"
    db_session.flush()
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)
    note.metadata_ = {**note.metadata_, SEMANTIC_SUMMARY_METADATA_KEY: "summary-b"}
    db_session.flush()
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)
    note.occurred_at = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
    db_session.flush()
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)
    note.metadata_ = {**note.metadata_, "thread_id": "t2"}
    db_session.flush()
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)
    note.metadata_ = {**note.metadata_, "from": "b@x.com"}
    db_session.flush()
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)

    jobs = _correlate_jobs(db_session)
    sigs = [job.payload["correlation_input_signature"] for job in jobs]
    assert len(jobs) == 7
    assert len(set(sigs)) == 7


def test_stale_queued_revision_makes_zero_model_calls(db_session) -> None:
    note = _note(db_session, "S1", body="one", metadata={"from": "a@x.com"})
    peer = _note(db_session, "Peer", metadata={"from": "a@x.com"})
    note.occurred_at = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    peer.occurred_at = datetime(2026, 9, 10, 12, 15, tzinfo=UTC)
    db_session.flush()
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)
    stale = _correlate_jobs(db_session)[0]
    note.body = "two"
    db_session.flush()
    judge = FakeCorrelationJudge()
    _run_correlate(db_session, stale, judge)
    assert judge.calls == 0
    jobs = _correlate_jobs(db_session)
    assert len(jobs) == 2
    current = next(job for job in jobs if job.id != stale.id)
    _run_correlate(db_session, current, judge)
    assert judge.calls == 1
    _run_correlate(db_session, stale, judge)
    assert judge.calls == 1
    assert len(_correlate_jobs(db_session)) == 2


def test_zero_match_success_is_idempotent(db_session) -> None:
    note = _note(db_session, "Lonely", metadata={"from": "a@x.com"})
    peer = _note(db_session, "Other", metadata={"from": "a@x.com"})
    note.occurred_at = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    peer.occurred_at = datetime(2026, 9, 10, 12, 20, tzinfo=UTC)
    db_session.flush()
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)
    job = _correlate_jobs(db_session)[0]
    judge = FakeCorrelationJudge()
    _run_correlate(db_session, job, judge)
    job.status = JOB_STATUS_DONE
    db_session.flush()
    enqueue_correlate_object(db_session, note.id, BOOTSTRAP_USER_ID, note.kind)
    assert len(_correlate_jobs(db_session)) == 1
    assert judge.calls == 1


def test_transient_rate_limit_is_retryable() -> None:
    from openai import RateLimitError

    exc = RateLimitError(
        "rate limited",
        response=MagicMock(status_code=429),
        body={"error": {"code": "rate_limit_exceeded", "type": "too_many_requests"}},
    )
    assert is_openai_quota_exhausted(exc) is False
    assert is_job_error_retryable(exc) is True


def test_transient_failure_reschedules_same_signature(db_session) -> None:
    queue = JobQueueService(db_session)
    job = queue.enqueue(
        JOB_TYPE_CORRELATE_OBJECT,
        {"object_id": str(uuid4()), "correlation_input_signature": "sig"},
        BOOTSTRAP_USER_ID,
    )
    claimed = queue.claim_next()
    assert claimed is not None
    queue.mark_retry(claimed.id, "rate limited", retryable=True)
    stored = queue.get_job(job.id)
    assert stored is not None
    assert stored.status == JOB_STATUS_PENDING
    assert stored.attempts == 1
    assert stored.payload["correlation_input_signature"] == "sig"


def test_permanent_quota_exhaustion_does_not_retry_three_times(db_session) -> None:
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
        JOB_TYPE_CORRELATE_OBJECT,
        {"object_id": str(uuid4()), "correlation_input_signature": "sig"},
        BOOTSTRAP_USER_ID,
    )
    claimed = queue.claim_next()
    assert claimed is not None
    assert claimed.attempts == 1
    queue.mark_retry(claimed.id, "insufficient_quota", retryable=False)
    stored = queue.get_job(job.id)
    assert stored is not None
    assert stored.status == JOB_STATUS_FAILED
    assert stored.attempts == 1
    assert stored.attempts < MAX_JOB_ATTEMPTS


def test_max_five_correlation_decisions_contract() -> None:
    assert CORRELATION_MAX_PROPOSED_EDGES == 5
    assert f"at most {CORRELATION_MAX_PROPOSED_EDGES}" in JUDGE_INSTRUCTIONS
    assert f"{CORRELATION_MIN_CONFIDENCE:.2f}" in JUDGE_INSTRUCTIONS
    assert CORRELATION_BACKGROUND_REASONING_EFFORT == "low"
    assert CORRELATION_BACKGROUND_VERBOSITY == "low"
    ids = [str(uuid4()) for _ in range(7)]
    payload = {
        "decisions": [
            {
                "target_object_id": ids[index],
                "relation_type": "related_to",
                "confidence": 0.81 + index * 0.01,
                "rationale": "ok",
            }
            for index in range(7)
        ]
    }
    import json

    parsed = _parse_judge_response(json.dumps(payload), set(ids))
    assert len(parsed.decisions) == 5
    assert parsed.decisions[0].confidence >= parsed.decisions[-1].confidence
    weak = {
        "decisions": [
            {
                "target_object_id": ids[0],
                "relation_type": "related_to",
                "confidence": 0.5,
                "rationale": "weak",
            }
        ]
    }
    assert _parse_judge_response(json.dumps(weak), {ids[0]}).decisions == ()


def test_auto_label_enqueue_path_unchanged(db_session) -> None:
    from app.db.models import UserSettings
    from app.jobs.constants import JOB_TYPE_AUTO_LABEL_OBJECT
    from app.services.auto_label_service import enqueue_auto_label_object
    from app.services.label_service import LabelService

    settings = db_session.get(UserSettings, BOOTSTRAP_USER_ID)
    if settings is None:
        settings = UserSettings(user_id=BOOTSTRAP_USER_ID, auto_label_enabled=True)
        db_session.add(settings)
    else:
        settings.auto_label_enabled = True
    db_session.flush()
    LabelService(db_session, BOOTSTRAP_USER_ID).create_label("Work")
    note = _note(db_session, "Label me", body="work")
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    jobs = list(
        db_session.scalars(select(Job).where(Job.type == JOB_TYPE_AUTO_LABEL_OBJECT))
    )
    assert len(jobs) == 1
    assert "classification_signature" in jobs[0].payload
    assert AUTO_LABEL_VERSION
    enqueue_auto_label_object(db_session, note.id, BOOTSTRAP_USER_ID)
    assert (
        len(list(db_session.scalars(select(Job).where(Job.type == JOB_TYPE_AUTO_LABEL_OBJECT))))
        == 1
    )
