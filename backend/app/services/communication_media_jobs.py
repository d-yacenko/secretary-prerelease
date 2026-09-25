"""Enqueue transcription for an eligible communication media child."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Object
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.domain.telegram_mtproto_ai import telegram_mtproto_ai_eligible
from app.jobs.constants import JOB_TYPE_TRANSCRIBE_COMMUNICATION_MEDIA
from app.services.job_queue_service import JobQueueService
from app.services.provenance import REJECTED_STATE

TRANSCRIBABLE_MEDIA_KINDS = frozenset({"voice", "audio"})


def maybe_enqueue_media_transcription(session: Session, parent: Object, child: Object) -> None:
    metadata = child.metadata_ or {}
    kind = str(metadata.get("media_kind") or "")
    if kind not in TRANSCRIBABLE_MEDIA_KINDS or parent.provider != "telegram":
        return
    if parent.user_id != child.user_id:
        return
    if parent.state == REJECTED_STATE or child.state == REJECTED_STATE:
        return
    if is_object_hidden_from_active_reads(parent) or is_object_hidden_from_active_reads(child):
        return
    if not telegram_mtproto_ai_eligible(session, parent):
        return
    descriptor_key = str(metadata.get("descriptor_key") or "")
    model = settings.openai_transcription_model.strip() or "unknown"
    JobQueueService(session).enqueue_once(
        JOB_TYPE_TRANSCRIBE_COMMUNICATION_MEDIA,
        {
            "media_object_id": str(child.id),
            "descriptor_key": descriptor_key,
            "model": model,
        },
        child.user_id,
        dedupe_key=f"{child.id}:{descriptor_key}:{model}",
    )
