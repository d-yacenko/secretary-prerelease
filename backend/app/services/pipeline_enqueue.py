"""Job enqueue helpers for correlation and semantic summary pipeline."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_audit.context import get_active_trace
from app.db.models import Job
from app.jobs.constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_CORRELATE_OBJECT,
    JOB_TYPE_EMBED_OBJECT,
    JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
    JOB_TYPE_SUMMARIZE_RESOURCE,
)
from app.llm.embedding_text import embed_job_payload, embedding_input_signature
from app.services.correlation_constants import CORRELATION_TRIGGER_KINDS
from app.services.correlation_input import correlation_input_signature
from app.services.embedding_index import object_has_current_embedding_provenance
from app.services.job_queue_service import JobQueueService


def _active_parent_trace_id() -> str | None:
    active = get_active_trace()
    if active is None:
        return None
    return str(active.trace_id)


def enqueue_extract_explicit_resource_content(
    session: Session,
    object_id: UUID,
    user_id: UUID,
    expected_revision: str | None,
    extraction_version: str,
    extraction_baseline: str | None = None,
) -> None:
    if _has_pending_job(
        session,
        user_id,
        JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
        object_id,
        {
            "expected_content_revision": expected_revision,
            "extraction_version": extraction_version,
            "extraction_baseline": extraction_baseline,
        },
    ):
        return
    payload: dict = {
        "object_id": str(object_id),
        "expected_content_revision": expected_revision,
        "extraction_version": extraction_version,
        "extraction_baseline": extraction_baseline,
    }
    parent_trace_id = _active_parent_trace_id()
    if parent_trace_id is not None:
        payload["parent_trace_id"] = parent_trace_id
    JobQueueService(session).enqueue(
        JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
        payload,
        user_id=user_id,
    )


def enqueue_summarize_resource(
    session: Session,
    object_id: UUID,
    user_id: UUID,
    expected_revision: str | None,
    expected_representation_generation: int | None = None,
) -> None:
    generation = expected_representation_generation
    if generation is None:
        from app.db.models import Object
        from app.services.representation_generation import get_representation_generation

        obj = session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == user_id)
        )
        generation = get_representation_generation(obj.metadata_ if obj is not None else None)
    dedupe_extra = {
        "expected_revision": expected_revision,
        "expected_representation_generation": generation,
    }
    if _has_pending_job(
        session,
        user_id,
        JOB_TYPE_SUMMARIZE_RESOURCE,
        object_id,
        dedupe_extra,
    ):
        return
    payload: dict = {
        "object_id": str(object_id),
        "expected_revision": expected_revision,
        "expected_representation_generation": generation,
    }
    parent_trace_id = _active_parent_trace_id()
    if parent_trace_id is not None:
        payload["parent_trace_id"] = parent_trace_id
    JobQueueService(session).enqueue(
        JOB_TYPE_SUMMARIZE_RESOURCE,
        payload,
        user_id=user_id,
    )


def enqueue_correlate_object(
    session: Session,
    object_id: UUID,
    user_id: UUID,
    object_kind: str,
) -> None:
    if object_kind not in CORRELATION_TRIGGER_KINDS:
        return
    from app.db.models import Object

    obj = session.scalar(
        select(Object).where(Object.id == object_id, Object.user_id == user_id)
    )
    if obj is None:
        return
    signature = correlation_input_signature(obj)
    if _has_correlation_signature_job(session, user_id, object_id, signature):
        return
    payload: dict = {
        "object_id": str(object_id),
        "correlation_input_signature": signature,
    }
    parent_trace_id = _active_parent_trace_id()
    if parent_trace_id is not None:
        payload["parent_trace_id"] = parent_trace_id
    JobQueueService(session).enqueue(
        JOB_TYPE_CORRELATE_OBJECT,
        payload,
        user_id=user_id,
    )


def enqueue_embed_object(session: Session, object_id: UUID, user_id: UUID) -> None:
    from app.db.models import Object

    obj = session.scalar(
        select(Object).where(Object.id == object_id, Object.user_id == user_id)
    )
    if obj is None:
        return
    signature = embedding_input_signature(obj)
    if _has_active_embedding_signature_job(session, user_id, object_id, signature):
        return
    if object_has_current_embedding_provenance(obj, signature):
        enqueue_correlate_object(session, object_id, user_id, obj.kind)
        enqueue_auto_label_object(session, object_id, user_id)
        return
    payload = embed_job_payload(obj, parent_trace_id=_active_parent_trace_id())
    JobQueueService(session).enqueue(
        JOB_TYPE_EMBED_OBJECT,
        payload,
        user_id=user_id,
    )


def enqueue_auto_label_object(
    session: Session,
    object_id: UUID,
    user_id: UUID,
    *,
    parent_trace_id=None,
) -> None:
    from app.services.auto_label_service import enqueue_auto_label_object as enqueue

    enqueue(session, object_id, user_id, parent_trace_id=parent_trace_id)


def _has_correlation_signature_job(
    session: Session,
    user_id: UUID,
    object_id: UUID,
    signature: str,
) -> bool:
    return _has_signature_job(
        session,
        user_id,
        JOB_TYPE_CORRELATE_OBJECT,
        object_id,
        "correlation_input_signature",
        signature,
    )


def _has_active_embedding_signature_job(
    session: Session,
    user_id: UUID,
    object_id: UUID,
    signature: str,
) -> bool:
    return _has_signature_job(
        session,
        user_id,
        JOB_TYPE_EMBED_OBJECT,
        object_id,
        "embedding_input_signature",
        signature,
        statuses=(JOB_STATUS_PENDING, JOB_STATUS_RUNNING),
    )


def _has_signature_job(
    session: Session,
    user_id: UUID,
    job_type: str,
    object_id: UUID,
    signature_key: str,
    signature: str,
    *,
    statuses: tuple[str, ...] = (JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_DONE),
) -> bool:
    existing_id = session.scalar(
        select(Job.id)
        .where(
            Job.user_id == user_id,
            Job.type == job_type,
            Job.status.in_(statuses),
            Job.payload["object_id"].as_string() == str(object_id),
            Job.payload[signature_key].as_string() == signature,
        )
        .limit(1)
    )
    return existing_id is not None


def _has_pending_job(
    session: Session,
    user_id: UUID,
    job_type: str,
    object_id: UUID,
    extra: dict,
) -> bool:
    jobs = session.scalars(
        select(Job).where(
            Job.user_id == user_id,
            Job.type == job_type,
            Job.status.in_((JOB_STATUS_PENDING, JOB_STATUS_RUNNING)),
        )
    )
    object_key = str(object_id)
    for job in jobs:
        payload = job.payload or {}
        if payload.get("object_id") != object_key:
            continue
        for key, value in extra.items():
            if payload.get(key) != value:
                break
        else:
            return True
    return False
