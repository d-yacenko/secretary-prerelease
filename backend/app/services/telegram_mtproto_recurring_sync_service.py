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
from app.db.models import TelegramMtprotoAccount, TelegramMtprotoChatSelection
from app.services.telegram_mtproto_history_service import TelegramMtprotoHistoryService
from app.services.telegram_mtproto_scope_service import TelegramMtprotoScopeService

TELEGRAM_MTPROTO_RECURRING_MAX_PEERS_PER_RUN = 10

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
