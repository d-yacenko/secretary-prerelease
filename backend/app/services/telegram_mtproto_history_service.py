from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleConfigurationError
from app.connectors.telegram.constants import (
    MAX_TELEGRAM_MESSAGE_BODY_CHARS,
    TELEGRAM_KIND,
    TELEGRAM_ORIGIN,
    TELEGRAM_PROVIDER,
    TELEGRAM_STATE,
)
from app.connectors.telegram.materialize import (
    TelegramMaterializeResult,
    TelegramObjectMaterializer,
)
from app.connectors.telegram.mtproto_account_store import TelegramMtprotoAccountStore
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAccountNotConnectedError,
    TelegramMtprotoAuthorizationInvalidError,
    TelegramMtprotoConfigurationError,
    TelegramMtprotoGroupNotSelectedError,
    TelegramMtprotoPeerNotInActiveScopeError,
    TelegramMtprotoProviderReferenceInvalidError,
    TelegramMtprotoProviderUnavailableError,
    TelegramMtprotoReadRejectedError,
    TelegramMtprotoWriteDefiniteError,
)
from app.connectors.telegram.mtproto_transport import (
    TELEGRAM_MTPROTO_HISTORY_PAGE_SIZE,
    TelegramMtprotoHistoryEntry,
    TelegramMtprotoHistoryPage,
    TelegramMtprotoTransport,
    TelethonMtprotoTransport,
)
from app.core.config import settings
from app.db.models import Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection
from app.domain.object_visibility import tombstone_object
from app.services.telegram_mtproto_notification_service import (
    TelegramMtprotoNotificationPersistenceError,
    TelegramMtprotoTransportNotificationService,
)

TELEGRAM_MTPROTO_HISTORY_DAYS = 14
TELEGRAM_MTPROTO_HISTORY_MAX_MESSAGES_PER_RUN = 200
TELEGRAM_MTPROTO_RECONCILE_MAX_LOOKUPS = 20
TELEGRAM_MTPROTO_RECONCILE_MAX_PER_PEER = 5
TELEGRAM_MTPROTO_RECONCILE_SCAN_LIMIT = 100
TELEGRAM_MTPROTO_RECONCILE_HEAD_WINDOW = 5
TELEGRAM_MTPROTO_RECONCILE_CURSORS_KEY = "telegram_reconcile_peer_cursors"
TELEGRAM_MTPROTO_RECONCILE_HEAD_KEY = "telegram_reconcile_peer_heads"
TELEGRAM_MTPROTO_RECONCILE_MODES_KEY = "telegram_reconcile_peer_modes"
TELEGRAM_MTPROTO_RECONCILE_ROTATION_KEY = "telegram_reconcile_peer_rotation"


@dataclass(frozen=True)
class TelegramMtprotoHistorySummary:
    peer_id: int
    scanned: int
    materialized: int
    created: int
    updated: int
    unchanged: int
    skipped: int
    jobs_enqueued: int
    history_complete: bool


@dataclass
class _ImportStats:
    scanned: int = 0
    materialized: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    jobs_enqueued: int = 0

    def add(self, result: TelegramMaterializeResult) -> None:
        self.materialized += 1
        if result.change == "created":
            self.created += 1
        elif result.change == "unchanged":
            self.unchanged += 1
        else:
            self.updated += 1
        self.jobs_enqueued += result.jobs_enqueued


class TelegramMtprotoHistoryService:
    def __init__(
        self,
        session,
        *,
        transport_factory: Callable[[], TelegramMtprotoTransport] | None = None,
        encryption: CredentialEncryption | None = None,
    ) -> None:
        self._session = session
        self._transport_factory = transport_factory or _build_transport
        self._encryption = encryption

    async def sync_group(self, user_id: UUID, peer_id: int) -> TelegramMtprotoHistorySummary:
        store = self._store()
        account = store.get_by_user_id(user_id)
        if account is None:
            raise TelegramMtprotoAccountNotConnectedError(
                "Telegram MTProto account is not connected"
            )
        selection = store.get_selection(account.id, peer_id)
        if selection is None or not selection.manual_selected:
            raise TelegramMtprotoGroupNotSelectedError("Telegram group is not selected")
        return await self._sync_selection(account, selection)

    async def sync_scope_peer(self, user_id: UUID, peer_id: int) -> TelegramMtprotoHistorySummary:
        store = self._store()
        account = store.get_by_user_id(user_id)
        if account is None:
            raise TelegramMtprotoAccountNotConnectedError(
                "Telegram MTProto account is not connected"
            )
        selection = store.get_selection(account.id, peer_id)
        if selection is None or not selection.scope_active:
            raise TelegramMtprotoPeerNotInActiveScopeError(
                "Telegram peer is not in active Telegram sync scope"
            )
        return await self._sync_selection(account, selection)

    async def reconcile_recent_messages(self, user_id: UUID, account_id: UUID, payload: dict) -> int:
        """Reconcile bounded known messages through the canonical A3 materializer."""
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
        selections = {
            selection.peer_id: selection
            for selection in self._session.scalars(
                select(TelegramMtprotoChatSelection).where(
                    TelegramMtprotoChatSelection.account_id == account_id,
                    TelegramMtprotoChatSelection.scope_active.is_(True),
                )
            )
        }
        if not selections:
            payload[TELEGRAM_MTPROTO_RECONCILE_CURSORS_KEY] = {}
            payload[TELEGRAM_MTPROTO_RECONCILE_HEAD_KEY] = {}
            payload[TELEGRAM_MTPROTO_RECONCILE_MODES_KEY] = {}
            payload[TELEGRAM_MTPROTO_RECONCILE_ROTATION_KEY] = 0
            return 0
        raw_cursors = payload.get(TELEGRAM_MTPROTO_RECONCILE_CURSORS_KEY, {})
        cursors = raw_cursors if isinstance(raw_cursors, dict) else {}
        raw_heads = payload.get(TELEGRAM_MTPROTO_RECONCILE_HEAD_KEY, {})
        heads = raw_heads if isinstance(raw_heads, dict) else {}
        raw_modes = payload.get(TELEGRAM_MTPROTO_RECONCILE_MODES_KEY, {})
        modes = raw_modes if isinstance(raw_modes, dict) else {}
        peer_ids = sorted(selections)
        active_keys = {str(peer_id) for peer_id in peer_ids}
        cursors = {key: value for key, value in cursors.items() if key in active_keys}
        heads = {key: value for key, value in heads.items() if key in active_keys}
        modes = {key: value for key, value in modes.items() if key in active_keys}
        payload[TELEGRAM_MTPROTO_RECONCILE_CURSORS_KEY] = cursors
        payload[TELEGRAM_MTPROTO_RECONCILE_HEAD_KEY] = heads
        payload[TELEGRAM_MTPROTO_RECONCILE_MODES_KEY] = modes
        try:
            rotation = int(payload.get(TELEGRAM_MTPROTO_RECONCILE_ROTATION_KEY, 0))
        except (TypeError, ValueError):
            rotation = 0
        rotation %= len(peer_ids)
        ordered_peers = peer_ids[rotation:] + peer_ids[:rotation]
        candidates: dict[int, list[tuple[Object, str]]] = {}
        actual_newest_values: dict[int, dict[str, str | None]] = {}
        for peer_id in ordered_peers:
            base_filters = [
                Object.user_id == user_id,
                Object.provider == TELEGRAM_PROVIDER,
                Object.kind == TELEGRAM_KIND,
                Object.deleted_at.is_(None),
                Object.metadata_["transport"].as_string() == "mtproto",
                Object.metadata_["account_id"].as_string() == str(account_id),
                Object.metadata_["peer_id"].as_string() == str(peer_id),
            ]
            head_window = list(
                self._session.scalars(
                    select(Object)
                    .where(*base_filters)
                    .order_by(Object.occurred_at.desc().nullslast(), Object.id.desc())
                    .limit(TELEGRAM_MTPROTO_RECONCILE_HEAD_WINDOW)
                )
            )
            head_state = heads.get(str(peer_id))
            head_cursor = _reconcile_cursor(
                head_state.get("cursor") if isinstance(head_state, dict) else None
            )
            newest_cursor = _reconcile_cursor(
                head_state.get("newest") if isinstance(head_state, dict) else None
            )
            head_candidate: Object | None = None
            if head_window:
                newest = head_window[0]
                actual_newest_values[peer_id] = _object_cursor_value(newest)
                if newest_cursor != _object_cursor(newest):
                    head_candidate = newest
                elif head_cursor is not None:
                    for index, item in enumerate(head_window):
                        if _object_cursor(item) == head_cursor:
                            head_candidate = head_window[(index + 1) % len(head_window)]
                            break
                if head_candidate is None:
                    head_candidate = newest
            cursor = _reconcile_cursor(cursors.get(str(peer_id)))
            filters = list(base_filters)
            if cursor is not None:
                cursor_time, cursor_id = cursor
                if cursor_time is None:
                    filters.append(
                        and_(Object.occurred_at.is_(None), Object.id < cursor_id)
                    )
                else:
                    filters.append(
                        or_(
                            Object.occurred_at < cursor_time,
                            and_(Object.occurred_at == cursor_time, Object.id < cursor_id),
                            Object.occurred_at.is_(None),
                        )
                    )
            sweep = list(
                self._session.scalars(
                    select(Object)
                    .where(*filters)
                    .order_by(Object.occurred_at.desc().nullslast(), Object.id.desc())
                    .limit(TELEGRAM_MTPROTO_RECONCILE_SCAN_LIMIT)
                )
            )
            if not sweep and cursor is not None:
                # Reaching the end starts a fresh bounded sweep.  The cursor is
                # only advanced again when a row is actually inspected.
                sweep = list(
                    self._session.scalars(
                        select(Object)
                        .where(*base_filters)
                        .order_by(Object.occurred_at.desc().nullslast(), Object.id.desc())
                        .limit(TELEGRAM_MTPROTO_RECONCILE_SCAN_LIMIT)
                    )
                )
            seen: set[UUID] = set()
            peer_candidates: list[tuple[Object, str]] = []
            mode = modes.get(str(peer_id))
            if mode not in {"head", "sweep"}:
                mode = "sweep"
            if mode == "head" and head_candidate is not None:
                peer_candidates.append((head_candidate, "head"))
                seen.add(head_candidate.id)
            if mode == "sweep":
                for candidate in sweep:
                    if candidate.id not in seen:
                        peer_candidates.append((candidate, "sweep"))
                        seen.add(candidate.id)
            candidates[peer_id] = peer_candidates
        provider_calls = 0
        peer_counts: dict[int, int] = {}
        positions = {peer_id: 0 for peer_id in ordered_peers}
        last_serviced_index: int | None = None
        materializer = TelegramObjectMaterializer(self._session)
        notifications = TelegramMtprotoTransportNotificationService(self._session)
        transport = self._transport_factory()
        store = self._store()
        session = store.decrypt_session(account)
        while provider_calls < TELEGRAM_MTPROTO_RECONCILE_MAX_LOOKUPS:
            made_progress = False
            for peer_id in ordered_peers:
                if provider_calls >= TELEGRAM_MTPROTO_RECONCILE_MAX_LOOKUPS:
                    break
                position = positions[peer_id]
                while position < len(candidates[peer_id]):
                    if peer_counts.get(peer_id, 0) >= TELEGRAM_MTPROTO_RECONCILE_MAX_PER_PEER:
                        break
                    obj, mode = candidates[peer_id][position]
                    position += 1
                    positions[peer_id] = position
                    made_progress = True
                    metadata = obj.metadata_ or {}
                    message_id = metadata.get("message_id")
                    cursor_value = {
                        "occurred_at": obj.occurred_at.isoformat() if obj.occurred_at else None,
                        "id": str(obj.id),
                    }
                    peer_key = str(peer_id)
                    if mode == "sweep":
                        cursors[peer_key] = cursor_value
                    else:
                        heads[peer_key] = {
                            "cursor": cursor_value,
                            "newest": actual_newest_values[peer_id],
                        }
                    modes[peer_key] = "sweep" if mode == "head" else "head"
                    last_serviced_index = peer_ids.index(peer_id)
                    if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0:
                        # Local malformed rows advance the sweep but consume no
                        # provider budget and cannot pin a peer indefinitely.
                        continue
                    break
                else:
                    continue
                if peer_counts.get(peer_id, 0) >= TELEGRAM_MTPROTO_RECONCILE_MAX_PER_PEER:
                    continue
                if position > len(candidates[peer_id]):
                    continue
                if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0:
                    continue
                peer_counts[peer_id] = peer_counts.get(peer_id, 0) + 1
                provider_calls += 1
                metadata = obj.metadata_ or {}
                original_body = obj.body
                original_title = obj.title
                original_metadata = obj.metadata_
                original_occurred_at = obj.occurred_at
                original_deleted_at = obj.deleted_at
                selection = selections[peer_id]
                try:
                    reference = store.decrypt_reference(selection)
                    result = await transport.fetch_message(
                        session, reference, peer_id=peer_id, message_id=message_id
                    )
                    if result is None:
                        was_inbound = metadata.get("direction") == "inbound"
                        if was_inbound and tombstone_object(obj):
                            notifications.message_deleted(
                                user_id=user_id,
                                account_id=account_id,
                                peer_id=peer_id,
                                message_id=message_id,
                                obj=obj,
                                occurred_at=obj.occurred_at or _utcnow(),
                                conversation_title=(
                                    metadata.get("peer_title")
                                    or metadata.get("group_title")
                                    or selection.title
                                ),
                            )
                        elif tombstone_object(obj):
                            self._session.flush()
                        continue
                    if result.get("peer_id") != peer_id or result.get("message_id") != message_id:
                        continue
                    if result.get("service") or not result.get("text"):
                        continue
                    entry = TelegramMtprotoHistoryEntry(
                        message_id=message_id,
                        occurred_at=result.get("occurred_at") or obj.occurred_at,
                        text=result.get("text"),
                        sender_peer_id=result.get("sender_peer_id"),
                        reply_to_message_id=result.get("reply_to_message_id"),
                        topic_id=result.get("topic_id"),
                        edited_at=result.get("edited_at"),
                        is_service=bool(result.get("service")),
                        outgoing=bool(result.get("outgoing")),
                    )
                    normalized = _normalize_entry(
                        account, selection, entry, datetime.min.replace(tzinfo=UTC)
                    )
                    if normalized is not None:
                        materialized = materializer.upsert_mtproto_message(
                            user_id=user_id, normalized=normalized
                        )
                        if (
                            materialized.change == "updated"
                            and entry.edited_at is not None
                            and metadata.get("direction") == "inbound"
                            and normalized["metadata"].get("direction") == "inbound"
                        ):
                            notifications.message_edited(
                                user_id=user_id,
                                account_id=account_id,
                                peer_id=peer_id,
                                message_id=message_id,
                                obj=materialized.obj,
                                occurred_at=entry.occurred_at or obj.occurred_at or _utcnow(),
                                edited_at=entry.edited_at,
                                conversation_title=selection.title,
                            )
                except TelegramMtprotoProviderUnavailableError:
                    raise
                except TelegramMtprotoProviderReferenceInvalidError:
                    continue
                except TelegramMtprotoReadRejectedError:
                    continue
                except TelegramMtprotoAuthorizationInvalidError:
                    raise
                except TelegramMtprotoNotificationPersistenceError:
                    obj.body = original_body
                    obj.title = original_title
                    obj.metadata_ = original_metadata
                    obj.occurred_at = original_occurred_at
                    obj.deleted_at = original_deleted_at
                    self._session.flush()
                    raise
                except TelegramMtprotoWriteDefiniteError:
                    raise
                except ValueError:
                    continue
                except Exception:  # noqa: BLE001, S112 - isolate one candidate failure
                    continue
            if not made_progress:
                break
        if last_serviced_index is not None:
            payload[TELEGRAM_MTPROTO_RECONCILE_ROTATION_KEY] = (
                last_serviced_index + 1
            ) % len(peer_ids)
        return provider_calls

    async def _sync_selection(
        self, account: TelegramMtprotoAccount, selection: TelegramMtprotoChatSelection
    ) -> TelegramMtprotoHistorySummary:
        store = self._store()
        try:
            session = store.decrypt_session(account)
            provider_peer_reference = self._encryption_or_raise().decrypt(
                selection.provider_peer_reference_encrypted
            )
        except GoogleConfigurationError as exc:
            raise TelegramMtprotoConfigurationError("Telegram MTProto is not configured") from exc

        cutoff = selection.history_cutoff_at or _utcnow() - timedelta(
            days=TELEGRAM_MTPROTO_HISTORY_DAYS
        )
        latest_message_id = selection.history_latest_message_id
        backfill_before_message_id = selection.history_backfill_before_message_id
        history_complete = selection.history_complete
        previous_latest_message_id = latest_message_id
        stats = _ImportStats()
        materializer = TelegramObjectMaterializer(self._session)
        remaining = TELEGRAM_MTPROTO_HISTORY_MAX_MESSAGES_PER_RUN

        if latest_message_id is None:
            page = await self._fetch_page(
                session,
                provider_peer_reference,
                reverse=False,
                limit=TELEGRAM_MTPROTO_HISTORY_PAGE_SIZE,
            )
            materialized_in_page = self._apply_page(
                materializer,
                account,
                selection,
                page,
                cutoff,
                stats,
                previous_latest_message_id=None,
            )
            stats.scanned += len(page.entries)
            stats.skipped += len(page.entries) - materialized_in_page
            remaining -= len(page.entries)
            if page.entries:
                latest_message_id = max(entry.message_id for entry in page.entries)
            backfill_before_message_id, history_complete = _next_backfill_state(page, cutoff)
        else:
            page = await self._fetch_page(
                session,
                provider_peer_reference,
                reverse=True,
                min_message_id=latest_message_id,
                limit=TELEGRAM_MTPROTO_HISTORY_PAGE_SIZE,
            )
            materialized_in_page = self._apply_page(
                materializer,
                account,
                selection,
                page,
                cutoff,
                stats,
                previous_latest_message_id=previous_latest_message_id,
            )
            stats.scanned += len(page.entries)
            stats.skipped += len(page.entries) - materialized_in_page
            remaining -= len(page.entries)
            if page.entries:
                latest_message_id = max(latest_message_id, max(entry.message_id for entry in page.entries))

        if (
            remaining > 0
            and not history_complete
            and backfill_before_message_id is not None
        ):
            page = await self._fetch_page(
                session,
                provider_peer_reference,
                reverse=False,
                max_message_id=backfill_before_message_id,
                limit=min(TELEGRAM_MTPROTO_HISTORY_PAGE_SIZE, remaining),
            )
            materialized_in_page = self._apply_page(
                materializer, account, selection, page, cutoff, stats
            )
            stats.scanned += len(page.entries)
            stats.skipped += len(page.entries) - materialized_in_page
            backfill_before_message_id, history_complete = _next_backfill_state(page, cutoff)

        selection.history_latest_message_id = latest_message_id
        selection.history_backfill_before_message_id = backfill_before_message_id
        selection.history_cutoff_at = cutoff
        selection.history_complete = history_complete
        selection.history_last_synced_at = _utcnow()
        self._session.flush()
        return TelegramMtprotoHistorySummary(
            peer_id=selection.peer_id,
            scanned=stats.scanned,
            materialized=stats.materialized,
            created=stats.created,
            updated=stats.updated,
            unchanged=stats.unchanged,
            skipped=stats.skipped,
            jobs_enqueued=stats.jobs_enqueued,
            history_complete=history_complete,
        )

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

    async def _fetch_page(
        self,
        session: str,
        provider_peer_reference: str,
        *,
        limit: int,
        min_message_id: int | None = None,
        max_message_id: int | None = None,
        reverse: bool,
    ) -> TelegramMtprotoHistoryPage:
        page = await self._transport_factory().fetch_history(
            session,
            provider_peer_reference,
            limit=limit,
            min_message_id=min_message_id,
            max_message_id=max_message_id,
            reverse=reverse,
        )
        entries = page.entries[:limit]
        return TelegramMtprotoHistoryPage(
            entries=entries,
            has_more=page.has_more or len(page.entries) > len(entries),
        )

    def _apply_page(
        self,
        materializer: TelegramObjectMaterializer,
        account: TelegramMtprotoAccount,
        selection: TelegramMtprotoChatSelection,
        page: TelegramMtprotoHistoryPage,
        cutoff: datetime,
        stats: _ImportStats,
        previous_latest_message_id: int | None = None,
    ) -> int:
        materialized = 0
        notifications = TelegramMtprotoTransportNotificationService(self._session)
        with self._session.begin_nested():
            for entry in sorted(page.entries, key=lambda item: item.message_id):
                normalized = _normalize_entry(account, selection, entry, cutoff)
                if normalized is None:
                    continue
                materialized += 1
                result = materializer.upsert_mtproto_message(
                    user_id=account.user_id,
                    normalized=normalized,
                )
                stats.add(result)
                if (
                    previous_latest_message_id is not None
                    and entry.message_id > previous_latest_message_id
                    and result.change == "created"
                    and normalized["metadata"].get("direction") == "inbound"
                    and selection.scope_active
                ):
                    notifications.message_created(
                        user_id=account.user_id,
                        account_id=account.id,
                        peer_id=selection.peer_id,
                        message_id=entry.message_id,
                        obj=result.obj,
                        occurred_at=entry.occurred_at,
                        conversation_title=selection.title,
                    )
        return materialized


def _normalize_entry(
    account: TelegramMtprotoAccount,
    selection: TelegramMtprotoChatSelection,
    entry: TelegramMtprotoHistoryEntry,
    cutoff: datetime,
) -> dict | None:
    if entry.is_service or not entry.text or not entry.text.strip():
        return None
    if entry.occurred_at is None or entry.occurred_at < cutoff:
        return None
    body = _bound_body(entry.text)
    if not body.strip():
        return None
    first_line = body.strip().splitlines()[0].strip()
    title = build_mtproto_presentation_title(selection.title, first_line)
    return {
        "provider": TELEGRAM_PROVIDER,
        "kind": TELEGRAM_KIND,
        "origin": TELEGRAM_ORIGIN,
        "state": TELEGRAM_STATE,
        "external_id": f"mtproto|{account.id}|{selection.peer_id}|{entry.message_id}",
        "title": title,
        "body": body,
        "occurred_at": entry.occurred_at,
        "metadata": {
            "transport": "mtproto",
            "account_id": str(account.id),
            "peer_id": selection.peer_id,
            "peer_kind": selection.peer_kind,
            "message_id": entry.message_id,
            "peer_title": selection.title,
            "peer_username": selection.username,
            "group_title": selection.title,
            "group_username": selection.username,
            "is_forum": selection.is_forum,
            "sender_peer_id": entry.sender_peer_id,
            "direction": "outbound" if entry.outgoing else "inbound",
            "reply_to_message_id": entry.reply_to_message_id,
            "topic_id": entry.topic_id,
            "edited_at": entry.edited_at.isoformat() if entry.edited_at else None,
        },
    }


def _next_backfill_state(
    page: TelegramMtprotoHistoryPage, cutoff: datetime
) -> tuple[int | None, bool]:
    if not page.entries:
        return None, True
    oldest = min(page.entries, key=lambda item: item.message_id)
    if oldest.occurred_at is not None and oldest.occurred_at <= cutoff:
        return None, True
    if not page.has_more:
        return None, True
    return oldest.message_id, False


def _bound_body(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized[:MAX_TELEGRAM_MESSAGE_BODY_CHARS]


def _bound_title(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= 200:
        return stripped
    return stripped[:199].rstrip() + "…"


def build_mtproto_presentation_title(peer_title: str, first_line: str) -> str:
    """Build the canonical bounded title shared by history and mutations."""
    return _bound_title(f"{peer_title}: {first_line}")


def _build_transport() -> TelegramMtprotoTransport:
    if not _mtproto_is_configured():
        raise TelegramMtprotoConfigurationError("Telegram MTProto is not configured")
    return TelethonMtprotoTransport(settings.telegram_api_id, settings.telegram_api_hash.strip())


def _mtproto_is_configured() -> bool:
    return bool(
        settings.telegram_api_id > 0
        and settings.telegram_api_hash.strip()
        and settings.secretary_credential_key.strip()
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid_cursor(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _reconcile_cursor(value: object) -> tuple[datetime | None, UUID] | None:
    if not isinstance(value, dict):
        return None
    cursor_id = _uuid_cursor(value.get("id"))
    if cursor_id is None:
        return None
    raw_time = value.get("occurred_at")
    if raw_time is None:
        return None, cursor_id
    try:
        occurred_at = datetime.fromisoformat(str(raw_time))
    except ValueError:
        return None
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    return occurred_at.astimezone(UTC), cursor_id


def _object_cursor(obj: Object) -> tuple[datetime | None, UUID]:
    occurred_at = obj.occurred_at.astimezone(UTC) if obj.occurred_at else None
    return occurred_at, obj.id


def _object_cursor_value(obj: Object) -> dict[str, str | None]:
    return {
        "occurred_at": obj.occurred_at.isoformat() if obj.occurred_at else None,
        "id": str(obj.id),
    }
