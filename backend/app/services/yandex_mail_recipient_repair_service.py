"""Isolated Yandex Mail repair for missing named To and Cc participants.

The caller supplies a ready IMAP transport. This service does not load
credentials, run sync, or rewrite stored message content.
"""

from __future__ import annotations

from dataclasses import dataclass
from email import message_from_bytes, policy
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.connectors.yandex.constants import DEFAULT_MAIL_FOLDER
from app.connectors.yandex.errors import YandexConnectorError, YandexImapError
from app.connectors.yandex.imap_transport import ImapTransport
from app.connectors.yandex.mail_normalize import build_external_id, yandex_structured_recipients
from app.db.models import Object, YandexMailAccount
from app.domain.object_visibility import is_object_hidden_from_active_reads

RECIPIENT_REPAIR_SCAN_LIMIT = 100
RECIPIENT_REPAIR_MAX_FETCHES = 20
_YANDEX_PROVIDER = "yandex_mail"
_EMAIL_KIND = "email"


@dataclass(frozen=True)
class YandexRecipientRepairSummary:
    candidates_scanned: int
    folder_select_calls: int
    message_fetches: int
    updated: int
    invalid_provenance: int
    uidvalidity_mismatch: int
    message_malformed: int
    no_named_recipients: int
    hidden_skipped: int
    current_uidvalidity: int | None
    next_cursor: UUID | None
    exhausted: bool


class YandexMailRecipientRepairService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def repair_named_recipients(
        self,
        user_id: UUID,
        account_id: UUID,
        transport: ImapTransport,
        *,
        cursor: UUID | None = None,
    ) -> YandexRecipientRepairSummary:
        account = self._session.scalar(
            select(YandexMailAccount).where(
                YandexMailAccount.id == account_id,
                YandexMailAccount.user_id == user_id,
            )
        )
        if account is None:
            raise YandexConnectorError("yandex mail account not found")

        filters = [
            Object.user_id == user_id,
            Object.provider == _YANDEX_PROVIDER,
            Object.kind == _EMAIL_KIND,
            Object.deleted_at.is_(None),
            Object.metadata_["source_account_email"].as_string() == account.email,
            Object.metadata_["folder"].as_string() == DEFAULT_MAIL_FOLDER,
            or_(
                Object.metadata_["to_participants"].as_string().is_(None),
                Object.metadata_["cc_participants"].as_string().is_(None),
            ),
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
        if not rows:
            return _summary(cursor=cursor, exhausted=True)

        current_uidvalidity = transport.select_folder(DEFAULT_MAIL_FOLDER)
        if not _positive_int(current_uidvalidity):
            raise YandexImapError("UIDVALIDITY response malformed")

        scanned = 0
        message_fetches = 0
        updated = 0
        invalid_provenance = 0
        uidvalidity_mismatch = 0
        message_malformed = 0
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

            target = _fetch_target(obj, current_uidvalidity)
            if target is None:
                invalid_provenance += 1
                scanned += 1
                next_cursor = obj.id
                continue
            if target == "uidvalidity":
                uidvalidity_mismatch += 1
                scanned += 1
                next_cursor = obj.id
                continue

            if message_fetches >= RECIPIENT_REPAIR_MAX_FETCHES:
                stopped_early = True
                break

            raw = transport.fetch_message(DEFAULT_MAIL_FOLDER, target)
            message_fetches += 1
            scanned += 1
            next_cursor = obj.id
            if not isinstance(raw, bytes) or not raw:
                message_malformed += 1
                continue

            parsed = message_from_bytes(raw, policy=policy.default)
            to_named, cc_named = yandex_structured_recipients(parsed)
            if not _apply_missing_participants(obj, to_named, cc_named):
                no_named_recipients += 1
                continue
            updated += 1

        exhausted = (
            not stopped_early
            and scanned == len(rows)
            and len(rows) < RECIPIENT_REPAIR_SCAN_LIMIT
        )
        return _summary(
            scanned=scanned,
            folder_select_calls=1,
            message_fetches=message_fetches,
            updated=updated,
            invalid_provenance=invalid_provenance,
            uidvalidity_mismatch=uidvalidity_mismatch,
            message_malformed=message_malformed,
            no_named_recipients=no_named_recipients,
            hidden_skipped=hidden_skipped,
            current_uidvalidity=current_uidvalidity,
            cursor=next_cursor,
            exhausted=exhausted,
        )


def _summary(
    *,
    scanned: int = 0,
    folder_select_calls: int = 0,
    message_fetches: int = 0,
    updated: int = 0,
    invalid_provenance: int = 0,
    uidvalidity_mismatch: int = 0,
    message_malformed: int = 0,
    no_named_recipients: int = 0,
    hidden_skipped: int = 0,
    current_uidvalidity: int | None = None,
    cursor: UUID | None = None,
    exhausted: bool = False,
) -> YandexRecipientRepairSummary:
    return YandexRecipientRepairSummary(
        candidates_scanned=scanned,
        folder_select_calls=folder_select_calls,
        message_fetches=message_fetches,
        updated=updated,
        invalid_provenance=invalid_provenance,
        uidvalidity_mismatch=uidvalidity_mismatch,
        message_malformed=message_malformed,
        no_named_recipients=no_named_recipients,
        hidden_skipped=hidden_skipped,
        current_uidvalidity=current_uidvalidity,
        next_cursor=cursor,
        exhausted=exhausted,
    )


def _fetch_target(obj: Object, current_uidvalidity: int) -> int | str | None:
    metadata = obj.metadata_ or {}
    uid = _positive_int(metadata.get("imap_uid"))
    stored_uidvalidity = _positive_int(metadata.get("imap_uidvalidity"))
    if uid is None or stored_uidvalidity is None:
        return None
    if stored_uidvalidity != current_uidvalidity:
        return "uidvalidity"
    expected = build_external_id(DEFAULT_MAIL_FOLDER, current_uidvalidity, uid)
    if obj.external_id != expected:
        return None
    return uid


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


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value
