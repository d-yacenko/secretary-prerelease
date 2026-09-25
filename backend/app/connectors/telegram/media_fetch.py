"""Fetch Telegram voice/audio bytes for an already stored media descriptor."""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.transcription_constants import MAX_TRANSCRIPTION_AUDIO_BYTES
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_account_store import TelegramMtprotoAccountStore
from app.connectors.telegram.mtproto_transport import TelethonMtprotoTransport
from app.core.config import settings
from app.db.models import Object, TelegramMtprotoChatSelection
from app.services.communication_media_processing_service import MediaProcessingPermanentError


class TelegramCommunicationMediaFetcher:
    def __init__(self, session: Session, user_id: UUID, *, transport=None) -> None:
        self._session = session
        self._user_id = user_id
        self._transport = transport

    def fetch(self, parent: Object, child: Object) -> bytes:
        del parent
        return asyncio.run(self._download(child))

    async def _download(self, child: Object) -> bytes:
        metadata = child.metadata_ or {}
        provenance = metadata.get("provenance") if isinstance(metadata.get("provenance"), dict) else {}
        try:
            account_id = UUID(str(provenance.get("account_id")))
            peer_id = int(str(provenance.get("peer_id")))
            message_id = int(str(provenance.get("message_id")))
        except (TypeError, ValueError) as exc:
            raise MediaProcessingPermanentError("communication media provenance is incomplete") from exc
        media_kind = str(metadata.get("media_kind") or "")
        provider_media_id = str(metadata.get("provider_media_id") or "")
        category = provenance.get("media_category")
        if category not in (None, "", media_kind) or media_kind not in {"voice", "audio"}:
            raise MediaProcessingPermanentError("communication media is not transcribable")
        store = TelegramMtprotoAccountStore(self._session, _encryption())
        account = store.get_by_id_for_user(account_id, self._user_id)
        selection = self._session.scalar(
            select(TelegramMtprotoChatSelection).where(
                TelegramMtprotoChatSelection.account_id == account_id,
                TelegramMtprotoChatSelection.peer_id == peer_id,
            )
        )
        if account is None or selection is None:
            raise MediaProcessingPermanentError("communication media account was not found")
        try:
            session_text = store.decrypt_session(account)
            reference = store.decrypt_reference(selection)
        except Exception as exc:
            raise MediaProcessingPermanentError("communication media account was not found") from exc
        transport = self._transport or TelethonMtprotoTransport(
            settings.telegram_api_id,
            settings.telegram_api_hash.strip(),
        )
        return await transport.download_voice_audio(
            session_text,
            reference,
            peer_id=peer_id,
            message_id=message_id,
            provider_media_id=provider_media_id,
            media_kind=media_kind,
            max_bytes=MAX_TRANSCRIPTION_AUDIO_BYTES + 1,
        )


def _encryption() -> CredentialEncryption:
    if not settings.secretary_credential_key.strip():
        raise MediaProcessingPermanentError("communication media account was not found")
    try:
        return CredentialEncryption(settings.secretary_credential_key)
    except Exception as exc:
        raise MediaProcessingPermanentError("communication media account was not found") from exc
