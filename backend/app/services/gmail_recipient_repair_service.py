"""Isolated Gmail repair for missing named To and Cc participants.

The caller supplies a ready transport and access token. This service does not
refresh credentials, run sync, or rewrite stored message content.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.google.errors import GoogleApiError, GoogleConnectorError
from app.connectors.google.gmail_normalize import gmail_structured_recipients
from app.connectors.google.gmail_transport import GmailTransport
from app.db.models import GoogleAccount, Object
from app.domain.object_visibility import is_object_hidden_from_active_reads

RECIPIENT_REPAIR_SCAN_LIMIT = 100
RECIPIENT_REPAIR_MAX_LOOKUPS = 20
_GMAIL_PROVIDER = "gmail"
_EMAIL_KIND = "email"
_GMAIL_USER = "me"


@dataclass(frozen=True)
class GmailRecipientRepairSummary:
    candidates_scanned: int
    provider_calls: int
    updated: int
    already_structured: int
    invalid_provenance: int
    provider_missing: int
    message_mismatch: int
    no_named_recipients: int
    hidden_skipped: int
    next_cursor: UUID | None
    exhausted: bool


class GmailRecipientRepairService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def repair_named_recipients(
        self,
        user_id: UUID,
        account_id: UUID,
        transport: GmailTransport,
        access_token: str,
        *,
        cursor: UUID | None = None,
    ) -> GmailRecipientRepairSummary:
        account = self._session.scalar(
            select(GoogleAccount).where(
                GoogleAccount.id == account_id,
                GoogleAccount.user_id == user_id,
            )
        )
        if account is None:
            raise GoogleConnectorError("gmail account not found")

        filters = [
            Object.user_id == user_id,
            Object.provider == _GMAIL_PROVIDER,
            Object.kind == _EMAIL_KIND,
            Object.deleted_at.is_(None),
            Object.metadata_["source_account_email"].as_string() == account.email,
        ]
        if cursor is not None:
            filters.append(Object.id > cursor)
        rows = list(
            self._session.scalars(
                select(Object)
                .where(*filters)
                .order_by(Object.id)
                .limit(RECIPIENT_REPAIR_SCAN_LIMIT)
            )
        )

        scanned = 0
        provider_calls = 0
        updated = 0
        already_structured = 0
        invalid_provenance = 0
        provider_missing = 0
        message_mismatch = 0
        no_named_recipients = 0
        hidden_skipped = 0
        next_cursor = cursor
        stopped_early = False

        for obj in rows:
            if is_object_hidden_from_active_reads(obj):
                hidden_skipped += 1
                scanned += 1
                next_cursor = obj.id
                continue

            message_id = _message_id(obj)
            if message_id is None:
                invalid_provenance += 1
                scanned += 1
                next_cursor = obj.id
                continue

            metadata = obj.metadata_ or {}
            if "to_participants" in metadata and "cc_participants" in metadata:
                already_structured += 1
                scanned += 1
                next_cursor = obj.id
                continue

            if provider_calls >= RECIPIENT_REPAIR_MAX_LOOKUPS:
                stopped_early = True
                break

            try:
                payload = transport.get_message(access_token, _GMAIL_USER, message_id)
            except GoogleApiError as exc:
                if exc.status_code != 404:
                    raise
                provider_calls += 1
                provider_missing += 1
                scanned += 1
                next_cursor = obj.id
                continue

            provider_calls += 1
            scanned += 1
            next_cursor = obj.id
            if not isinstance(payload, dict) or payload.get("id") != message_id:
                message_mismatch += 1
                continue

            to_named, cc_named = gmail_structured_recipients(payload)
            if not _apply_missing_participants(obj, to_named, cc_named):
                no_named_recipients += 1
                continue
            updated += 1

        exhausted = (
            not stopped_early
            and scanned == len(rows)
            and len(rows) < RECIPIENT_REPAIR_SCAN_LIMIT
        )
        return GmailRecipientRepairSummary(
            candidates_scanned=scanned,
            provider_calls=provider_calls,
            updated=updated,
            already_structured=already_structured,
            invalid_provenance=invalid_provenance,
            provider_missing=provider_missing,
            message_mismatch=message_mismatch,
            no_named_recipients=no_named_recipients,
            hidden_skipped=hidden_skipped,
            next_cursor=next_cursor,
            exhausted=exhausted,
        )


def _apply_missing_participants(
    obj: Object,
    to_named: list[dict[str, str]],
    cc_named: list[dict[str, str]],
) -> bool:
    metadata = dict(obj.metadata_ or {})
    changed = False
    if "to_participants" not in metadata and to_named:
        metadata["to_participants"] = to_named
        changed = True
    if "cc_participants" not in metadata and cc_named:
        metadata["cc_participants"] = cc_named
        changed = True
    if not changed:
        return False
    obj.metadata_ = metadata
    return True


def _message_id(obj: Object) -> str | None:
    metadata = obj.metadata_ or {}
    message_id = metadata.get("message_id")
    external_id = obj.external_id
    if not isinstance(message_id, str) or not message_id.strip():
        return None
    if not isinstance(external_id, str) or not external_id.strip():
        return None
    if external_id != message_id:
        return None
    return message_id
