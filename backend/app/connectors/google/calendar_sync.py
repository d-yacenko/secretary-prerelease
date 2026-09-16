from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.google.calendar_history_state import (
    complete_active_window,
    continue_active_window,
    get_calendar_backfill,
    get_history_backfill,
    persist_active_page_token,
    reconcile_discovered_calendars,
    select_history_calendar,
    set_calendar_backfill,
    set_history_backfill,
    set_last_history_calendar_id,
    start_active_window,
)
from app.connectors.google.calendar_normalize import normalize_calendar_event
from app.connectors.google.calendar_transport import CalendarTransport
from app.connectors.google.constants import (
    CALENDAR_READONLY_SCOPE,
    DEFAULT_CALENDAR_SYNC_DAYS_BACK,
    DEFAULT_CALENDAR_SYNC_DAYS_FORWARD,
    DEFAULT_CALENDAR_SYNC_MAX_EVENTS,
    LIVE_CALENDAR_LOOKBACK_DAYS,
    LIVE_CALENDAR_MAX_PAGES_PER_CALENDAR,
    LIVE_CALENDAR_PAGE_SIZE,
    LIVE_COVERAGE_STATE_KEY,
    LIVE_COVERAGE_VERSION,
    MAX_CALENDAR_SYNC_CALENDARS,
    MAX_CALENDAR_SYNC_EVENTS,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.errors import GoogleConnectorError
from app.connectors.google.gmail_transport import GoogleTokenManager
from app.connectors.google.oauth_service import GoogleOAuthService
from app.db.models import Object
from app.domain.object_visibility import passive_sync_should_skip_existing
from app.services.job_queue_service import JobQueueService


def utcnow() -> datetime:
    return datetime.now(UTC)


def _cancelled_status(value: object) -> bool:
    status = str(value or "").strip().lower()
    return status in {"cancelled", "canceled"}


def _fair_calendar_quota(remaining: int, calendars_left: int) -> int:
    if remaining <= 0 or calendars_left <= 0:
        return 0
    return max(1, remaining // calendars_left)


def _parse_stored_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _resolve_live_page_chain(
    stored: dict[str, Any],
    fallback_min: datetime,
    fallback_max: datetime,
) -> tuple[datetime, datetime, str | None]:
    raw_token = stored.get("next_page_token")
    if not raw_token:
        return fallback_min, fallback_max, None
    time_min = _parse_stored_datetime(stored.get("active_time_min"))
    time_max = _parse_stored_datetime(stored.get("active_time_max"))
    if time_min is None or time_max is None:
        return fallback_min, fallback_max, None
    return time_min, time_max, str(raw_token)


class CalendarSyncService:
    def __init__(
        self,
        session: Session,
        account_store: GoogleAccountStore,
        token_manager: GoogleTokenManager,
        transport: CalendarTransport,
        job_queue: JobQueueService,
        days_back: int = DEFAULT_CALENDAR_SYNC_DAYS_BACK,
        days_forward: int = DEFAULT_CALENDAR_SYNC_DAYS_FORWARD,
        default_limit: int = DEFAULT_CALENDAR_SYNC_MAX_EVENTS,
        max_limit: int = MAX_CALENDAR_SYNC_EVENTS,
        max_calendars: int = MAX_CALENDAR_SYNC_CALENDARS,
    ) -> None:
        self._session = session
        self._account_store = account_store
        self._token_manager = token_manager
        self._transport = transport
        self._job_queue = job_queue
        self._days_back = days_back
        self._days_forward = days_forward
        self._default_limit = default_limit
        self._max_limit = max_limit
        self._max_calendars = max_calendars

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
        if CALENDAR_READONLY_SCOPE not in account.scopes:
            raise GoogleConnectorError("google account is missing calendar scope")

        account_email = account.email
        owner_user_id = account.user_id
        effective_limit = limit if limit is not None else self._default_limit
        effective_limit = min(max(effective_limit, 1), self._max_limit)

        self._session.commit()
        access_token = self._token_manager.get_valid_access_token(account_id, user_id)
        self._session.commit()

        calendars = self._transport.list_calendars(access_token, self._max_calendars)
        calendar_entries: list[tuple[str, str | None]] = []
        for calendar in calendars:
            calendar_id = str(calendar.get("id", ""))
            if not calendar_id:
                continue
            summary = calendar.get("summary")
            calendar_entries.append(
                (
                    calendar_id,
                    str(summary) if summary is not None else None,
                )
            )

        live_stats = self._run_live_pass(
            account_id=account_id,
            user_id=user_id,
            owner_user_id=owner_user_id,
            access_token=access_token,
            calendar_entries=calendar_entries,
            effective_limit=effective_limit,
        )

        if include_history_pass:
            self._run_history_pass(
                account_id=account_id,
                user_id=user_id,
                owner_user_id=owner_user_id,
                access_token=access_token,
                calendar_ids=[calendar_id for calendar_id, _ in calendar_entries],
                calendar_summaries={
                    calendar_id: summary for calendar_id, summary in calendar_entries
                },
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

    def _live_operational_window(self) -> tuple[datetime, datetime]:
        now = utcnow()
        return (
            now - timedelta(days=LIVE_CALENDAR_LOOKBACK_DAYS),
            now + timedelta(days=self._days_forward),
        )

    def _run_live_pass(
        self,
        *,
        account_id: UUID,
        user_id: UUID,
        owner_user_id: UUID,
        access_token: str,
        calendar_entries: list[tuple[str, str | None]],
        effective_limit: int,
    ) -> dict[str, int]:
        fresh_min, fresh_max = self._live_operational_window()

        created = 0
        updated = 0
        jobs_enqueued = 0
        synchronized = 0
        unchanged = 0
        remaining = effective_limit
        calendar_state = self._account_store.get_calendar_sync_state(account_id, user_id)
        live_state = dict(calendar_state.get(LIVE_COVERAGE_STATE_KEY) or {})
        if not isinstance(live_state, dict):
            live_state = {}
        calendars_live = dict(live_state.get("calendars") or {})
        if not isinstance(calendars_live, dict):
            calendars_live = {}

        calendar_count = len(calendar_entries)
        for index, (calendar_id, calendar_summary) in enumerate(calendar_entries):
            quota = _fair_calendar_quota(remaining, calendar_count - index)
            if quota <= 0:
                continue
            self._session.commit()
            stored = dict(calendars_live.get(calendar_id) or {})
            if not isinstance(stored, dict):
                stored = {}
            time_min, time_max, next_token = _resolve_live_page_chain(
                stored, fresh_min, fresh_max
            )

            processed_for_calendar = 0
            pages = 0
            while processed_for_calendar < quota and pages < LIVE_CALENDAR_MAX_PAGES_PER_CALENDAR:
                page_size = min(
                    LIVE_CALENDAR_PAGE_SIZE,
                    quota - processed_for_calendar,
                    remaining - processed_for_calendar,
                )
                if page_size <= 0:
                    break
                pages += 1
                page = self._transport.list_events_page(
                    access_token=access_token,
                    calendar_id=calendar_id,
                    time_min=time_min,
                    time_max=time_max,
                    max_results=page_size,
                    page_token=next_token,
                    show_deleted=True,
                )
                stats = self._materialize_calendar_events(
                    raw_events=page.events,
                    owner_user_id=owner_user_id,
                    calendar_id=calendar_id,
                    calendar_summary=calendar_summary,
                    remaining=page_size,
                )
                created += stats["created"]
                updated += stats["updated"]
                jobs_enqueued += stats["jobs_enqueued"]
                synchronized += stats["synchronized"]
                unchanged += stats["unchanged"]
                processed_for_calendar += stats["processed"]
                next_token = page.next_page_token
                if not next_token:
                    break

            remaining -= processed_for_calendar
            if next_token:
                calendars_live[calendar_id] = {
                    "version": LIVE_COVERAGE_VERSION,
                    "active_time_min": time_min.isoformat(),
                    "active_time_max": time_max.isoformat(),
                    "next_page_token": next_token,
                }
            else:
                calendars_live.pop(calendar_id, None)

        live_state["version"] = LIVE_COVERAGE_VERSION
        live_state["calendars"] = calendars_live
        calendar_state[LIVE_COVERAGE_STATE_KEY] = live_state
        self._account_store.update_calendar_sync_state(account_id, user_id, calendar_state)
        self._session.commit()

        return {
            "synchronized": synchronized,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "jobs_enqueued": jobs_enqueued,
        }

    def _run_history_pass(
        self,
        *,
        account_id: UUID,
        user_id: UUID,
        owner_user_id: UUID,
        access_token: str,
        calendar_ids: list[str],
        calendar_summaries: dict[str, str | None],
        effective_limit: int,
    ) -> None:
        calendar_state = self._account_store.get_calendar_sync_state(account_id, user_id)
        original_backfill = get_history_backfill(calendar_state)
        reconciled_backfill = reconcile_discovered_calendars(
            original_backfill,
            calendar_ids,
            self._days_back,
            self._max_limit,
            effective_limit,
        )
        if reconciled_backfill != original_backfill:
            calendar_state = set_history_backfill(calendar_state, reconciled_backfill)
            self._account_store.update_calendar_sync_state(account_id, user_id, calendar_state)
            self._session.commit()

        calendar_id, plan, backfill = select_history_calendar(
            reconciled_backfill,
            calendar_ids,
            self._days_back,
        )
        if calendar_id is None or plan is None or plan.window is None:
            return

        entry = get_calendar_backfill(backfill, calendar_id)
        window = plan.window
        if window.next_page_token is None and not entry.get("active_start"):
            page_size = min(effective_limit, self._max_limit)
            entry = start_active_window(entry, window, self._days_back, page_size)
            backfill = set_calendar_backfill(backfill, calendar_id, entry)
            calendar_state = set_history_backfill(calendar_state, backfill)
            self._account_store.update_calendar_sync_state(account_id, user_id, calendar_state)
            self._session.commit()
            window = continue_active_window(entry)
            if window is None:
                return

        entry = get_calendar_backfill(backfill, calendar_id)
        page_size = entry.get("active_page_size", effective_limit)
        try:
            page_size = int(page_size)
        except (TypeError, ValueError):
            return
        if page_size <= 0:
            return

        page = self._transport.list_events_page(
            access_token=access_token,
            calendar_id=calendar_id,
            time_min=window.active_start,
            time_max=window.active_end,
            max_results=page_size,
            page_token=window.next_page_token,
        )

        stats = self._materialize_calendar_events(
            raw_events=page.events,
            owner_user_id=owner_user_id,
            calendar_id=calendar_id,
            calendar_summary=calendar_summaries.get(calendar_id),
            remaining=page_size,
        )
        del stats

        calendar_state = self._account_store.get_calendar_sync_state(account_id, user_id)
        backfill = get_history_backfill(calendar_state)
        entry = get_calendar_backfill(backfill, calendar_id)
        if page.next_page_token:
            entry = persist_active_page_token(entry, window, page.next_page_token)
        else:
            entry = complete_active_window(entry)
        backfill = set_calendar_backfill(backfill, calendar_id, entry)
        backfill = set_last_history_calendar_id(backfill, calendar_id)
        calendar_state = set_history_backfill(calendar_state, backfill)
        self._account_store.update_calendar_sync_state(account_id, user_id, calendar_state)
        self._session.flush()

    def _materialize_calendar_events(
        self,
        *,
        raw_events: list[dict[str, Any]],
        owner_user_id: UUID,
        calendar_id: str,
        calendar_summary: str | None,
        remaining: int,
    ) -> dict[str, int]:
        created = 0
        updated = 0
        jobs_enqueued = 0
        synchronized = 0
        unchanged = 0
        processed = 0

        for raw_event in raw_events:
            if remaining <= 0:
                break
            if not str(raw_event.get("id") or "").strip():
                continue
            normalized = normalize_calendar_event(
                raw_event,
                calendar_id=calendar_id,
                calendar_summary=calendar_summary,
            )
            existing = self._find_existing_calendar_object(
                owner_user_id, normalized["external_id"]
            )
            cancelled = _cancelled_status((normalized.get("metadata") or {}).get("status"))

            if existing is not None and passive_sync_should_skip_existing(existing):
                synchronized += 1
                unchanged += 1
                continue

            if cancelled:
                if existing is None:
                    continue
                if existing.status != "deleted":
                    self._apply_normalized_calendar_object(existing, normalized)
                    updated += 1
                    synchronized += 1
                    processed += 1
                    remaining -= 1
                    self._session.commit()
                else:
                    synchronized += 1
                    unchanged += 1
                    processed += 1
                    remaining -= 1
                    self._session.commit()
                continue

            if existing is None:
                obj = Object(
                    user_id=owner_user_id,
                    kind=normalized["kind"],
                    provider=normalized["provider"],
                    external_id=normalized["external_id"],
                    origin=normalized["origin"],
                    state=normalized["state"],
                    title=normalized["title"],
                    body=normalized.get("body"),
                    start_at=normalized.get("start_at"),
                    due_at=normalized.get("due_at"),
                    occurred_at=normalized.get("occurred_at"),
                    metadata_=normalized["metadata"],
                )
                self._session.add(obj)
                self._session.flush()
                created += 1
                synchronized += 1
                processed += 1
                remaining -= 1
                self._job_queue.enqueue(
                    "embed_object",
                    {"object_id": str(obj.id)},
                    user_id=owner_user_id,
                )
                jobs_enqueued += 1
                self._session.commit()
                continue

            if self._calendar_object_changed(existing, normalized):
                self._apply_normalized_calendar_object(existing, normalized)
                updated += 1
                synchronized += 1
                processed += 1
                remaining -= 1
                self._job_queue.enqueue(
                    "embed_object",
                    {"object_id": str(existing.id)},
                    user_id=owner_user_id,
                )
                jobs_enqueued += 1
                self._session.commit()
            else:
                synchronized += 1
                unchanged += 1
                processed += 1
                remaining -= 1
                self._session.commit()

        return {
            "created": created,
            "updated": updated,
            "jobs_enqueued": jobs_enqueued,
            "synchronized": synchronized,
            "unchanged": unchanged,
            "processed": processed,
        }

    def _find_existing_calendar_object(self, user_id: UUID, external_id: str) -> Object | None:
        return self._session.scalar(
            select(Object).where(
                Object.user_id == user_id,
                Object.provider == "google_calendar",
                Object.kind == "event",
                Object.external_id == external_id,
            )
        )

    def _calendar_object_changed(self, obj: Object, normalized: dict[str, Any]) -> bool:
        if obj.status == "deleted":
            return True
        if obj.title != normalized["title"]:
            return True
        if obj.body != normalized.get("body"):
            return True
        if obj.start_at != normalized.get("start_at"):
            return True
        if obj.due_at != normalized.get("due_at"):
            return True
        return obj.metadata_ != normalized["metadata"]

    def _apply_normalized_calendar_object(self, obj: Object, normalized: dict[str, Any]) -> None:
        obj.title = normalized["title"]
        obj.body = normalized.get("body")
        obj.start_at = normalized.get("start_at")
        obj.due_at = normalized.get("due_at")
        obj.occurred_at = normalized.get("occurred_at")
        obj.metadata_ = normalized["metadata"]
        if _cancelled_status((normalized.get("metadata") or {}).get("status")):
            obj.status = "deleted"
        else:
            obj.status = None


def build_calendar_sync_service(
    session: Session,
    credential_key: str,
    client_file: str,
    redirect_uri: str,
    days_back: int,
    days_forward: int,
    default_limit: int,
    max_limit: int,
    max_calendars: int,
    http_client: Any | None = None,
) -> CalendarSyncService:
    encryption = GoogleAccountStore.build_encryption(credential_key)
    account_store = GoogleAccountStore(session, encryption)
    oauth_service = GoogleOAuthService(client_file, redirect_uri, http_client=http_client)
    token_manager = GoogleTokenManager(session, account_store, oauth_service)
    transport = CalendarTransport(http_client=http_client)
    job_queue = JobQueueService(session)
    return CalendarSyncService(
        session=session,
        account_store=account_store,
        token_manager=token_manager,
        transport=transport,
        job_queue=job_queue,
        days_back=days_back,
        days_forward=days_forward,
        default_limit=default_limit,
        max_limit=max_limit,
        max_calendars=max_calendars,
    )
