from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from email import message_from_bytes
from email import policy as email_policy
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.yandex.constants import (
    DEFAULT_MAIL_FOLDER,
    DEFAULT_SYNC_DAYS,
    DEFAULT_SYNC_LIMIT,
    MAX_SYNC_DAYS,
    MAX_SYNC_LIMIT,
)
from app.connectors.yandex.credentials import YandexMailAccountStore, YandexMailSyncSnapshot
from app.connectors.yandex.errors import YandexConnectorError
from app.connectors.yandex.imap_transport import ImaplibTransport, ImapTransport
from app.connectors.yandex.mail_history_state import (
    INITIAL_HISTORY_BEFORE_UID,
    clear_history_if_uidvalidity_changed,
    complete_active_window,
    continue_active_scan,
    get_history_backfill,
    persist_history_cursor,
    plan_history_active_scan,
    set_history_backfill,
    start_active_window,
)
from app.connectors.yandex.mail_normalize import (
    build_external_id,
    extract_imap_attachment_descriptors,
    normalize_imap_message,
)
from app.db.models import Object
from app.services.email_attachment_service import EmailAttachmentService
from app.services.job_queue_service import JobQueueService


def utcnow() -> datetime:
    return datetime.now(UTC)


def _imap_date(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _valid_forward_checkpoint(stored_uidvalidity: Any, uidvalidity: int, stored_last_uid: Any) -> bool:
    if stored_uidvalidity is None or stored_uidvalidity != uidvalidity:
        return False
    if stored_last_uid is None:
        return False
    try:
        last_uid = int(stored_last_uid)
    except (TypeError, ValueError):
        return False
    return last_uid > 0


def _merge_forward_checkpoint(
    state: dict[str, Any],
    uidvalidity: int,
    inbox_last_uid: int,
) -> dict[str, Any]:
    merged = dict(state)
    merged["inbox_uidvalidity"] = uidvalidity
    merged["inbox_last_uid"] = inbox_last_uid
    return merged


def _clear_history_on_mailbox_uidvalidity_change(
    state: dict[str, Any],
    current_uidvalidity: int,
    stored_root_uidvalidity: Any,
) -> dict[str, Any]:
    if stored_root_uidvalidity is not None:
        try:
            if int(stored_root_uidvalidity) != current_uidvalidity:
                return set_history_backfill(state, {})
        except (TypeError, ValueError):
            return set_history_backfill(state, {})
    return clear_history_if_uidvalidity_changed(state, current_uidvalidity)


class YandexMailSyncService:
    def __init__(
        self,
        session: Session,
        account_store: YandexMailAccountStore,
        job_queue: JobQueueService,
        sync_days: int = DEFAULT_SYNC_DAYS,
        default_limit: int = DEFAULT_SYNC_LIMIT,
        max_limit: int = MAX_SYNC_LIMIT,
        transport_factory: Callable[[YandexMailSyncSnapshot], ImapTransport] | None = None,
    ) -> None:
        self._session = session
        self._account_store = account_store
        self._job_queue = job_queue
        self._sync_days = min(max(sync_days, 1), MAX_SYNC_DAYS)
        self._default_limit = default_limit
        self._max_limit = max_limit
        self._transport_factory = transport_factory

    def sync_account(
        self,
        account_id: UUID,
        user_id: UUID,
        limit: int | None = None,
        *,
        include_history_pass: bool = False,
    ) -> dict[str, Any]:
        snapshot = self._account_store.load_sync_snapshot(account_id, user_id)
        if snapshot is None:
            raise YandexConnectorError("yandex mail account not found")

        effective_limit = limit if limit is not None else self._default_limit
        effective_limit = min(max(effective_limit, 1), self._max_limit)

        self._session.commit()

        transport = self._open_transport(snapshot)
        folder = DEFAULT_MAIL_FOLDER
        stored_state = dict(snapshot.sync_state)

        try:
            uidvalidity = transport.select_folder(folder)
            live_stats = self._run_live_pass(
                account_id=account_id,
                user_id=user_id,
                snapshot=snapshot,
                transport=transport,
                folder=folder,
                uidvalidity=uidvalidity,
                stored_state=stored_state,
                effective_limit=effective_limit,
            )

            if include_history_pass:
                self._run_history_pass(
                    account_id=account_id,
                    user_id=user_id,
                    transport=transport,
                    folder=folder,
                    uidvalidity=uidvalidity,
                    stored_root_uidvalidity=stored_state.get("inbox_uidvalidity"),
                    effective_limit=effective_limit,
                )

            return {
                "account_email": snapshot.email,
                "synchronized": live_stats["synchronized"],
                "created": live_stats["created"],
                "updated": live_stats["updated"],
                "unchanged": live_stats["unchanged"],
                "jobs_enqueued": live_stats["jobs_enqueued"],
            }
        finally:
            if isinstance(transport, ImaplibTransport):
                transport.close()

    def _run_live_pass(
        self,
        *,
        account_id: UUID,
        user_id: UUID,
        snapshot: YandexMailSyncSnapshot,
        transport: ImapTransport,
        folder: str,
        uidvalidity: int,
        stored_state: dict[str, Any],
        effective_limit: int,
    ) -> dict[str, int]:
        since_date = utcnow() - timedelta(days=self._sync_days)
        stored_uidvalidity = stored_state.get("inbox_uidvalidity")
        stored_last_uid = stored_state.get("inbox_last_uid")
        use_incremental = _valid_forward_checkpoint(
            stored_uidvalidity,
            uidvalidity,
            stored_last_uid,
        )

        if use_incremental:
            candidate_uids = transport.search_uids_incremental(
                folder=folder,
                after_uid=int(stored_last_uid),
                max_results=effective_limit,
            )
        else:
            candidate_uids = transport.search_uids_initial(
                folder=folder,
                since_date=since_date,
                max_results=effective_limit,
            )

        stats, max_processed_uid = self._materialize_uids(
            transport=transport,
            folder=folder,
            uidvalidity=uidvalidity,
            uids=candidate_uids,
            owner_user_id=snapshot.user_id,
            initial_max_uid=int(stored_last_uid or 0) if use_incremental else 0,
        )

        account = self._account_store.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise YandexConnectorError("yandex mail account not found")
        merged_state = _merge_forward_checkpoint(
            dict(account.sync_state or {}),
            uidvalidity,
            max_processed_uid,
        )
        self._account_store.update_sync_state(account, merged_state)
        self._session.commit()

        return stats

    def _run_history_pass(
        self,
        *,
        account_id: UUID,
        user_id: UUID,
        transport: ImapTransport,
        folder: str,
        uidvalidity: int,
        stored_root_uidvalidity: Any,
        effective_limit: int,
    ) -> None:
        account = self._account_store.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise YandexConnectorError("yandex mail account not found")

        state = dict(account.sync_state or {})
        state = _clear_history_on_mailbox_uidvalidity_change(
            state,
            uidvalidity,
            stored_root_uidvalidity,
        )
        original_backfill = get_history_backfill(state)
        plan = plan_history_active_scan(original_backfill, self._sync_days)
        if plan.backfill != original_backfill:
            state = set_history_backfill(state, plan.backfill)
            self._account_store.update_sync_state(account, state)
            self._session.commit()

        if plan.scan is None:
            return

        backfill = get_history_backfill(state)
        scan = plan.scan
        if scan.active_before_uid is None and not backfill.get("active_start_date"):
            backfill = start_active_window(
                backfill,
                scan,
                self._sync_days,
                INITIAL_HISTORY_BEFORE_UID,
                inbox_uidvalidity=uidvalidity,
            )
            state = set_history_backfill(state, backfill)
            self._account_store.update_sync_state(account, state)
            self._session.commit()
            active = continue_active_scan(backfill)
            if active is None:
                return
        else:
            active = continue_active_scan(backfill)
            if active is None:
                return

        page = transport.search_uids_history_page(
            folder=folder,
            since_date=_imap_date(active.active_start_date),
            before_date=_imap_date(active.active_end_date),
            before_uid=active.active_before_uid,
            max_results=effective_limit,
        )

        snapshot = self._account_store.load_sync_snapshot(account_id, user_id)
        if snapshot is None:
            raise YandexConnectorError("yandex mail account not found")
        self._materialize_uids(
            transport=transport,
            folder=folder,
            uidvalidity=uidvalidity,
            uids=page.uids,
            owner_user_id=snapshot.user_id,
            initial_max_uid=0,
        )

        account = self._account_store.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise YandexConnectorError("yandex mail account not found")
        state = dict(account.sync_state or {})
        backfill = get_history_backfill(state)
        if page.complete:
            backfill = complete_active_window(backfill)
        else:
            if page.next_before_uid is None:
                return
            backfill = persist_history_cursor(backfill, page.next_before_uid)
        state = set_history_backfill(state, backfill)
        self._account_store.update_sync_state(account, state)
        self._session.flush()

    def _materialize_uids(
        self,
        *,
        transport: ImapTransport,
        folder: str,
        uidvalidity: int,
        uids: list[int],
        owner_user_id: UUID,
        initial_max_uid: int,
    ) -> tuple[dict[str, int], int]:
        known_external_ids = self._load_known_external_ids(
            owner_user_id,
            folder,
            uidvalidity,
            uids,
        )
        self._session.commit()

        created = 0
        updated = 0
        jobs_enqueued = 0
        synchronized = 0
        unchanged = 0
        max_processed_uid = initial_max_uid

        for uid in uids:
            external_id = build_external_id(folder, uidvalidity, uid)
            if external_id in known_external_ids:
                synchronized += 1
                unchanged += 1
                max_processed_uid = max(max_processed_uid, uid)
                continue

            self._session.commit()
            raw_message = transport.fetch_message(folder, uid)
            normalized = normalize_imap_message(
                raw_message,
                folder=folder,
                uid=uid,
                uidvalidity=uidvalidity,
            )
            obj = Object(
                user_id=owner_user_id,
                kind=normalized["kind"],
                provider=normalized["provider"],
                external_id=normalized["external_id"],
                origin=normalized["origin"],
                state=normalized["state"],
                title=normalized["title"],
                body=normalized.get("body"),
                metadata_=normalized["metadata"],
                occurred_at=normalized.get("occurred_at"),
            )
            self._session.add(obj)
            self._session.flush()
            created += 1
            synchronized += 1
            max_processed_uid = max(max_processed_uid, uid)
            msg = message_from_bytes(raw_message, policy=email_policy.default)
            descriptors = extract_imap_attachment_descriptors(msg)
            if descriptors:
                attachment_service = EmailAttachmentService(self._session, owner_user_id)
                attachment_service.materialize_yandex_attachments(obj, descriptors)
            self._job_queue.enqueue(
                "embed_object",
                {"object_id": str(obj.id)},
                user_id=owner_user_id,
            )
            jobs_enqueued += 1
            self._session.commit()

        return {
            "synchronized": synchronized,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "jobs_enqueued": jobs_enqueued,
        }, max_processed_uid

    def _open_transport(self, snapshot: YandexMailSyncSnapshot) -> ImapTransport:
        if self._transport_factory is not None:
            return self._transport_factory(snapshot)
        return ImaplibTransport(
            host=snapshot.imap_host,
            port=snapshot.imap_port,
            email=snapshot.email,
            password=snapshot.app_password,
        )

    def _load_known_external_ids(
        self,
        user_id: UUID,
        folder: str,
        uidvalidity: int,
        uids: list[int],
    ) -> set[str]:
        if not uids:
            return set()
        external_ids = [build_external_id(folder, uidvalidity, uid) for uid in uids]
        rows = self._session.scalars(
            select(Object.external_id).where(
                Object.user_id == user_id,
                Object.provider == "yandex_mail",
                Object.kind == "email",
                Object.external_id.in_(external_ids),
            )
        )
        return {str(external_id) for external_id in rows if external_id is not None}


def build_yandex_mail_sync_service(
    session: Session,
    credential_key: str,
    sync_days: int,
    default_limit: int,
    max_limit: int,
    transport_factory: Callable[[YandexMailSyncSnapshot], ImapTransport] | None = None,
) -> YandexMailSyncService:
    account_store = YandexMailAccountStore(
        session,
        YandexMailAccountStore.build_encryption(credential_key),
    )
    job_queue = JobQueueService(session)
    return YandexMailSyncService(
        session=session,
        account_store=account_store,
        job_queue=job_queue,
        sync_days=sync_days,
        default_limit=default_limit,
        max_limit=max_limit,
        transport_factory=transport_factory,
    )
