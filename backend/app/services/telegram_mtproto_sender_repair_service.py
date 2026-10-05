"""Isolated MTProto repair for legacy inbound sender metadata.

This service is not a sync, reconcile, or production entrypoint. It only copies
the closed sender kind, and a fetched display when present, onto Objects that
still have no sender kind.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleConfigurationError
from app.connectors.telegram.constants import TELEGRAM_KIND, TELEGRAM_PROVIDER
from app.connectors.telegram.mtproto_account_store import TelegramMtprotoAccountStore
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAccountNotConnectedError,
    TelegramMtprotoConfigurationError,
)
from app.connectors.telegram.mtproto_transport import TelegramMtprotoTransport
from app.core.config import settings
from app.db.models import Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection
from app.domain.object_visibility import is_object_hidden_from_active_reads

SENDER_REPAIR_SCAN_LIMIT = 100
SENDER_REPAIR_MAX_LOOKUPS = 20
SENDER_REPAIR_MAX_PER_PEER = 5
_CLOSED_SENDER_KINDS = frozenset({"user", "bot", "channel", "chat"})


@dataclass(frozen=True)
class TelegramMtprotoSenderRepairSummary:
    candidates_scanned: int
    provider_calls: int
    updated: int
    provider_missing: int
    fetched_without_kind: int
    invalid_or_mismatch: int
    hidden_skipped: int
    next_cursor: UUID | None
    exhausted: bool


class TelegramMtprotoSenderRepairService:
    def __init__(
        self,
        session: Session,
        *,
        transport_factory: Callable[[], TelegramMtprotoTransport],
        encryption: CredentialEncryption | None = None,
    ) -> None:
        self._session = session
        self._transport_factory = transport_factory
        self._encryption = encryption

    async def repair_inbound_sender_metadata(
        self,
        user_id: UUID,
        account_id: UUID,
        *,
        cursor: UUID | None = None,
    ) -> TelegramMtprotoSenderRepairSummary:
        account = self._account(user_id, account_id)
        selections = {
            selection.peer_id: selection
            for selection in self._session.scalars(
                select(TelegramMtprotoChatSelection).where(
                    TelegramMtprotoChatSelection.account_id == account.id,
                    TelegramMtprotoChatSelection.scope_active.is_(True),
                )
            )
        }
        filters = [
            Object.user_id == user_id,
            Object.provider == TELEGRAM_PROVIDER,
            Object.kind == TELEGRAM_KIND,
            Object.deleted_at.is_(None),
            Object.metadata_["transport"].as_string() == "mtproto",
            Object.metadata_["account_id"].as_string() == str(account.id),
            Object.metadata_["direction"].as_string() == "inbound",
            Object.metadata_["sender_kind"].as_string().is_(None),
        ]
        if cursor is not None:
            filters.append(Object.id > cursor)
        rows = list(
            self._session.scalars(
                select(Object).where(*filters).order_by(Object.id).limit(SENDER_REPAIR_SCAN_LIMIT)
            )
        )

        scanned = 0
        provider_calls = 0
        updated = 0
        provider_missing = 0
        fetched_without_kind = 0
        invalid_or_mismatch = 0
        hidden_skipped = 0
        next_cursor = cursor
        peer_calls: dict[int, int] = {}
        transport: TelegramMtprotoTransport | None = None
        session_text: str | None = None
        references: dict[int, str] = {}

        for obj in rows:
            if is_object_hidden_from_active_reads(obj):
                hidden_skipped += 1
                scanned += 1
                next_cursor = obj.id
                continue

            peer_id, message_id = _repair_target(obj.metadata_ or {})
            selection = selections.get(peer_id) if peer_id is not None else None
            if message_id is None or selection is None:
                invalid_or_mismatch += 1
                scanned += 1
                next_cursor = obj.id
                continue

            if (
                provider_calls >= SENDER_REPAIR_MAX_LOOKUPS
                or peer_calls.get(peer_id, 0) >= SENDER_REPAIR_MAX_PER_PEER
            ):
                break

            if transport is None or session_text is None:
                store = self._store()
                session_text = store.decrypt_session(account)
                transport = self._transport_factory()
            reference = references.get(peer_id)
            if reference is None:
                reference = self._store().decrypt_reference(selection)
                references[peer_id] = reference

            result = await transport.fetch_message(
                session_text,
                reference,
                peer_id=peer_id,
                message_id=message_id,
            )
            provider_calls += 1
            peer_calls[peer_id] = peer_calls.get(peer_id, 0) + 1
            scanned += 1
            next_cursor = obj.id

            if result is None:
                provider_missing += 1
                continue
            if result.get("peer_id") != peer_id or result.get("message_id") != message_id:
                invalid_or_mismatch += 1
                continue

            kind = result.get("sender_kind")
            if kind not in _CLOSED_SENDER_KINDS:
                fetched_without_kind += 1
                continue

            _apply_sender_metadata(obj, kind, result.get("sender_display_name"))
            updated += 1

        exhausted = scanned == len(rows) and len(rows) < SENDER_REPAIR_SCAN_LIMIT
        return TelegramMtprotoSenderRepairSummary(
            candidates_scanned=scanned,
            provider_calls=provider_calls,
            updated=updated,
            provider_missing=provider_missing,
            fetched_without_kind=fetched_without_kind,
            invalid_or_mismatch=invalid_or_mismatch,
            hidden_skipped=hidden_skipped,
            next_cursor=next_cursor,
            exhausted=exhausted,
        )

    def _account(self, user_id: UUID, account_id: UUID) -> TelegramMtprotoAccount:
        account = TelegramMtprotoAccountStore(
            self._session, self._encryption_or_raise()
        ).get_by_id_for_user(account_id, user_id)
        if account is None:
            raise TelegramMtprotoAccountNotConnectedError(
                "Telegram MTProto account is not connected"
            )
        return account

    def _store(self) -> TelegramMtprotoAccountStore:
        return TelegramMtprotoAccountStore(self._session, self._encryption_or_raise())

    def _encryption_or_raise(self) -> CredentialEncryption:
        if self._encryption is not None:
            return self._encryption
        if not settings.secretary_credential_key.strip():
            raise TelegramMtprotoConfigurationError("Telegram MTProto is not configured")
        try:
            return CredentialEncryption(settings.secretary_credential_key)
        except GoogleConfigurationError as exc:
            raise TelegramMtprotoConfigurationError("Telegram MTProto is not configured") from exc


def _repair_target(metadata: dict) -> tuple[int | None, int | None]:
    return _json_int(metadata.get("peer_id")), _positive_int(metadata.get("message_id"))


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _json_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _apply_sender_metadata(obj: Object, kind: str, display: object) -> None:
    metadata = dict(obj.metadata_ or {})
    metadata["sender_kind"] = kind
    if isinstance(display, str) and display.strip():
        metadata["sender_display_name"] = display
    obj.metadata_ = metadata
