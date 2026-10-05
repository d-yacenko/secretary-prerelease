"""Isolated Teams repair for a missing inbound sender kind.

The caller supplies a ready transport. This service does not acquire tokens,
run sync, or rewrite message content.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.teams.constants import MESSAGE_TYPE_MESSAGE, TEAMS_KIND, TEAMS_PROVIDER
from app.connectors.teams.errors import TeamsConnectorError
from app.connectors.teams.id_token import try_canonical_microsoft_guid
from app.connectors.teams.normalize import (
    build_external_id,
    provider_id_str,
    sender_identity_from_message,
)
from app.connectors.teams.transport import TeamsTransport
from app.db.models import Object, TeamsAccount
from app.domain.object_visibility import is_object_hidden_from_active_reads

SENDER_KIND_REPAIR_SCAN_LIMIT = 100
SENDER_KIND_REPAIR_MAX_LOOKUPS = 20
SENDER_KIND_REPAIR_MAX_PER_CHAT = 5
_CLOSED_KINDS = frozenset({"user", "application"})


@dataclass(frozen=True)
class TeamsSenderKindRepairSummary:
    candidates_scanned: int
    provider_calls: int
    updated: int
    fetched_without_kind: int
    identity_mismatch: int
    invalid_provenance: int
    hidden_skipped: int
    next_cursor: UUID | None
    exhausted: bool


class TeamsSenderKindRepairService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def repair_sender_kind(
        self,
        user_id: UUID,
        account_id: UUID,
        transport: TeamsTransport,
        *,
        cursor: UUID | None = None,
    ) -> TeamsSenderKindRepairSummary:
        account = self._session.scalar(
            select(TeamsAccount).where(
                TeamsAccount.id == account_id,
                TeamsAccount.user_id == user_id,
            )
        )
        if account is None:
            raise TeamsConnectorError("teams account not found")

        filters = [
            Object.user_id == user_id,
            Object.provider == TEAMS_PROVIDER,
            Object.kind == TEAMS_KIND,
            Object.deleted_at.is_(None),
            Object.metadata_["account_id"].as_string() == str(account.id),
            Object.metadata_["tenant_id"].as_string() == account.tenant_id,
            Object.metadata_["teams_user_id"].as_string() == account.microsoft_user_id,
            Object.metadata_["direction"].as_string() == "inbound",
            Object.metadata_["sender_kind"].as_string().is_(None),
        ]
        if cursor is not None:
            filters.append(Object.id > cursor)
        rows = list(
            self._session.scalars(
                select(Object)
                .where(*filters)
                .order_by(Object.id)
                .limit(SENDER_KIND_REPAIR_SCAN_LIMIT)
            )
        )

        scanned = 0
        provider_calls = 0
        updated = 0
        fetched_without_kind = 0
        identity_mismatch = 0
        invalid_provenance = 0
        hidden_skipped = 0
        next_cursor = cursor
        chat_calls: dict[str, int] = {}
        stopped_early = False

        for obj in rows:
            if is_object_hidden_from_active_reads(obj):
                hidden_skipped += 1
                scanned += 1
                next_cursor = obj.id
                continue

            target = _repair_target(account, obj)
            if target is None:
                invalid_provenance += 1
                scanned += 1
                next_cursor = obj.id
                continue

            chat_id, message_id, sender_id = target
            if (
                provider_calls >= SENDER_KIND_REPAIR_MAX_LOOKUPS
                or chat_calls.get(chat_id, 0) >= SENDER_KIND_REPAIR_MAX_PER_CHAT
            ):
                stopped_early = True
                break

            payload = transport.get_chat_message(chat_id, message_id)
            provider_calls += 1
            chat_calls[chat_id] = chat_calls.get(chat_id, 0) + 1
            scanned += 1
            next_cursor = obj.id

            if not isinstance(payload, dict):
                identity_mismatch += 1
                continue
            if _message_rejected(payload, chat_id, message_id):
                identity_mismatch += 1
                continue

            fetched_id, _fetched_display, kind = sender_identity_from_message(payload)
            if kind not in _CLOSED_KINDS:
                fetched_without_kind += 1
                continue
            if not _same_sender(sender_id, fetched_id):
                identity_mismatch += 1
                continue

            metadata = dict(obj.metadata_ or {})
            metadata["sender_kind"] = kind
            obj.metadata_ = metadata
            updated += 1

        exhausted = (
            not stopped_early
            and scanned == len(rows)
            and len(rows) < SENDER_KIND_REPAIR_SCAN_LIMIT
        )
        return TeamsSenderKindRepairSummary(
            candidates_scanned=scanned,
            provider_calls=provider_calls,
            updated=updated,
            fetched_without_kind=fetched_without_kind,
            identity_mismatch=identity_mismatch,
            invalid_provenance=invalid_provenance,
            hidden_skipped=hidden_skipped,
            next_cursor=next_cursor,
            exhausted=exhausted,
        )


def _repair_target(account: TeamsAccount, obj: Object) -> tuple[str, str, str] | None:
    metadata = obj.metadata_ or {}
    chat_id = _text(metadata.get("chat_id"))
    message_id = _text(metadata.get("message_id"))
    sender_id = _text(metadata.get("sender_id"))
    display = _text(metadata.get("sender_display_name"))
    if chat_id is None or message_id is None or sender_id is None or display is None:
        return None
    expected = build_external_id(
        account.tenant_id,
        account.microsoft_user_id,
        chat_id,
        message_id,
    )
    if obj.external_id != expected:
        return None
    return chat_id, message_id, sender_id


def _message_rejected(payload: dict, chat_id: str, message_id: str) -> bool:
    if provider_id_str(payload.get("id")) != message_id:
        return True
    returned_chat = provider_id_str(payload.get("chatId"))
    if returned_chat is not None and returned_chat != chat_id:
        return True
    if payload.get("deletedDateTime"):
        return True
    message_type = payload.get("messageType")
    if message_type is not None:
        explicit = str(message_type).strip()
        if explicit and explicit != MESSAGE_TYPE_MESSAGE:
            return True
    return False


def _same_sender(stored_sender_id: str, fetched_sender_id: str | None) -> bool:
    if not fetched_sender_id:
        return False
    return try_canonical_microsoft_guid(stored_sender_id) == try_canonical_microsoft_guid(
        fetched_sender_id
    )


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
