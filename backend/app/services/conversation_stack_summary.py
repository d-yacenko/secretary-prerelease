"""Derived conversation-stack summaries stored as Representations."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Job, Object, Representation
from app.domain.telegram_mtproto_ai import telegram_mtproto_ai_eligible
from app.jobs.constants import (
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_SUMMARIZE_CONVERSATION_STACK,
)
from app.llm.summarizer import FakeSummarizer, Summarizer
from app.services.conversation_stack import ConversationStack, stack_content_fingerprint
from app.services.job_queue_service import JobQueueService
from app.services.representation_service import KIND_CONVERSATION_STACK_SUMMARY

CONVERSATION_STACK_SUMMARY_MAX_CHARS = 160
CONVERSATION_STACK_SUMMARY_INPUT_MAX_CHARS = 4000
CONVERSATION_STACK_SUMMARY_MAX_VARIANTS_PER_ANCHOR = 8
SUMMARY_RETRY_COOLDOWN = timedelta(minutes=15)
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|bearer)\s*[:=]\s*\S+"
)
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")


def _redact(text: str) -> str:
    cleaned = _SECRET_RE.sub("[redacted]", text)
    cleaned = _LONG_TOKEN_RE.sub("[redacted]", cleaned)
    return cleaned


def stack_input_text(objects: list[Object]) -> str:
    lines: list[str] = []
    for obj in objects:
        excerpt = (obj.body or obj.title or "").strip().replace("\n", " ")
        if len(excerpt) > 280:
            excerpt = excerpt[:277].rstrip() + "…"
        lines.append(_redact(f"{obj.title}: {excerpt}".strip(": ")))
    joined = "\n".join(lines)
    if len(joined) > CONVERSATION_STACK_SUMMARY_INPUT_MAX_CHARS:
        return joined[:CONVERSATION_STACK_SUMMARY_INPUT_MAX_CHARS]
    return joined


def find_current_stack_summary(
    session: Session, stack: ConversationStack
) -> Representation | None:
    if not stack.object_ids:
        return None
    anchor_id = stack.object_ids[-1]
    rows = session.scalars(
        select(Representation).where(
            Representation.object_id == anchor_id,
            Representation.kind == KIND_CONVERSATION_STACK_SUMMARY,
        )
    ).all()
    for row in rows:
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        if meta.get("stack_fingerprint") == stack.fingerprint and row.text:
            return row
    return None


def apply_summary_to_stack(
    session: Session, stack: ConversationStack
) -> ConversationStack:
    row = find_current_stack_summary(session, stack)
    if row is None:
        return stack
    return ConversationStack(
        stack_id=stack.stack_id,
        fingerprint=stack.fingerprint,
        object_ids=stack.object_ids,
        display_object_ids=stack.display_object_ids,
        provider=stack.provider,
        conversation_key=stack.conversation_key,
        conversation_label=stack.conversation_label,
        participants=stack.participants,
        message_count=stack.message_count,
        start_at=stack.start_at,
        end_at=stack.end_at,
        fallback_summary=stack.fallback_summary,
        semantic_summary=row.text,
        summary_status="current",
        marker_side=stack.marker_side,
    )


def _active_summary_job(session: Session, user_id: UUID, fingerprint: str) -> Job | None:
    for job in session.scalars(
        select(Job).where(
            Job.user_id == user_id,
            Job.type == JOB_TYPE_SUMMARIZE_CONVERSATION_STACK,
            Job.status.in_((JOB_STATUS_PENDING, JOB_STATUS_RUNNING)),
        )
    ):
        if (job.payload or {}).get("stack_fingerprint") == fingerprint:
            return job
    return None


def _job_timestamp(job: Job) -> datetime:
    stamp = job.updated_at or job.created_at
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=UTC)
    return stamp


def _recent_failed_summary_job(session: Session, user_id: UUID, fingerprint: str) -> Job | None:
    newest: Job | None = None
    newest_at: datetime | None = None
    for job in session.scalars(
        select(Job).where(
            Job.user_id == user_id,
            Job.type == JOB_TYPE_SUMMARIZE_CONVERSATION_STACK,
            Job.status == JOB_STATUS_FAILED,
        )
    ):
        if (job.payload or {}).get("stack_fingerprint") != fingerprint:
            continue
        stamp = _job_timestamp(job)
        if newest_at is None or stamp > newest_at:
            newest = job
            newest_at = stamp
    if newest is None or newest_at is None:
        return None
    if datetime.now(UTC) - newest_at < SUMMARY_RETRY_COOLDOWN:
        return newest
    return None


def enqueue_summarize_conversation_stack(
    session: Session,
    user_id: UUID,
    stack: ConversationStack,
) -> Job | None:
    objects = list(
        session.scalars(
            select(Object).where(
                Object.user_id == user_id,
                Object.id.in_(list(stack.object_ids)),
            )
        )
    )
    if len(objects) != len(stack.object_ids) or any(
        not telegram_mtproto_ai_eligible(session, obj) for obj in objects
    ):
        return None
    if find_current_stack_summary(session, stack) is not None:
        return None
    existing = _active_summary_job(session, user_id, stack.fingerprint)
    if existing is not None:
        return existing
    failed = _recent_failed_summary_job(session, user_id, stack.fingerprint)
    if failed is not None:
        return None
    payload = {
        "stack_fingerprint": stack.fingerprint,
        "conversation_key": stack.conversation_key,
        "object_ids": [str(item) for item in stack.object_ids],
        "anchor_object_id": str(stack.object_ids[-1]),
        "content_fingerprints": {
            str(obj_id): None for obj_id in stack.object_ids
        },
    }
    return JobQueueService(session).enqueue(
        JOB_TYPE_SUMMARIZE_CONVERSATION_STACK,
        payload,
        user_id=user_id,
    )


def persist_stack_summary(
    session: Session,
    *,
    stack: ConversationStack,
    objects: list[Object],
    text: str,
) -> Representation:
    anchor = objects[-1]
    bounded = " ".join(text.split())
    if not bounded:
        raise ValueError("empty conversation stack summary")
    if len(bounded) > CONVERSATION_STACK_SUMMARY_MAX_CHARS:
        bounded = bounded[: CONVERSATION_STACK_SUMMARY_MAX_CHARS - 1].rstrip() + "…"
    identity_hash = hashlib.sha256(
        ",".join(str(obj.id) for obj in objects).encode("utf-8")
    ).hexdigest()
    content_hash = hashlib.sha256(
        "|".join(stack_content_fingerprint(obj) for obj in objects).encode("utf-8")
    ).hexdigest()
    metadata = {
        "stack_fingerprint": stack.fingerprint,
        "conversation_key": stack.conversation_key,
        "object_ids": [str(obj.id) for obj in objects],
        "identity_hash": identity_hash,
        "semantic_content_fingerprint": content_hash,
        "summary_version": 1,
    }
    existing = list(
        session.scalars(
            select(Representation).where(
                Representation.object_id == anchor.id,
                Representation.kind == KIND_CONVERSATION_STACK_SUMMARY,
            )
        )
    )
    matched = None
    for row in existing:
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        if meta.get("stack_fingerprint") == stack.fingerprint:
            matched = row
            break
    if matched is not None:
        matched.text = bounded
        matched.metadata_ = metadata
        session.flush()
        _prune_anchor_summary_variants(session, anchor.id, keep_id=matched.id)
        return matched
    row = Representation(
        object_id=anchor.id,
        kind=KIND_CONVERSATION_STACK_SUMMARY,
        text=bounded,
        metadata_=metadata,
    )
    session.add(row)
    session.flush()
    _prune_anchor_summary_variants(session, anchor.id, keep_id=row.id)
    return row


def _prune_anchor_summary_variants(
    session: Session, anchor_id: UUID, *, keep_id: UUID
) -> None:
    rows = list(
        session.scalars(
            select(Representation)
            .where(
                Representation.object_id == anchor_id,
                Representation.kind == KIND_CONVERSATION_STACK_SUMMARY,
            )
            .order_by(
                Representation.updated_at.desc(),
                Representation.created_at.desc(),
                Representation.id.desc(),
            )
        )
    )
    keep = {keep_id}
    for row in rows:
        if len(keep) >= CONVERSATION_STACK_SUMMARY_MAX_VARIANTS_PER_ANCHOR:
            break
        keep.add(row.id)
    for row in rows:
        if row.id not in keep:
            session.delete(row)
    session.flush()


class ConversationStackSummaryService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        summarizer: Summarizer | None = None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._summarizer = summarizer or FakeSummarizer(
            max_chars=CONVERSATION_STACK_SUMMARY_MAX_CHARS
        )

    def generate_for_payload(self, payload: dict) -> str | None:
        from app.services.conversation_stack import (
            compute_stack_fingerprint,
            deterministic_fallback_summary,
        )

        object_ids = [UUID(str(item)) for item in payload.get("object_ids") or []]
        expected = str(payload.get("stack_fingerprint") or "")
        if not object_ids or not expected:
            return None
        objects = list(
            self._session.scalars(
                select(Object).where(
                    Object.user_id == self._user_id,
                    Object.id.in_(object_ids),
                )
            ).all()
        )
        if any(not telegram_mtproto_ai_eligible(self._session, obj) for obj in objects):
            return None
        by_id = {obj.id: obj for obj in objects}
        ordered = [by_id[item] for item in object_ids if item in by_id]
        if len(ordered) != len(object_ids):
            return None
        conversation_key = str(payload.get("conversation_key") or "")
        fingerprint = compute_stack_fingerprint(
            conversation_key=conversation_key,
            members=ordered,
        )
        if fingerprint != expected:
            return None
        source = stack_input_text(ordered)
        if not source.strip():
            return None
        summary = self._summarizer.summarize(
            "Напиши одно короткое фактическое предложение по переписке. "
            "Только по тексту. Без рекомендаций и домыслов.\n\n" + source
        )
        normalized = " ".join(str(summary or "").split())
        if not normalized:
            raise ValueError("empty conversation stack summary")
        stack = ConversationStack(
            stack_id=fingerprint,
            fingerprint=fingerprint,
            object_ids=tuple(obj.id for obj in ordered),
            display_object_ids=tuple(obj.id for obj in ordered),
            provider=ordered[0].provider or "unknown",
            conversation_key=conversation_key,
            conversation_label=ordered[0].title,
            participants=(),
            message_count=len(ordered),
            start_at=ordered[0].occurred_at or ordered[0].created_at,
            end_at=ordered[-1].occurred_at or ordered[-1].created_at,
            fallback_summary=deterministic_fallback_summary(
                provider=ordered[0].provider or "unknown",
                conversation_label=ordered[0].title,
                message_count=len(ordered),
                start_at=ordered[0].occurred_at or ordered[0].created_at,
                end_at=ordered[-1].occurred_at or ordered[-1].created_at,
            ),
        )
        persist_stack_summary(
            self._session, stack=stack, objects=ordered, text=normalized
        )
        return normalized
