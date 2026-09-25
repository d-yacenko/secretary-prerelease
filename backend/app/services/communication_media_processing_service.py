"""Transcribe an existing voice/audio media child through the shared provider stack."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.transcription_constants import MAX_TRANSCRIPTION_AUDIO_BYTES
from app.connectors.telegram.mtproto_errors import TelegramMtprotoProviderUnavailableError
from app.core.config import settings
from app.db.models import Object, Representation
from app.domain.communication_media import parse_stored_descriptor
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.domain.telegram_mtproto_ai import telegram_mtproto_ai_eligible
from app.services.communication_media_jobs import TRANSCRIBABLE_MEDIA_KINDS
from app.services.effective_user_settings_service import EffectiveUserSettingsService
from app.services.openai_daily_budget import OpenAIDailyBudgetGuard
from app.services.provenance import REJECTED_STATE
from app.services.transcription_service import (
    create_transcription_provider_for_api_key,
    transcribe_audio_bytes,
)

TRANSCRIPT_KIND = "transcript"
MAX_TRANSCRIPT_CHARS = 20_000


class MediaProcessingPermanentError(Exception):
    """Policy or descriptor mismatch that must not be retried."""


@dataclass(frozen=True)
class MediaProcessingResult:
    status: str
    representation_id: UUID | None = None


class CommunicationMediaProcessingService:
    def __init__(self, session: Session, user_id: UUID, *, fetcher=None, provider=None) -> None:
        self._session = session
        self._user_id = user_id
        self._fetcher = fetcher
        self._provider = provider

    def process(self, media_object_id: UUID) -> MediaProcessingResult:
        child = self._session.get(Object, media_object_id)
        if child is None or child.user_id != self._user_id:
            raise MediaProcessingPermanentError("communication media was not found")
        if child.kind != "file":
            raise MediaProcessingPermanentError("communication media is not a file")
        if child.state == REJECTED_STATE or is_object_hidden_from_active_reads(child):
            return MediaProcessingResult(status="skipped")
        parent, descriptor = self._validated_parent(child)
        if parent is None:
            return MediaProcessingResult(status="skipped")
        audio = self._fetch(parent, child)
        if not audio:
            raise MediaProcessingPermanentError("communication media is empty")
        if len(audio) > MAX_TRANSCRIPTION_AUDIO_BYTES:
            raise MediaProcessingPermanentError("communication media exceeds size limit")
        digest = hashlib.sha256(audio).hexdigest()
        model = self._model_name()
        existing = self._transcript(child.id)
        stored = (existing.metadata_ or {}) if existing is not None else {}
        if stored.get("content_hash") == digest and stored.get("model") == model:
            return MediaProcessingResult(status="unchanged", representation_id=existing.id)
        filename = descriptor.filename or f"{descriptor.media_kind}.ogg"
        text = transcribe_audio_bytes(
            audio,
            filename,
            descriptor.mime_type,
            self._provider_or_default(),
        )
        provenance = {
            "model": model,
            "content_hash": digest,
            "source": "communication_media",
        }
        row = self._store_transcript(child, existing, text[:MAX_TRANSCRIPT_CHARS], provenance)
        metadata = dict(child.metadata_ or {})
        metadata["content_hash"] = digest
        metadata["transcript_model"] = model
        metadata["transcribed_at"] = datetime.now(UTC).isoformat()
        child.metadata_ = metadata
        self._session.flush()
        return MediaProcessingResult(status="transcribed", representation_id=row.id)

    def _validated_parent(self, child: Object):
        metadata = child.metadata_ or {}
        descriptor = parse_stored_descriptor(
            child.provider or "",
            {
                "descriptor_key": metadata.get("descriptor_key"),
                "media_kind": metadata.get("media_kind"),
                "provider_media_id": metadata.get("provider_media_id"),
                "filename": metadata.get("filename"),
                "mime_type": metadata.get("mime_type"),
                "size": metadata.get("size"),
                "duration_seconds": metadata.get("duration_seconds"),
                "provenance": metadata.get("provenance"),
            },
        )
        if descriptor is None or descriptor.media_kind not in TRANSCRIBABLE_MEDIA_KINDS:
            raise MediaProcessingPermanentError("communication media is not transcribable")
        if child.provider != "telegram":
            raise MediaProcessingPermanentError("communication media provider is not supported")
        try:
            parent_uuid = UUID(str(metadata.get("parent_communication_id")))
        except (TypeError, ValueError) as exc:
            raise MediaProcessingPermanentError("communication media parent is missing") from exc
        parent = self._session.get(Object, parent_uuid)
        if parent is None or parent.user_id != self._user_id:
            raise MediaProcessingPermanentError("communication media parent was not found")
        if parent.state == REJECTED_STATE or is_object_hidden_from_active_reads(parent):
            return None, descriptor
        if not telegram_mtproto_ai_eligible(self._session, parent):
            return None, descriptor
        return parent, descriptor

    def _fetch(self, parent: Object, child: Object) -> bytes:
        fetcher = self._fetcher or _default_fetcher(self._session, self._user_id)
        try:
            audio = fetcher.fetch(parent, child)
        except MediaProcessingPermanentError:
            raise
        except TelegramMtprotoProviderUnavailableError:
            raise
        except Exception as exc:
            raise MediaProcessingPermanentError("communication media fetch failed") from exc
        if not isinstance(audio, bytes):
            raise MediaProcessingPermanentError("communication media fetch failed")
        return audio

    def _provider_or_default(self):
        if self._provider is not None:
            return self._provider
        api_key = EffectiveUserSettingsService.build(self._session).resolve_openai_api_key(
            self._user_id
        )
        provider = create_transcription_provider_for_api_key(api_key)
        return OpenAIDailyBudgetGuard.build(
            self._session, self._user_id
        ).guard_transcription_provider(provider)

    def _model_name(self) -> str:
        model = getattr(self._provider_or_default(), "model", None)
        if isinstance(model, str) and model.strip():
            return model.strip()
        configured = settings.openai_transcription_model.strip()
        return configured or "unknown"

    def _transcript(self, object_id: UUID) -> Representation | None:
        return self._session.scalar(
            select(Representation)
            .where(Representation.object_id == object_id, Representation.kind == TRANSCRIPT_KIND)
            .order_by(Representation.created_at, Representation.id)
            .limit(1)
        )

    def _store_transcript(
        self,
        child: Object,
        existing: Representation | None,
        text: str,
        provenance: dict,
    ) -> Representation:
        if existing is None:
            row = Representation(
                object_id=child.id,
                kind=TRANSCRIPT_KIND,
                part_index=0,
                text=text,
                metadata_=provenance,
            )
            self._session.add(row)
            self._session.flush()
            return row
        existing.text = text
        existing.metadata_ = provenance
        self._session.flush()
        return existing


def _default_fetcher(session: Session, user_id: UUID):
    from app.connectors.telegram.media_fetch import TelegramCommunicationMediaFetcher

    return TelegramCommunicationMediaFetcher(session, user_id)
