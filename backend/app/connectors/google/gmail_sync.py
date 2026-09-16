from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.google.constants import (
    DEFAULT_SYNC_DAYS,
    DEFAULT_SYNC_LIMIT,
    MAX_SYNC_LIMIT,
    build_gmail_list_query,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.errors import GoogleApiError, GoogleConnectorError
from app.connectors.google.gmail_history_state import (
    complete_active_window,
    date_to_gmail,
    get_history_backfill,
    persist_active_page_token,
    plan_history_active_window,
    set_history_backfill,
    start_active_window,
)
from app.connectors.google.gmail_normalize import (
    extract_gmail_attachment_descriptors,
    normalize_gmail_message,
)
from app.connectors.google.gmail_transport import GmailTransport, GoogleTokenManager
from app.connectors.google.oauth_service import GoogleOAuthService
from app.db.models import Object
from app.services.client_intake_constants import MAX_EMAIL_ATTACHMENT_BYTES
from app.services.email_attachment_service import EmailAttachmentService
from app.services.job_queue_service import JobQueueService


def utcnow() -> datetime:
    return datetime.now(UTC)


class GmailSyncService:
    def __init__(
        self,
        session: Session,
        account_store: GoogleAccountStore,
        token_manager: GoogleTokenManager,
        transport: GmailTransport,
        job_queue: JobQueueService,
        sync_days: int = DEFAULT_SYNC_DAYS,
        default_limit: int = DEFAULT_SYNC_LIMIT,
        max_limit: int = MAX_SYNC_LIMIT,
    ) -> None:
        self._session = session
        self._account_store = account_store
        self._token_manager = token_manager
        self._transport = transport
        self._job_queue = job_queue
        self._sync_days = sync_days
        self._default_limit = default_limit
        self._max_limit = max_limit

    def sync_account(
        self,
        account_id: UUID,
        user_id: UUID,
        limit: int | None = None,
        *,
        include_history_pass: bool = False,
    ) -> dict[str, Any]:
        account = self._account_store.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise GoogleConnectorError("google account not found")

        account_email = account.email
        owner_user_id = account.user_id
        effective_limit = limit if limit is not None else self._default_limit
        effective_limit = min(max(effective_limit, 1), self._max_limit)

        self._session.commit()
        access_token = self._token_manager.get_valid_access_token(account_id, user_id)
        self._session.commit()

        live_stats = self._run_live_pass(
            account_id=account_id,
            user_id=user_id,
            owner_user_id=owner_user_id,
            access_token=access_token,
            effective_limit=effective_limit,
        )

        if include_history_pass:
            self._run_history_pass(
                account_id=account_id,
                user_id=user_id,
                owner_user_id=owner_user_id,
                access_token=access_token,
                effective_limit=effective_limit,
            )

        return {
            "account_email": account_email,
            "synchronized": live_stats["synchronized"],
            "created": live_stats["created"],
            "updated": live_stats["updated"],
            "unchanged": live_stats["unchanged"],
            "jobs_enqueued": live_stats["jobs_enqueued"],
        }

    def _run_live_pass(
        self,
        *,
        account_id: UUID,
        user_id: UUID,
        owner_user_id: UUID,
        access_token: str,
        effective_limit: int,
    ) -> dict[str, int]:
        after_date = (utcnow() - timedelta(days=self._sync_days)).strftime("%Y/%m/%d")
        query = build_gmail_list_query(after_date)
        message_ids = self._transport.list_message_ids(
            access_token=access_token,
            user_id="me",
            query=query,
            max_results=effective_limit,
        )
        return self._materialize_message_ids(
            message_ids=message_ids,
            owner_user_id=owner_user_id,
            access_token=access_token,
        )

    def _run_history_pass(
        self,
        *,
        account_id: UUID,
        user_id: UUID,
        owner_user_id: UUID,
        access_token: str,
        effective_limit: int,
    ) -> dict[str, int]:
        gmail_state = self._account_store.get_gmail_sync_state(account_id, user_id)
        original_backfill = get_history_backfill(gmail_state)
        plan = plan_history_active_window(original_backfill, self._sync_days)
        backfill = plan.backfill
        window = plan.window

        if backfill != original_backfill:
            gmail_state = set_history_backfill(gmail_state, backfill)
            self._account_store.update_gmail_sync_state(account_id, user_id, gmail_state)
            self._session.commit()

        if window is None:
            return {
                "synchronized": 0,
                "created": 0,
                "unchanged": 0,
                "jobs_enqueued": 0,
            }

        if window.next_page_token is None and not backfill.get("active_start"):
            backfill = start_active_window(backfill, window)
            gmail_state = set_history_backfill(gmail_state, backfill)
            self._account_store.update_gmail_sync_state(account_id, user_id, gmail_state)
            self._session.commit()

        query = build_gmail_list_query(
            date_to_gmail(window.active_start),
            date_to_gmail(window.active_end),
        )
        page = self._transport.list_message_ids_page(
            access_token=access_token,
            user_id="me",
            query=query,
            max_results=effective_limit,
            page_token=window.next_page_token,
        )

        stats = self._materialize_message_ids(
            message_ids=page.message_ids,
            owner_user_id=owner_user_id,
            access_token=access_token,
        )

        gmail_state = self._account_store.get_gmail_sync_state(account_id, user_id)
        backfill = get_history_backfill(gmail_state)
        if page.next_page_token:
            backfill = persist_active_page_token(backfill, window, page.next_page_token)
        else:
            backfill = complete_active_window(backfill)
        gmail_state = set_history_backfill(gmail_state, backfill)
        self._account_store.update_gmail_sync_state(account_id, user_id, gmail_state)
        self._session.flush()
        return stats

    def _materialize_message_ids(
        self,
        *,
        message_ids: list[str],
        owner_user_id: UUID,
        access_token: str,
    ) -> dict[str, int]:
        known_external_ids = self._load_known_gmail_external_ids(owner_user_id, message_ids)
        self._session.commit()

        created = 0
        updated = 0
        jobs_enqueued = 0
        synchronized = 0
        unchanged = 0

        for message_id in message_ids:
            if message_id in known_external_ids:
                synchronized += 1
                unchanged += 1
                continue

            self._session.commit()
            raw_message = self._transport.get_message(access_token, "me", message_id)
            normalized = normalize_gmail_message(raw_message)
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
            descriptors = extract_gmail_attachment_descriptors(raw_message.get("payload", {}))
            if descriptors:
                attachment_service = EmailAttachmentService(self._session, owner_user_id)

                def fetch_attachment(
                    desc: dict,
                    mid: str = message_id,
                ) -> bytes | None:
                    inline = desc.get("inline_bytes")
                    if inline is not None:
                        return inline
                    attachment_id = desc.get("attachment_id")
                    if not attachment_id:
                        return None
                    known_size = desc.get("size")
                    if known_size is not None and int(known_size) > MAX_EMAIL_ATTACHMENT_BYTES:
                        return None
                    try:
                        return self._transport.get_attachment(
                            access_token,
                            "me",
                            mid,
                            str(attachment_id),
                        )
                    except GoogleApiError:
                        return None

                attachment_service.materialize_gmail_attachments(
                    obj, descriptors, fetch_attachment
                )
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
        }

    def _load_known_gmail_external_ids(
        self,
        user_id: UUID,
        message_ids: list[str],
    ) -> set[str]:
        if not message_ids:
            return set()
        rows = self._session.scalars(
            select(Object.external_id).where(
                Object.user_id == user_id,
                Object.provider == "gmail",
                Object.kind == "email",
                Object.external_id.in_(message_ids),
            )
        )
        return {str(external_id) for external_id in rows if external_id is not None}


def build_gmail_sync_service(
    session: Session,
    credential_key: str,
    client_file: str,
    redirect_uri: str,
    sync_days: int,
    default_limit: int,
    max_limit: int,
    http_client: Any | None = None,
) -> GmailSyncService:
    encryption = GoogleAccountStore.build_encryption(credential_key)
    account_store = GoogleAccountStore(session, encryption)
    oauth_service = GoogleOAuthService(client_file, redirect_uri, http_client=http_client)
    token_manager = GoogleTokenManager(session, account_store, oauth_service)
    transport = GmailTransport(http_client=http_client)
    job_queue = JobQueueService(session)
    return GmailSyncService(
        session=session,
        account_store=account_store,
        token_manager=token_manager,
        transport=transport,
        job_queue=job_queue,
        sync_days=sync_days,
        default_limit=default_limit,
        max_limit=max_limit,
    )
