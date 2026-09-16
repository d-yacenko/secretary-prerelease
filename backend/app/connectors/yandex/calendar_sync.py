from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.connectors.yandex.caldav_host import trusted_caldav_base_url
from app.connectors.yandex.caldav_transport import (
    CalDavCalendar,
    CalDavFetchResult,
    CalDavHttpTransport,
    CalDavTransport,
)
from app.connectors.yandex.calendar_credentials import (
    YandexCalendarAccountStore,
    YandexCalendarSyncSnapshot,
)
from app.connectors.yandex.calendar_history_state import (
    clear_stale_reset_coverage,
    complete_active_history_range,
    continue_active_history_range,
    get_calendar_entry,
    mark_initial_coverage_complete,
    persist_history_backfill_cursor,
    reconcile_active_history_range,
    select_history_calendar,
    set_calendar_entry,
    set_last_history_calendar_href,
    start_active_history_range,
)
from app.connectors.yandex.calendar_normalize import (
    build_external_id,
    normalize_caldav_resource,
)
from app.connectors.yandex.constants import (
    CALENDAR_BACKFILL_MIN_SLICE_DAYS,
    CALENDAR_BACKFILL_SLICE_DAYS,
    CALENDAR_BACKFILL_SLICE_OVERLAP_DAYS,
    CALENDAR_OPERATIONAL_QUERY_MAX_ITERATIONS,
    CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION,
    DEFAULT_CALENDAR_SYNC_DAYS_BACK,
    DEFAULT_CALENDAR_SYNC_DAYS_FORWARD,
    DEFAULT_CALENDAR_SYNC_LIMIT,
    LIVE_CALENDAR_LOOKBACK_DAYS,
    MAX_CALENDAR_SYNC_CALENDARS,
    MAX_CALENDAR_SYNC_DAYS_BACK,
    MAX_CALENDAR_SYNC_DAYS_FORWARD,
    MAX_CALENDAR_SYNC_LIMIT,
)
from app.connectors.yandex.errors import YandexCalDavStaleSyncTokenError, YandexConnectorError
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


@dataclass
class _BatchStats:
    synchronized: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    tombstoned: int = 0
    jobs_enqueued: int = 0
    budget_consumed: int = 0


@dataclass
class _ApplyBatchResult:
    stats: _BatchStats
    completed_all_resources: bool
    last_processed_href: str | None


class YandexCalendarSyncService:
    def __init__(
        self,
        session: Session,
        account_store: YandexCalendarAccountStore,
        job_queue: JobQueueService,
        days_back: int = DEFAULT_CALENDAR_SYNC_DAYS_BACK,
        days_forward: int = DEFAULT_CALENDAR_SYNC_DAYS_FORWARD,
        default_limit: int = DEFAULT_CALENDAR_SYNC_LIMIT,
        max_limit: int = MAX_CALENDAR_SYNC_LIMIT,
        max_calendars: int = MAX_CALENDAR_SYNC_CALENDARS,
        transport_factory: Callable[[YandexCalendarSyncSnapshot], CalDavTransport] | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._account_store = account_store
        self._job_queue = job_queue
        self._days_back = min(max(days_back, 1), MAX_CALENDAR_SYNC_DAYS_BACK)
        self._days_forward = min(max(days_forward, 1), MAX_CALENDAR_SYNC_DAYS_FORWARD)
        self._default_limit = default_limit
        self._max_limit = max_limit
        self._max_calendars = max_calendars
        self._transport_factory = transport_factory
        self._now_factory = now_factory or utcnow

    def sync_account(
        self,
        account_id: UUID,
        user_id: UUID,
        limit: int | None = None,
        include_history_pass: bool = False,
    ) -> dict[str, Any]:
        snapshot = self._account_store.load_sync_snapshot(account_id, user_id)
        if snapshot is None:
            raise YandexConnectorError("yandex calendar account not found")

        occurrence_budget = limit if limit is not None else self._default_limit
        occurrence_budget = min(max(occurrence_budget, 1), self._max_limit)

        self._session.commit()

        transport = self._open_transport(snapshot)
        window_min, window_max = self._sync_window()
        sync_state_root = dict(snapshot.sync_state or {})
        calendar_state = dict(sync_state_root.get("calendars", {}))
        if (
            sync_state_root.get("normalization_version", 0)
            < CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION
        ):
            for calendar_href, stored in list(calendar_state.items()):
                refreshed = dict(stored)
                refreshed.pop("sync_token", None)
                refreshed["backfill_cursor"] = window_min.isoformat()
                refreshed.pop("pending_sync_token", None)
                calendar_state[calendar_href] = refreshed
        calendars = transport.discover_calendars(self._max_calendars)
        calendar_summaries = {
            calendar.href: calendar.display_name for calendar in calendars
        }

        totals = _BatchStats()
        calendar_count = len(calendars)

        for index, calendar in enumerate(calendars):
            allocated = _fair_calendar_quota(occurrence_budget, calendar_count - index)
            if allocated <= 0:
                continue

            calendar_href = calendar.href
            stored = dict(calendar_state.get(calendar_href, {}))
            calendar_summary = calendar.display_name or stored.get("display_name")
            quota = allocated

            try:
                batch_stats, quota, stored, _operational_hit = self._sync_operational_calendar(
                    transport=transport,
                    snapshot=snapshot,
                    calendar_href=calendar_href,
                    stored=stored,
                    calendar_summary=calendar_summary,
                    window_min=window_min,
                    window_max=window_max,
                    occurrence_budget=quota,
                )
            except YandexConnectorError:
                if calendar_summary:
                    stored["display_name"] = calendar_summary
                calendar_state[calendar_href] = stored
                self._persist_calendar_state(account_id, user_id, sync_state_root, calendar_state)
                raise
            self._merge_stats(totals, batch_stats)

            if stored.get("sync_token") and quota > 0:
                if not stored.get("covered_window_end"):
                    stored["covered_window_end"] = window_max.isoformat()
                batch_stats, quota, stored = self._sync_steady_state_calendar(
                    transport=transport,
                    snapshot=snapshot,
                    account_id=account_id,
                    user_id=user_id,
                    sync_state_root=sync_state_root,
                    calendar_state=calendar_state,
                    calendar_href=calendar_href,
                    stored=stored,
                    calendar_summary=calendar_summary,
                    window_min=window_min,
                    window_max=window_max,
                    occurrence_budget=quota,
                )
                self._merge_stats(totals, batch_stats)
            elif quota > 0:
                batch_stats, quota, stored = self._sync_backfill_calendar(
                    transport=transport,
                    snapshot=snapshot,
                    calendar=calendar,
                    calendar_href=calendar_href,
                    stored=stored,
                    calendar_summary=calendar_summary,
                    window_min=window_min,
                    window_max=window_max,
                    occurrence_budget=quota,
                )
                self._merge_stats(totals, batch_stats)

            consumed = allocated - quota
            occurrence_budget = max(0, occurrence_budget - consumed)
            if calendar_summary:
                stored["display_name"] = calendar_summary
            calendar_state[calendar_href] = stored

        self._persist_calendar_state(account_id, user_id, sync_state_root, calendar_state)

        if include_history_pass:
            history_budget = min(
                limit if limit is not None else self._default_limit,
                self._max_limit,
            )
            sync_state_root, calendar_state = self._run_history_pass(
                transport=transport,
                snapshot=snapshot,
                account_id=account_id,
                user_id=user_id,
                sync_state_root=sync_state_root,
                calendar_state=calendar_state,
                calendars=calendars,
                calendar_summaries=calendar_summaries,
                history_budget=history_budget,
            )
            self._persist_calendar_state(account_id, user_id, sync_state_root, calendar_state)

        return {
            "account_email": snapshot.email,
            "synchronized": totals.synchronized,
            "created": totals.created,
            "updated": totals.updated,
            "unchanged": totals.unchanged,
            "tombstoned": totals.tombstoned,
            "jobs_enqueued": totals.jobs_enqueued,
        }

    def _sync_window(self) -> tuple[datetime, datetime]:
        now = self._now_factory()
        return now - timedelta(days=self._days_back), now + timedelta(days=self._days_forward)

    def _operational_window(self) -> tuple[datetime, datetime]:
        now = self._now_factory()
        return (
            now - timedelta(days=LIVE_CALENDAR_LOOKBACK_DAYS),
            now + timedelta(days=self._days_forward),
        )

    def _clear_operational_continuation(self, stored: dict[str, Any]) -> None:
        stored.pop("operational_href_cursor", None)
        stored.pop("operational_query_start", None)
        stored.pop("operational_query_end", None)
        stored.pop("operational_slice_start", None)
        stored.pop("operational_slice_end", None)

    def _persist_operational_query_range(
        self,
        stored: dict[str, Any],
        range_start: datetime,
        range_end: datetime,
        leaf_start: datetime,
        leaf_end: datetime,
    ) -> None:
        stored["operational_query_start"] = range_start.isoformat()
        stored["operational_query_end"] = range_end.isoformat()
        stored["operational_slice_start"] = leaf_start.isoformat()
        stored["operational_slice_end"] = leaf_end.isoformat()

    def _sync_operational_calendar(
        self,
        transport: CalDavTransport,
        snapshot: YandexCalendarSyncSnapshot,
        calendar_href: str,
        stored: dict[str, Any],
        calendar_summary: str | None,
        window_min: datetime,
        window_max: datetime,
        occurrence_budget: int,
    ) -> tuple[_BatchStats, int, dict[str, Any], bool]:
        op_min, op_max = self._operational_window()
        totals = _BatchStats()
        min_slice = timedelta(days=CALENDAR_BACKFILL_MIN_SLICE_DAYS)
        overlap = timedelta(days=CALENDAR_BACKFILL_SLICE_OVERLAP_DAYS)
        frozen_start = self._parse_iso_datetime(stored.get("operational_query_start"))
        frozen_end = self._parse_iso_datetime(stored.get("operational_query_end"))
        if frozen_start is not None and frozen_end is not None and frozen_start < frozen_end:
            range_start, range_end = frozen_start, frozen_end
        else:
            range_start, range_end = window_min, window_max
        leaf_start = self._parse_iso_datetime(stored.get("operational_slice_start")) or range_start
        leaf_end = self._parse_iso_datetime(stored.get("operational_slice_end")) or range_end
        leaf_start = max(leaf_start, range_start)
        leaf_end = min(leaf_end, range_end)
        if leaf_end <= leaf_start:
            leaf_start, leaf_end = range_start, range_end

        operational_hit = False
        iterations = 0
        while occurrence_budget > 0:
            iterations += 1
            if iterations > CALENDAR_OPERATIONAL_QUERY_MAX_ITERATIONS:
                raise YandexConnectorError("operational calendar query exceeded iteration limit")

            after_href = stored.get("operational_href_cursor")
            if after_href is not None:
                after_href = str(after_href)
            self._session.commit()
            fetch_result = transport.query_events(
                calendar_href=calendar_href,
                time_min=leaf_start,
                time_max=leaf_end,
                max_results=self._max_limit,
                expand_min=op_min,
                expand_max=op_max,
                after_href=after_href,
            )
            operational_hit = operational_hit or bool(
                fetch_result.events or fetch_result.selected_ref_hrefs
            )

            if fetch_result.provider_truncated:
                stored.pop("operational_href_cursor", None)
                duration = leaf_end - leaf_start
                if duration <= min_slice:
                    self._persist_operational_query_range(
                        stored, range_start, range_end, leaf_start, leaf_end
                    )
                    raise YandexConnectorError(
                        "operational calendar-query truncated at minimum time slice"
                    )
                leaf_end = leaf_start + duration / 2
                self._persist_operational_query_range(
                    stored, range_start, range_end, leaf_start, leaf_end
                )
                continue

            apply_result = self._apply_fetch_batch(
                user_id=snapshot.user_id,
                fetch_result=fetch_result,
                calendar_href=calendar_href,
                calendar_summary=calendar_summary,
                time_min=op_min,
                time_max=op_max,
                cap_occurrences=True,
                occurrence_budget=occurrence_budget,
                reconcile_occurrences=True,
                allow_fallback=True,
            )
            self._merge_stats(totals, apply_result.stats)
            occurrence_budget -= apply_result.stats.budget_consumed

            if fetch_result.local_truncated or not apply_result.completed_all_resources:
                if not apply_result.completed_all_resources:
                    if apply_result.last_processed_href:
                        stored["operational_href_cursor"] = apply_result.last_processed_href
                elif fetch_result.last_selected_href:
                    stored["operational_href_cursor"] = fetch_result.last_selected_href
                if stored.get("operational_slice_end"):
                    self._persist_operational_query_range(
                        stored, range_start, range_end, leaf_start, leaf_end
                    )
                return totals, occurrence_budget, stored, operational_hit

            stored.pop("operational_href_cursor", None)
            if stored.get("operational_slice_end"):
                next_start = leaf_end - overlap
                if next_start <= leaf_start:
                    next_start = leaf_end
                if next_start >= range_end:
                    self._clear_operational_continuation(stored)
                    break
                leaf_start = next_start
                leaf_end = range_end
                self._persist_operational_query_range(
                    stored, range_start, range_end, leaf_start, leaf_end
                )
                continue
            self._clear_operational_continuation(stored)
            break

        return totals, occurrence_budget, stored, operational_hit

    def _persist_calendar_state(
        self,
        account_id: UUID,
        user_id: UUID,
        sync_state_root: dict[str, Any],
        calendar_state: dict[str, Any],
    ) -> None:
        account = self._account_store.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise YandexConnectorError("yandex calendar account not found")
        updated_state = dict(sync_state_root)
        updated_state["calendars"] = calendar_state
        updated_state["normalization_version"] = CURRENT_YANDEX_CALENDAR_NORMALIZATION_VERSION
        self._account_store.update_sync_state(account, updated_state)
        self._session.commit()

    def _merge_stored_calendar_entry(
        self,
        stored: dict[str, Any],
        entry: dict[str, Any],
        calendar_summary: str | None,
    ) -> dict[str, Any]:
        merged = dict(stored)
        merged.update(entry)
        if calendar_summary:
            merged["display_name"] = calendar_summary
        return merged

    def _run_history_pass(
        self,
        transport: CalDavTransport,
        snapshot: YandexCalendarSyncSnapshot,
        account_id: UUID,
        user_id: UUID,
        sync_state_root: dict[str, Any],
        calendar_state: dict[str, Any],
        calendars: list[CalDavCalendar],
        calendar_summaries: dict[str, str | None],
        history_budget: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if history_budget <= 0:
            return sync_state_root, calendar_state

        calendar_hrefs = [calendar.href for calendar in calendars]
        state = dict(sync_state_root)
        state["calendars"] = calendar_state

        for href in calendar_hrefs:
            entry = get_calendar_entry(state, href)
            reconciled = reconcile_active_history_range(entry, self._days_back)
            if reconciled != entry:
                state = set_calendar_entry(state, href, reconciled)

        calendar_href, plan, state = select_history_calendar(
            state,
            calendar_hrefs,
            self._days_back,
        )
        if calendar_href is None or plan is None or plan.range is None:
            return state, dict(state.get("calendars", {}))

        calendar_state = dict(state.get("calendars", {}))
        entry = get_calendar_entry(state, calendar_href)
        if continue_active_history_range(entry) is None:
            entry = start_active_history_range(
                entry,
                plan.range.active_start,
                plan.range.active_end,
                self._days_back,
            )
            state = set_calendar_entry(state, calendar_href, entry)
            calendar_state[calendar_href] = self._merge_stored_calendar_entry(
                calendar_state.get(calendar_href, {}),
                entry,
                calendar_summaries.get(calendar_href),
            )
            self._persist_calendar_state(account_id, user_id, state, calendar_state)

        entry = get_calendar_entry(state, calendar_href)
        active = continue_active_history_range(entry)
        if active is None:
            return state, calendar_state

        frozen_start = active.active_start
        frozen_end = active.active_end
        cursor = active.history_backfill_cursor or frozen_start
        cursor = max(cursor, frozen_start)
        min_slice = timedelta(days=CALENDAR_BACKFILL_MIN_SLICE_DAYS)
        overlap = timedelta(days=CALENDAR_BACKFILL_SLICE_OVERLAP_DAYS)

        parent_slice_end = min(
            cursor + timedelta(days=CALENDAR_BACKFILL_SLICE_DAYS),
            frozen_end,
        )
        leaf_end = active.history_backfill_slice_end or parent_slice_end
        leaf_end = min(leaf_end, parent_slice_end)
        leaf_start = cursor
        calendar_summary = calendar_summaries.get(calendar_href) or entry.get("display_name")
        stored_sync_token = entry.get("sync_token")

        self._session.commit()
        while True:
            fetch_result = transport.query_events(
                calendar_href=calendar_href,
                time_min=leaf_start,
                time_max=leaf_end,
                max_results=self._max_limit,
            )
            if len(fetch_result.events) < self._max_limit:
                break
            duration = leaf_end - leaf_start
            if duration <= min_slice:
                raise YandexConnectorError("history calendar slice exceeds resource cap")
            leaf_end = leaf_start + duration / 2

        apply_result = self._apply_fetch_batch(
            user_id=snapshot.user_id,
            fetch_result=fetch_result,
            calendar_href=calendar_href,
            calendar_summary=calendar_summary,
            time_min=leaf_start,
            time_max=leaf_end,
            cap_occurrences=True,
            occurrence_budget=history_budget,
            reconcile_occurrences=False,
        )

        entry = get_calendar_entry(state, calendar_href)
        if not apply_result.completed_all_resources:
            entry = persist_history_backfill_cursor(entry, leaf_start, leaf_end)
        else:
            if leaf_end < parent_slice_end:
                next_cursor = leaf_end - overlap
                if next_cursor <= leaf_start:
                    next_cursor = leaf_end
                entry = persist_history_backfill_cursor(
                    entry,
                    next_cursor,
                    parent_slice_end,
                )
            elif parent_slice_end >= frozen_end:
                entry = complete_active_history_range(entry)
            else:
                next_cursor = parent_slice_end - overlap
                if next_cursor <= cursor:
                    next_cursor = parent_slice_end
                entry = persist_history_backfill_cursor(entry, next_cursor, None)

        if stored_sync_token is not None:
            entry["sync_token"] = stored_sync_token

        state = set_calendar_entry(state, calendar_href, entry)
        state = set_last_history_calendar_href(state, calendar_href)
        calendar_state[calendar_href] = self._merge_stored_calendar_entry(
            calendar_state.get(calendar_href, {}),
            entry,
            calendar_summary,
        )
        return state, calendar_state

    def _sync_backfill_calendar(
        self,
        transport: CalDavTransport,
        snapshot: YandexCalendarSyncSnapshot,
        calendar: CalDavCalendar,
        calendar_href: str,
        stored: dict[str, Any],
        calendar_summary: str | None,
        window_min: datetime,
        window_max: datetime,
        occurrence_budget: int,
    ) -> tuple[_BatchStats, int, dict[str, Any]]:
        if not stored.get("pending_sync_token") and calendar.sync_token:
            stored["pending_sync_token"] = calendar.sync_token
        return self._run_bounded_reconciliation(
            transport=transport,
            snapshot=snapshot,
            calendar_href=calendar_href,
            stored=stored,
            calendar_summary=calendar_summary,
            range_start=window_min,
            range_end=window_max,
            occurrence_budget=occurrence_budget,
            establish_token_on_complete=True,
        )

    def _sync_steady_state_calendar(
        self,
        transport: CalDavTransport,
        snapshot: YandexCalendarSyncSnapshot,
        account_id: UUID,
        user_id: UUID,
        sync_state_root: dict[str, Any],
        calendar_state: dict[str, Any],
        calendar_href: str,
        stored: dict[str, Any],
        calendar_summary: str | None,
        window_min: datetime,
        window_max: datetime,
        occurrence_budget: int,
    ) -> tuple[_BatchStats, int, dict[str, Any]]:
        totals = _BatchStats()
        if occurrence_budget > 0 and stored.get("sync_token"):
            batch_stats, occurrence_budget, stored = self._sync_incremental_calendar(
                transport=transport,
                snapshot=snapshot,
                account_id=account_id,
                user_id=user_id,
                sync_state_root=sync_state_root,
                calendar_state=calendar_state,
                calendar_href=calendar_href,
                stored=stored,
                stored_token=str(stored["sync_token"]),
                calendar_summary=calendar_summary,
                time_min=window_min,
                time_max=window_max,
                occurrence_budget=occurrence_budget,
            )
            self._merge_stats(totals, batch_stats)

        return totals, occurrence_budget, stored

    def _run_bounded_reconciliation(
        self,
        transport: CalDavTransport,
        snapshot: YandexCalendarSyncSnapshot,
        calendar_href: str,
        stored: dict[str, Any],
        calendar_summary: str | None,
        range_start: datetime,
        range_end: datetime,
        occurrence_budget: int,
        establish_token_on_complete: bool,
    ) -> tuple[_BatchStats, int, dict[str, Any]]:
        totals = _BatchStats()
        cursor = self._parse_iso_datetime(stored.get("backfill_cursor")) or range_start
        cursor = max(cursor, range_start)
        min_slice = timedelta(days=CALENDAR_BACKFILL_MIN_SLICE_DAYS)
        overlap = timedelta(days=CALENDAR_BACKFILL_SLICE_OVERLAP_DAYS)
        iterations = 0

        while occurrence_budget > 0 and cursor < range_end:
            iterations += 1
            if iterations > 500:
                raise YandexConnectorError("bounded calendar reconciliation exceeded iteration limit")

            parent_slice_end = min(
                cursor + timedelta(days=CALENDAR_BACKFILL_SLICE_DAYS),
                range_end,
            )
            leaf_end = self._parse_iso_datetime(stored.get("backfill_slice_end")) or parent_slice_end
            leaf_end = min(leaf_end, parent_slice_end)
            leaf_start = cursor

            self._session.commit()
            while True:
                fetch_result = transport.query_events(
                    calendar_href=calendar_href,
                    time_min=leaf_start,
                    time_max=leaf_end,
                    max_results=self._max_limit,
                )
                self._capture_baseline_sync_token(stored, fetch_result.sync_token)
                if len(fetch_result.events) < self._max_limit:
                    break
                duration = leaf_end - leaf_start
                if duration <= min_slice:
                    raise YandexConnectorError("bounded calendar slice exceeds resource cap")
                leaf_end = leaf_start + duration / 2

            apply_result = self._apply_fetch_batch(
                user_id=snapshot.user_id,
                fetch_result=fetch_result,
                calendar_href=calendar_href,
                calendar_summary=calendar_summary,
                time_min=leaf_start,
                time_max=leaf_end,
                cap_occurrences=True,
                occurrence_budget=occurrence_budget,
                reconcile_occurrences=False,
            )
            self._merge_stats(totals, apply_result.stats)
            occurrence_budget -= apply_result.stats.budget_consumed

            if not apply_result.completed_all_resources:
                stored["backfill_cursor"] = leaf_start.isoformat()
                stored["backfill_slice_end"] = leaf_end.isoformat()
                return totals, occurrence_budget, stored

            stored.pop("backfill_slice_end", None)
            if leaf_end < parent_slice_end:
                next_cursor = leaf_end - overlap
                if next_cursor <= leaf_start:
                    next_cursor = leaf_end
                cursor = next_cursor
                stored["backfill_slice_end"] = parent_slice_end.isoformat()
                continue

            if parent_slice_end >= range_end:
                cursor = range_end
                break
            next_cursor = parent_slice_end - overlap
            cursor = next_cursor if next_cursor > cursor else parent_slice_end

        if cursor < range_end:
            stored["backfill_cursor"] = cursor.isoformat()
            return totals, occurrence_budget, stored

        stored.pop("backfill_cursor", None)
        stored.pop("backfill_slice_end", None)
        if establish_token_on_complete and stored.get("pending_sync_token"):
            stored["sync_token"] = stored["pending_sync_token"]
            stored.pop("pending_sync_token", None)
        if establish_token_on_complete:
            stored = mark_initial_coverage_complete(stored, range_start, range_end)
        else:
            stored["covered_window_end"] = range_end.isoformat()
        return totals, occurrence_budget, stored

    def _capture_baseline_sync_token(self, stored: dict[str, Any], fetch_token: str | None) -> None:
        if stored.get("pending_sync_token"):
            return
        if fetch_token:
            stored["pending_sync_token"] = fetch_token

    def _sync_incremental_calendar(
        self,
        transport: CalDavTransport,
        snapshot: YandexCalendarSyncSnapshot,
        account_id: UUID,
        user_id: UUID,
        sync_state_root: dict[str, Any],
        calendar_state: dict[str, Any],
        calendar_href: str,
        stored: dict[str, Any],
        stored_token: str,
        calendar_summary: str | None,
        time_min: datetime,
        time_max: datetime,
        occurrence_budget: int,
    ) -> tuple[_BatchStats, int, dict[str, Any]]:
        totals = _BatchStats()
        current_token = stored_token
        iterations = 0

        while True:
            iterations += 1
            if iterations > 50:
                raise YandexConnectorError("incremental calendar sync exceeded iteration limit")
            if occurrence_budget <= 0:
                break
            self._session.commit()
            try:
                fetch_result = transport.sync_collection(
                    calendar_href=calendar_href,
                    sync_token=current_token,
                    max_results=self._max_limit,
                    time_min=time_min,
                    time_max=time_max,
                )
            except YandexCalDavStaleSyncTokenError:
                stored = clear_stale_reset_coverage(stored)
                stored.pop("sync_token", None)
                stored["backfill_cursor"] = time_min.isoformat()
                stored.pop("pending_sync_token", None)
                calendar_state[calendar_href] = stored
                self._persist_calendar_state(
                    account_id,
                    user_id,
                    sync_state_root,
                    calendar_state,
                )
                batch_stats, occurrence_budget, stored = self._run_bounded_reconciliation(
                    transport=transport,
                    snapshot=snapshot,
                    calendar_href=calendar_href,
                    stored=stored,
                    calendar_summary=calendar_summary,
                    range_start=time_min,
                    range_end=time_max,
                    occurrence_budget=occurrence_budget,
                    establish_token_on_complete=True,
                )
                self._merge_stats(totals, batch_stats)
                return totals, occurrence_budget, stored

            apply_result = self._apply_fetch_batch(
                user_id=snapshot.user_id,
                fetch_result=fetch_result,
                calendar_href=calendar_href,
                calendar_summary=calendar_summary,
                time_min=time_min,
                time_max=time_max,
                cap_occurrences=True,
                occurrence_budget=occurrence_budget,
                reconcile_occurrences=True,
                allow_fallback=True,
                fallback_min=self._operational_window()[0],
                fallback_max=self._operational_window()[1],
            )
            self._merge_stats(totals, apply_result.stats)
            occurrence_budget -= apply_result.stats.budget_consumed

            if not apply_result.completed_all_resources:
                break

            if fetch_result.sync_token:
                stored["sync_token"] = fetch_result.sync_token

            if not fetch_result.events:
                break
            if fetch_result.sync_token is None:
                break
            if not fetch_result.truncated and fetch_result.sync_token == current_token:
                break
            current_token = fetch_result.sync_token
            if occurrence_budget <= 0:
                break

        return totals, occurrence_budget, stored

    def _apply_fetch_batch(
        self,
        user_id: UUID,
        fetch_result: CalDavFetchResult,
        calendar_href: str,
        calendar_summary: str | None,
        time_min: datetime,
        time_max: datetime,
        cap_occurrences: bool,
        occurrence_budget: int,
        reconcile_occurrences: bool,
        allow_fallback: bool = False,
        fallback_min: datetime | None = None,
        fallback_max: datetime | None = None,
    ) -> _ApplyBatchResult:
        stats = _BatchStats()
        last_processed_href: str | None = None
        completed_all_resources = True

        for deleted_href in fetch_result.deleted_hrefs:
            if cap_occurrences and occurrence_budget <= 0:
                completed_all_resources = False
                break
            self._session.commit()
            tombstoned_count, deletions_complete = self._tombstone_all_by_event_href(
                user_id,
                deleted_href,
                max_count=occurrence_budget if cap_occurrences else None,
            )
            stats.tombstoned += tombstoned_count
            stats.synchronized += tombstoned_count
            stats.budget_consumed += tombstoned_count
            if cap_occurrences:
                occurrence_budget -= tombstoned_count
            if not deletions_complete:
                completed_all_resources = False
                break
        if fetch_result.deleted_hrefs:
            self._session.commit()

        for raw_event in fetch_result.events:
            result = normalize_caldav_resource(
                raw_event.calendar_data,
                calendar_href=calendar_href,
                calendar_summary=calendar_summary,
                etag=raw_event.etag,
                event_href=raw_event.event_href,
                time_min=time_min,
                time_max=time_max,
                allow_fallback=allow_fallback,
                fallback_min=fallback_min,
                fallback_max=fallback_max,
            )
            normalized_list = result.events
            returned_ids: set[str] = set()
            resource_completed = True
            for normalized in normalized_list:
                if cap_occurrences and occurrence_budget <= 0:
                    resource_completed = False
                    completed_all_resources = False
                    break
                returned_ids.add(normalized["external_id"])
                change = self._upsert_event(user_id, normalized)
                stats.synchronized += 1
                if change == "created":
                    stats.created += 1
                    stats.jobs_enqueued += 1
                elif change == "updated":
                    stats.updated += 1
                    stats.jobs_enqueued += 1
                elif change == "tombstoned":
                    stats.tombstoned += 1
                else:
                    stats.unchanged += 1
                if change != "unchanged":
                    stats.budget_consumed += 1
                    if cap_occurrences:
                        occurrence_budget -= 1
            if not resource_completed:
                completed_all_resources = False
                break
            recon_exclude_ids = set(returned_ids)
            if result.recurrence_master_uid:
                if cap_occurrences and occurrence_budget <= 0:
                    completed_all_resources = False
                    break
                tombstoned_legacy = self._tombstone_legacy_recurrence_master(
                    user_id,
                    calendar_href,
                    result.recurrence_master_uid,
                )
                recon_exclude_ids.add(
                    build_external_id(calendar_href, result.recurrence_master_uid)
                )
                if tombstoned_legacy:
                    stats.tombstoned += 1
                    stats.synchronized += 1
                    stats.budget_consumed += 1
                    if cap_occurrences:
                        occurrence_budget -= 1
            if (
                reconcile_occurrences
                and result.occurrence_set_complete
                and result.occurrence_coverage_min is not None
                and result.occurrence_coverage_max is not None
                and (returned_ids or result.recurrence_master_uid)
            ):
                removed, missing_complete = self._tombstone_missing_occurrences(
                    user_id=user_id,
                    event_href=raw_event.event_href,
                    returned_external_ids=recon_exclude_ids,
                    time_min=result.occurrence_coverage_min,
                    time_max=result.occurrence_coverage_max,
                    max_count=occurrence_budget if cap_occurrences else None,
                )
                stats.tombstoned += removed
                stats.synchronized += removed
                stats.budget_consumed += removed
                if cap_occurrences:
                    occurrence_budget -= removed
                if not missing_complete:
                    completed_all_resources = False
                    break
            if resource_completed:
                last_processed_href = raw_event.event_href
            self._session.commit()
            if cap_occurrences and occurrence_budget <= 0:
                if raw_event != fetch_result.events[-1]:
                    completed_all_resources = False
                break

        return _ApplyBatchResult(
            stats=stats,
            completed_all_resources=completed_all_resources,
            last_processed_href=last_processed_href,
        )

    def _tombstone_missing_occurrences(
        self,
        user_id: UUID,
        event_href: str,
        returned_external_ids: set[str],
        time_min: datetime,
        time_max: datetime,
        max_count: int | None = None,
    ) -> tuple[int, bool]:
        fetch_limit = None if max_count is None else max_count + 1
        candidates = self._find_active_by_event_href_in_window(
            user_id,
            event_href,
            time_min,
            time_max,
            exclude_external_ids=returned_external_ids,
            limit=fetch_limit,
        )
        complete = True
        if max_count is not None and len(candidates) > max_count:
            complete = False
            candidates = candidates[:max_count]
        tombstoned = 0
        for obj in candidates:
            metadata = dict(obj.metadata_ or {})
            metadata["caldav_deleted"] = True
            metadata["deleted_at"] = self._now_factory().isoformat()
            obj.status = "deleted"
            obj.metadata_ = metadata
            tombstoned += 1
        return tombstoned, complete

    def _tombstone_legacy_recurrence_master(
        self,
        user_id: UUID,
        calendar_href: str,
        event_uid: str,
    ) -> bool:
        external_id = build_external_id(calendar_href, event_uid)
        obj = self._find_existing_event(user_id, external_id)
        if obj is None:
            return False
        metadata = dict(obj.metadata_ or {})
        changed = False
        if obj.status != "deleted":
            metadata["recurrence_master_superseded"] = True
            metadata["recurrence_master_superseded_at"] = self._now_factory().isoformat()
            metadata.pop("caldav_deleted", None)
            metadata.pop("deleted_at", None)
            obj.status = "deleted"
            changed = True
        elif metadata.get("recurrence_master_superseded") is True:
            if metadata.get("caldav_deleted") is True or "deleted_at" in metadata:
                metadata.pop("caldav_deleted", None)
                metadata.pop("deleted_at", None)
                changed = True
        else:
            return False
        if changed:
            obj.metadata_ = metadata
            self._session.flush()
        return changed

    def _merge_stats(self, totals: _BatchStats, batch: _BatchStats) -> None:
        totals.synchronized += batch.synchronized
        totals.created += batch.created
        totals.updated += batch.updated
        totals.unchanged += batch.unchanged
        totals.tombstoned += batch.tombstoned
        totals.jobs_enqueued += batch.jobs_enqueued
        totals.budget_consumed += batch.budget_consumed

    def _upsert_event(self, user_id: UUID, normalized: dict[str, Any]) -> str:
        existing = self._find_existing_event(user_id, normalized["external_id"])
        cancelled = _cancelled_status((normalized.get("metadata") or {}).get("status"))
        if existing is not None and passive_sync_should_skip_existing(existing):
            return "unchanged"
        if cancelled:
            if existing is None:
                return "unchanged"
            if existing.status == "deleted":
                return "unchanged"
            self._apply_normalized_event(existing, normalized)
            existing.status = "deleted"
            return "tombstoned"
        if existing is None:
            obj = Object(
                user_id=user_id,
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
            self._job_queue.enqueue(
                "embed_object",
                {"object_id": str(obj.id)},
                user_id=user_id,
            )
            return "created"

        if self._event_changed(existing, normalized):
            self._apply_normalized_event(existing, normalized)
            self._job_queue.enqueue(
                "embed_object",
                {"object_id": str(existing.id)},
                user_id=user_id,
            )
            return "updated"
        return "unchanged"

    def _tombstone_all_by_event_href(
        self,
        user_id: UUID,
        event_href: str,
        max_count: int | None = None,
    ) -> tuple[int, bool]:
        fetch_limit = None if max_count is None else max_count + 1
        candidates = self._find_all_by_event_href(
            user_id,
            event_href,
            limit=fetch_limit,
            active_only=True,
        )
        complete = True
        if max_count is not None and len(candidates) > max_count:
            complete = False
            candidates = candidates[:max_count]
        tombstoned = 0
        for obj in candidates:
            metadata = dict(obj.metadata_ or {})
            metadata["caldav_deleted"] = True
            metadata["deleted_at"] = self._now_factory().isoformat()
            obj.status = "deleted"
            obj.metadata_ = metadata
            tombstoned += 1
        return tombstoned, complete

    def _open_transport(self, snapshot: YandexCalendarSyncSnapshot) -> CalDavTransport:
        if self._transport_factory is not None:
            return self._transport_factory(snapshot)
        base_url = trusted_caldav_base_url(snapshot.caldav_host)
        return CalDavHttpTransport(
            email=snapshot.email,
            password=snapshot.app_password,
            base_url=base_url,
        )

    def _find_existing_event(self, user_id: UUID, external_id: str) -> Object | None:
        return self._session.scalar(
            select(Object).where(
                Object.user_id == user_id,
                Object.provider == "yandex_calendar",
                Object.kind == "event",
                Object.external_id == external_id,
            )
        )

    def _find_all_by_event_href(
        self,
        user_id: UUID,
        event_href: str,
        limit: int | None = None,
        active_only: bool = False,
    ) -> list[Object]:
        conditions = [
            Object.user_id == user_id,
            Object.provider == "yandex_calendar",
            Object.kind == "event",
            Object.metadata_["event_href"].as_string() == event_href,
        ]
        if active_only:
            conditions.append(or_(Object.status.is_(None), Object.status != "deleted"))
        stmt = select(Object).where(*conditions).order_by(Object.id)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self._session.scalars(stmt).all())

    def _find_active_by_event_href_in_window(
        self,
        user_id: UUID,
        event_href: str,
        time_min: datetime,
        time_max: datetime,
        exclude_external_ids: set[str] | None = None,
        limit: int | None = None,
    ) -> list[Object]:
        conditions = [
            Object.user_id == user_id,
            Object.provider == "yandex_calendar",
            Object.kind == "event",
            Object.metadata_["event_href"].as_string() == event_href,
            or_(Object.status.is_(None), Object.status != "deleted"),
            Object.start_at.is_not(None),
            Object.start_at >= time_min,
            Object.start_at <= time_max,
        ]
        if exclude_external_ids:
            conditions.append(Object.external_id.notin_(list(exclude_external_ids)))
        stmt = select(Object).where(*conditions).order_by(Object.id)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self._session.scalars(stmt).all())

    def _event_changed(self, obj: Object, normalized: dict[str, Any]) -> bool:
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

    def _apply_normalized_event(self, obj: Object, normalized: dict[str, Any]) -> None:
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

    def _parse_iso_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)


def build_yandex_calendar_sync_service(
    session: Session,
    credential_key: str,
    days_back: int,
    days_forward: int,
    default_limit: int,
    max_limit: int,
    max_calendars: int,
    transport_factory: Callable[[YandexCalendarSyncSnapshot], CalDavTransport] | None = None,
    now_factory: Callable[[], datetime] | None = None,
) -> YandexCalendarSyncService:
    account_store = YandexCalendarAccountStore(
        session,
        YandexCalendarAccountStore.build_encryption(credential_key),
    )
    job_queue = JobQueueService(session)
    return YandexCalendarSyncService(
        session=session,
        account_store=account_store,
        job_queue=job_queue,
        days_back=days_back,
        days_forward=days_forward,
        default_limit=default_limit,
        max_limit=max_limit,
        max_calendars=max_calendars,
        transport_factory=transport_factory,
        now_factory=now_factory,
    )
