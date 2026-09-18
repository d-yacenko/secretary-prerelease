"""Account-level recurring Telegram MTProto scope and history synchronization."""

from uuid import UUID

from sqlalchemy import select

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAccountNotConnectedError,
    TelegramMtprotoGroupUnavailableError,
    TelegramMtprotoPeerNotInActiveScopeError,
    TelegramMtprotoProviderReferenceInvalidError,
)
from app.core.config import settings
from app.db.models import Job, Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection
from app.domain.telegram_mtproto_ai import telegram_mtproto_ai_predicate
from app.jobs.constants import JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_TYPE_EMBED_OBJECT
from app.llm.embedding_text import embedding_input_signature
from app.services.embedding_index import object_has_current_embedding_provenance
from app.services.pipeline_enqueue import enqueue_embed_object
from app.services.telegram_mtproto_history_service import TelegramMtprotoHistoryService
from app.services.telegram_mtproto_scope_service import TelegramMtprotoScopeService

TELEGRAM_MTPROTO_RECURRING_MAX_PEERS_PER_RUN = 10
TELEGRAM_MTPROTO_EMBED_CATCHUP_MAX_PER_RUN = 10
TELEGRAM_MTPROTO_EMBED_CATCHUP_SCAN_LIMIT = 100
TELEGRAM_MTPROTO_EMBED_CATCHUP_CURSOR_KEY = "telegram_embed_catchup_cursor"

_PEER_LOCAL_ERRORS = (
    TelegramMtprotoGroupUnavailableError,
    TelegramMtprotoProviderReferenceInvalidError,
    TelegramMtprotoPeerNotInActiveScopeError,
)


class TelegramMtprotoRecurringSyncService:
    def __init__(
        self,
        session,
        *,
        scope_service: TelegramMtprotoScopeService | None = None,
        history_service: TelegramMtprotoHistoryService | None = None,
    ) -> None:
        self._session = session
        if scope_service is None or history_service is None:
            encryption = CredentialEncryption(settings.secretary_credential_key)
            self._scope = scope_service or TelegramMtprotoScopeService(
                session, encryption=encryption
            )
            self._history = history_service or TelegramMtprotoHistoryService(
                session, encryption=encryption
            )
        else:
            self._scope = scope_service
            self._history = history_service

    async def run(self, user_id: UUID, account_id: UUID, payload: dict) -> None:
        account = self._session.scalar(
            select(TelegramMtprotoAccount).where(
                TelegramMtprotoAccount.id == account_id,
                TelegramMtprotoAccount.user_id == user_id,
            )
        )
        if account is None:
            raise TelegramMtprotoAccountNotConnectedError(
                "Telegram MTProto account is not connected"
            )

        await self._scope.reconcile_scope(user_id)
        self._enqueue_embedding_catchup(user_id, account_id, payload)
        selections = list(
            self._session.scalars(
                select(TelegramMtprotoChatSelection)
                .where(
                    TelegramMtprotoChatSelection.account_id == account_id,
                    TelegramMtprotoChatSelection.scope_active.is_(True),
                )
                .order_by(TelegramMtprotoChatSelection.peer_id)
            )
        )
        if not selections:
            payload["telegram_peer_cursor"] = 0
            return

        cursor = payload.get("telegram_peer_cursor", 0)
        try:
            cursor = int(cursor)
        except (TypeError, ValueError):
            cursor = 0
        cursor %= len(selections)
        ordered = selections[cursor:] + selections[:cursor]
        for offset, selection in enumerate(ordered[:TELEGRAM_MTPROTO_RECURRING_MAX_PEERS_PER_RUN]):
            try:
                await self._history.sync_scope_peer(user_id, selection.peer_id)
            except _PEER_LOCAL_ERRORS:
                pass
            payload["telegram_peer_cursor"] = (cursor + offset + 1) % len(selections)

    def _enqueue_embedding_catchup(
        self, user_id: UUID, account_id: UUID, payload: dict | None = None
    ) -> int:
        if not settings.telegram_mtproto_ai_enabled:
            return 0
        catchup_payload = payload if payload is not None else {}
        cursor_raw = catchup_payload.get(TELEGRAM_MTPROTO_EMBED_CATCHUP_CURSOR_KEY)
        try:
            cursor = UUID(str(cursor_raw)) if cursor_raw else None
        except (TypeError, ValueError):
            cursor = None
        filters = [
            Object.user_id == user_id,
            Object.provider == "telegram",
            Object.kind == "chat_message",
            Object.metadata_["transport"].as_string() == "mtproto",
            Object.metadata_["account_id"].as_string() == str(account_id),
            telegram_mtproto_ai_predicate(),
        ]
        if cursor is not None:
            filters.append(Object.id > cursor)
        objects = list(
            self._session.scalars(
                select(Object)
                .where(*filters)
                .order_by(Object.id)
                .limit(TELEGRAM_MTPROTO_EMBED_CATCHUP_SCAN_LIMIT)
            )
        )
        if not objects and cursor is not None:
            objects = list(
                self._session.scalars(
                    select(Object)
                    .where(
                        Object.user_id == user_id,
                        Object.provider == "telegram",
                        Object.kind == "chat_message",
                        Object.metadata_["transport"].as_string() == "mtproto",
                        Object.metadata_["account_id"].as_string() == str(account_id),
                        telegram_mtproto_ai_predicate(),
                    )
                    .order_by(Object.id)
                    .limit(TELEGRAM_MTPROTO_EMBED_CATCHUP_SCAN_LIMIT)
                )
        )
        queued = 0
        for obj in objects:
            if catchup_payload is not None:
                catchup_payload[TELEGRAM_MTPROTO_EMBED_CATCHUP_CURSOR_KEY] = str(obj.id)
            if object_has_current_embedding_provenance(
                obj, embedding_input_signature(obj)
            ):
                continue
            current_signature = embedding_input_signature(obj)
            before = self._session.scalar(
                select(Job.id).where(
                    Job.user_id == user_id,
                    Job.type == JOB_TYPE_EMBED_OBJECT,
                    Job.status.in_((JOB_STATUS_PENDING, JOB_STATUS_RUNNING)),
                    Job.payload["object_id"].as_string() == str(obj.id),
                    Job.payload["embedding_input_signature"].as_string()
                    == current_signature,
                )
            )
            if before is not None:
                continue
            enqueue_embed_object(self._session, obj.id, user_id)
            after = self._session.scalar(
                select(Job.id).where(
                    Job.user_id == user_id,
                    Job.type == JOB_TYPE_EMBED_OBJECT,
                    Job.status.in_((JOB_STATUS_PENDING, JOB_STATUS_RUNNING)),
                    Job.payload["object_id"].as_string() == str(obj.id),
                    Job.payload["embedding_input_signature"].as_string()
                    == current_signature,
                )
            )
            if after is not None:
                queued += 1
                if queued >= TELEGRAM_MTPROTO_EMBED_CATCHUP_MAX_PER_RUN:
                    break
        return queued
