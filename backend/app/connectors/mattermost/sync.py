from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.connectors.mattermost.constants import (
    DEFAULT_INITIAL_POSTS_PER_CHANNEL,
    DEFAULT_MAX_CHANNELS,
    DEFAULT_MAX_POSTS_PER_RUN,
    DEFAULT_SYNC_DAYS,
    DEFAULT_SYNC_OVERLAP_SECONDS,
    MAX_INITIAL_POSTS_PER_CHANNEL,
    MAX_MAX_CHANNELS,
    MAX_MAX_POSTS_PER_RUN,
    MAX_SYNC_DAYS,
    MAX_SYNC_OVERLAP_SECONDS,
)
from app.connectors.mattermost.credentials import MattermostAccountStore, MattermostSyncSnapshot
from app.connectors.mattermost.errors import (
    MattermostConnectorError,
    MattermostEndpointNotFoundError,
)
from app.connectors.mattermost.materialize import MattermostObjectMaterializer
from app.connectors.mattermost.mattermost_history_state import (
    complete_active_history,
    continue_active_scan,
    get_history_backfill,
    persist_active_before_post_id,
    persist_active_oldest_processed_post_id,
    reconcile_active_scan,
    select_history_channel,
    set_channel_entry,
    set_history_backfill,
    set_last_history_channel_id,
    start_active_history_range,
)
from app.connectors.mattermost.normalize import (
    MattermostChannelContext,
)
from app.connectors.mattermost.transport import (
    MattermostHttpTransport,
    MattermostPostsPage,
    MattermostTransport,
)
from app.db.models import Object
from app.services.job_queue_service import JobQueueService


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class _SyncTotals:
    synchronized: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    jobs_enqueued: int = 0


class MattermostSyncService:
    def __init__(
        self,
        session: Session,
        account_store: MattermostAccountStore,
        job_queue: JobQueueService,
        sync_days: int = DEFAULT_SYNC_DAYS,
        max_channels: int = DEFAULT_MAX_CHANNELS,
        initial_posts_per_channel: int = DEFAULT_INITIAL_POSTS_PER_CHANNEL,
        max_posts_per_run: int = DEFAULT_MAX_POSTS_PER_RUN,
        overlap_seconds: int = DEFAULT_SYNC_OVERLAP_SECONDS,
        transport_factory: Callable[[MattermostSyncSnapshot], MattermostTransport] | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._account_store = account_store
        self._job_queue = job_queue
        self._sync_days = min(max(sync_days, 1), MAX_SYNC_DAYS)
        self._max_channels = min(max(max_channels, 1), MAX_MAX_CHANNELS)
        self._initial_posts_per_channel = min(
            max(initial_posts_per_channel, 1),
            MAX_INITIAL_POSTS_PER_CHANNEL,
        )
        self._max_posts_per_run = min(max(max_posts_per_run, 1), MAX_MAX_POSTS_PER_RUN)
        self._overlap_seconds = min(max(overlap_seconds, 0), MAX_SYNC_OVERLAP_SECONDS)
        self._transport_factory = transport_factory
        self._now_factory = now_factory or utcnow
        self._materializer = MattermostObjectMaterializer(session)

    def sync_account(
        self,
        account_id: UUID,
        user_id: UUID,
        *,
        include_history_pass: bool = False,
    ) -> dict[str, Any]:
        account = self._account_store.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise MattermostConnectorError("mattermost account not found")

        snapshot = self._account_store.load_sync_snapshot(
            account_id=account_id,
            user_id=user_id,
            normalized_server_url=account.server_url,
        )
        if snapshot is None:
            raise MattermostConnectorError("mattermost account not found")

        self._session.commit()
        transport = self._open_transport(snapshot)
        owns_transport = self._should_close_transport(transport)
        try:
            now = self._now_factory()
            cutoff = now - timedelta(days=self._sync_days)
            cutoff_ms = int(cutoff.timestamp() * 1000)

            channels = self._discover_channels(transport, snapshot.remote_user_id)
            teams_by_id = self._build_teams_index(transport)

            sync_state_root = dict(snapshot.sync_state or {})
            channel_state_root = dict(sync_state_root.get("channels", {}))

            posts_budget = self._max_posts_per_run
            totals = _SyncTotals()

            for channel in channels[: self._max_channels]:
                if posts_budget <= 0:
                    break
                channel_id = str(channel.get("id") or "").strip()
                if not channel_id:
                    continue
                stored = dict(channel_state_root.get(channel_id, {}))
                channel_context = self._build_channel_context(channel, teams_by_id)

                if stored.get("bootstrap_complete"):
                    posts_budget, stored, batch = self._sync_new_posts(
                        transport=transport,
                        snapshot=snapshot,
                        channel_context=channel_context,
                        stored=stored,
                        cutoff_ms=cutoff_ms,
                        posts_budget=posts_budget,
                    )
                else:
                    posts_budget, stored, batch = self._sync_bootstrap(
                        transport=transport,
                        snapshot=snapshot,
                        channel_context=channel_context,
                        stored=stored,
                        cutoff_ms=cutoff_ms,
                        posts_budget=posts_budget,
                    )
                self._merge_totals(totals, batch)

                if posts_budget > 0:
                    posts_budget, stored, batch = self._sync_edit_sweep(
                        transport=transport,
                        snapshot=snapshot,
                        channel_context=channel_context,
                        stored=stored,
                        cutoff_ms=cutoff_ms,
                        posts_budget=posts_budget,
                    )
                    self._merge_totals(totals, batch)

                channel_state_root[channel_id] = stored

            self._persist_sync_state(
                account_id=account_id,
                user_id=user_id,
                sync_state_root=sync_state_root,
                channel_state_root=channel_state_root,
            )

            if include_history_pass:
                sync_state_root, channel_state_root = self._run_history_pass(
                    transport=transport,
                    snapshot=snapshot,
                    account_id=account_id,
                    user_id=user_id,
                    sync_state_root=sync_state_root,
                    channel_state_root=channel_state_root,
                    channels=channels[: self._max_channels],
                    teams_by_id=teams_by_id,
                )
                self._persist_sync_state(
                    account_id=account_id,
                    user_id=user_id,
                    sync_state_root=sync_state_root,
                    channel_state_root=channel_state_root,
                )

            return {
                "account_username": snapshot.username,
                "server_url": snapshot.server_url,
                "synchronized": totals.synchronized,
                "created": totals.created,
                "updated": totals.updated,
                "unchanged": totals.unchanged,
                "jobs_enqueued": totals.jobs_enqueued,
            }
        finally:
            if owns_transport:
                transport.close()

    def _history_page_size(self) -> int:
        return min(self._initial_posts_per_channel, self._max_posts_per_run)

    def _persist_sync_state(
        self,
        account_id: UUID,
        user_id: UUID,
        sync_state_root: dict[str, Any],
        channel_state_root: dict[str, Any],
    ) -> None:
        account = self._account_store.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise MattermostConnectorError("mattermost account not found")
        updated_state = dict(sync_state_root)
        updated_state["channels"] = channel_state_root
        self._account_store.update_sync_state(account, updated_state)
        self._session.commit()

    def _merge_stored_channel_entry(
        self,
        stored: dict[str, Any],
        entry: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(stored)
        backfill = entry.get("history_backfill")
        if isinstance(backfill, dict):
            merged = set_history_backfill(merged, backfill)
        return merged

    def _run_history_pass(
        self,
        transport: MattermostTransport,
        snapshot: MattermostSyncSnapshot,
        account_id: UUID,
        user_id: UUID,
        sync_state_root: dict[str, Any],
        channel_state_root: dict[str, Any],
        channels: list[dict[str, Any]],
        teams_by_id: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        history_page_size = self._history_page_size()
        if history_page_size <= 0:
            return sync_state_root, channel_state_root

        channel_ids = [
            str(channel.get("id") or "").strip()
            for channel in channels
            if str(channel.get("id") or "").strip()
        ]
        if not channel_ids:
            return sync_state_root, channel_state_root

        channels_by_id = {
            str(channel.get("id") or "").strip(): channel
            for channel in channels
            if str(channel.get("id") or "").strip()
        }

        state = dict(sync_state_root)
        state["channels"] = channel_state_root
        for channel_id in channel_ids:
            stored = dict(channel_state_root.get(channel_id, {}))
            backfill = get_history_backfill(stored)
            reconciled = reconcile_active_scan(backfill, self._sync_days)
            if reconciled != backfill:
                stored = set_history_backfill(stored, reconciled)
                channel_state_root[channel_id] = stored

        state["channels"] = channel_state_root
        self._persist_sync_state(
            account_id=account_id,
            user_id=user_id,
            sync_state_root=state,
            channel_state_root=channel_state_root,
        )

        channel_id, plan, state = select_history_channel(
            state,
            channel_ids,
            self._sync_days,
        )
        if channel_id is None or plan is None or plan.scan is None:
            return state, dict(state.get("channels", {}))

        channel_state_root = dict(state.get("channels", {}))
        stored = dict(channel_state_root.get(channel_id, {}))
        if continue_active_scan(get_history_backfill(stored)) is None:
            started_backfill = start_active_history_range(
                get_history_backfill(stored),
                plan.scan.active_start_ms,
                plan.scan.active_end_ms,
                self._sync_days,
                before_post_id=plan.scan.active_before_post_id,
            )
            stored = set_history_backfill(stored, started_backfill)
            channel_state_root[channel_id] = stored
            state = set_channel_entry(state, channel_id, stored)
            self._persist_sync_state(
                account_id=account_id,
                user_id=user_id,
                sync_state_root=state,
                channel_state_root=channel_state_root,
            )

        stored = dict(channel_state_root.get(channel_id, {}))
        backfill = get_history_backfill(stored)
        active = continue_active_scan(backfill)
        if active is None:
            return state, channel_state_root

        channel = channels_by_id[channel_id]
        channel_context = self._build_channel_context(channel, teams_by_id)
        before_post_id = active.active_before_post_id

        if before_post_id is None:
            page = transport.get_posts_page(
                channel_id=channel_id,
                page=0,
                per_page=history_page_size,
            )
        else:
            page = transport.get_posts_before(
                channel_id=channel_id,
                before_post_id=before_post_id,
                per_page=history_page_size,
            )

        provider_posts = self._posts_from_page(page)
        oldest_provider_post = self._oldest_post(provider_posts)
        interval_complete = self._history_interval_complete(
            provider_posts=provider_posts,
            active_start_ms=active.active_start_ms,
            per_page=history_page_size,
        )

        in_window_posts = [
            post
            for post in provider_posts
            if active.active_start_ms <= int(post.get("create_at") or 0) < active.active_end_ms
        ]
        in_window_posts.sort(key=lambda item: int(item.get("create_at") or 0))

        oldest_in_window_processed: dict[str, Any] | None = None
        if in_window_posts:
            author_map = self._resolve_authors(transport, in_window_posts)
            for post in in_window_posts:
                self._upsert_post(
                    snapshot=snapshot,
                    channel_context=channel_context,
                    post=post,
                    author_map=author_map,
                )
                if oldest_in_window_processed is None or int(post.get("create_at") or 0) < int(
                    oldest_in_window_processed.get("create_at") or 0
                ):
                    oldest_in_window_processed = post
                self._session.commit()

        stored = dict(channel_state_root.get(channel_id, {}))
        backfill = get_history_backfill(stored)
        if oldest_in_window_processed is not None:
            oldest_id = str(oldest_in_window_processed.get("id") or "").strip()
            if oldest_id:
                backfill = persist_active_oldest_processed_post_id(backfill, oldest_id)

        if interval_complete:
            backfill = complete_active_history(backfill)
        elif oldest_provider_post is not None:
            oldest_id = str(oldest_provider_post.get("id") or "").strip()
            if oldest_id:
                backfill = persist_active_before_post_id(backfill, oldest_id)

        stored = set_history_backfill(stored, backfill)
        channel_state_root[channel_id] = stored
        state = set_channel_entry(state, channel_id, stored)
        state = set_last_history_channel_id(state, channel_id)
        return state, dict(state.get("channels", {}))

    def _posts_from_page(self, page: MattermostPostsPage) -> list[dict[str, Any]]:
        posts: list[dict[str, Any]] = []
        for post_id in page.order:
            post = page.posts.get(post_id)
            if isinstance(post, dict):
                posts.append(post)
        return posts

    def _oldest_post(self, posts: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not posts:
            return None
        return min(posts, key=lambda item: int(item.get("create_at") or 0))

    def _history_interval_complete(
        self,
        provider_posts: list[dict[str, Any]],
        active_start_ms: int,
        per_page: int,
    ) -> bool:
        if not provider_posts:
            return True
        if any(int(post.get("create_at") or 0) < active_start_ms for post in provider_posts):
            return True
        return len(provider_posts) < per_page

    def _discover_channels(
        self,
        transport: MattermostTransport,
        remote_user_id: str,
    ) -> list[dict[str, Any]]:
        try:
            channels = transport.list_my_channels()
        except MattermostEndpointNotFoundError:
            channels = self._discover_channels_via_teams(transport, remote_user_id)

        deduped: dict[str, dict[str, Any]] = {}
        for channel in channels:
            channel_id = str(channel.get("id") or "").strip()
            if channel_id:
                deduped[channel_id] = channel

        sorted_channels = sorted(
            deduped.values(),
            key=lambda item: int(item.get("last_post_at") or 0),
            reverse=True,
        )
        return sorted_channels

    def _discover_channels_via_teams(
        self,
        transport: MattermostTransport,
        remote_user_id: str,
    ) -> list[dict[str, Any]]:
        teams = transport.list_my_teams()
        discovered: dict[str, dict[str, Any]] = {}
        for team in teams:
            team_id = str(team.get("id") or "").strip()
            if not team_id:
                continue
            team_channels = transport.list_team_channels_for_user(team_id, remote_user_id)
            for channel in team_channels:
                channel_id = str(channel.get("id") or "").strip()
                if channel_id:
                    discovered[channel_id] = channel
        return list(discovered.values())

    def _build_teams_index(self, transport: MattermostTransport) -> dict[str, dict[str, Any]]:
        teams = transport.list_my_teams()
        index: dict[str, dict[str, Any]] = {}
        for team in teams:
            team_id = str(team.get("id") or "").strip()
            if team_id:
                index[team_id] = team
        return index

    def _build_channel_context(
        self,
        channel: dict[str, Any],
        teams_by_id: dict[str, dict[str, Any]],
    ) -> MattermostChannelContext:
        team_id = str(channel.get("team_id") or "").strip() or None
        team = teams_by_id.get(team_id) if team_id else None
        return MattermostChannelContext(
            channel_id=str(channel.get("id") or ""),
            channel_name=str(channel.get("name") or "").strip() or None,
            channel_display_name=str(channel.get("display_name") or "").strip() or None,
            channel_type=str(channel.get("type") or "").strip() or None,
            team_id=team_id,
            team_name=str(team.get("name") or "").strip() if team else None,
            team_display_name=str(team.get("display_name") or "").strip() if team else None,
        )

    def _sync_bootstrap(
        self,
        transport: MattermostTransport,
        snapshot: MattermostSyncSnapshot,
        channel_context: MattermostChannelContext,
        stored: dict[str, Any],
        cutoff_ms: int,
        posts_budget: int,
    ) -> tuple[int, dict[str, Any], _SyncTotals]:
        page = transport.get_posts_page(
            channel_id=channel_context.channel_id,
            page=0,
            per_page=self._initial_posts_per_channel,
        )
        posts = self._ordered_posts(page, cutoff_ms=cutoff_ms)
        totals, posts_budget, last_anchor = self._process_posts(
            transport=transport,
            snapshot=snapshot,
            channel_context=channel_context,
            posts=posts,
            posts_budget=posts_budget,
        )
        if last_anchor is not None:
            stored["last_processed_post_id"] = last_anchor["post_id"]
            stored["last_processed_create_at_ms"] = last_anchor["create_at_ms"]
        stored["bootstrap_complete"] = True
        return posts_budget, stored, totals

    def _sync_new_posts(
        self,
        transport: MattermostTransport,
        snapshot: MattermostSyncSnapshot,
        channel_context: MattermostChannelContext,
        stored: dict[str, Any],
        cutoff_ms: int,
        posts_budget: int,
    ) -> tuple[int, dict[str, Any], _SyncTotals]:
        anchor_id = str(stored.get("last_processed_post_id") or "").strip()
        if not anchor_id:
            return self._sync_bootstrap(
                transport=transport,
                snapshot=snapshot,
                channel_context=channel_context,
                stored=stored,
                cutoff_ms=cutoff_ms,
                posts_budget=posts_budget,
            )

        page = transport.get_posts_after(
            channel_id=channel_context.channel_id,
            after_post_id=anchor_id,
            per_page=min(posts_budget, self._initial_posts_per_channel),
        )
        posts = self._ordered_posts(page, cutoff_ms=cutoff_ms)
        totals, posts_budget, last_anchor = self._process_posts(
            transport=transport,
            snapshot=snapshot,
            channel_context=channel_context,
            posts=posts,
            posts_budget=posts_budget,
        )
        if last_anchor is not None:
            stored["last_processed_post_id"] = last_anchor["post_id"]
            stored["last_processed_create_at_ms"] = last_anchor["create_at_ms"]
        return posts_budget, stored, totals

    def _sync_edit_sweep(
        self,
        transport: MattermostTransport,
        snapshot: MattermostSyncSnapshot,
        channel_context: MattermostChannelContext,
        stored: dict[str, Any],
        cutoff_ms: int,
        posts_budget: int,
    ) -> tuple[int, dict[str, Any], _SyncTotals]:
        watermark_ms = stored.get("edit_sweep_watermark_ms")
        if watermark_ms is None:
            watermark_ms = cutoff_ms
        since_ms = int(watermark_ms) - self._overlap_seconds * 1000

        page = transport.get_posts_since(
            channel_id=channel_context.channel_id,
            since_ms=since_ms,
        )
        posts = self._ordered_posts(page, cutoff_ms=None)
        totals = _SyncTotals()
        if not posts:
            return posts_budget, stored, totals

        processed_all = True
        max_processed_update_ms: int | None = None

        author_map = self._resolve_authors(transport, posts)
        for post in posts:
            if posts_budget <= 0:
                processed_all = False
                break
            change = self._upsert_post(
                snapshot=snapshot,
                channel_context=channel_context,
                post=post,
                author_map=author_map,
            )
            totals.synchronized += 1
            if change == "created":
                totals.created += 1
                totals.jobs_enqueued += 1
            elif change == "updated":
                totals.updated += 1
                totals.jobs_enqueued += 1
            elif change == "metadata_updated":
                totals.updated += 1
            else:
                totals.unchanged += 1
            update_at_ms = int(post.get("update_at") or post.get("create_at") or 0)
            if max_processed_update_ms is None:
                max_processed_update_ms = update_at_ms
            else:
                max_processed_update_ms = max(max_processed_update_ms, update_at_ms)
            posts_budget -= 1
            self._session.commit()

        can_advance = (
            processed_all
            and not page.provider_saturated
            and max_processed_update_ms is not None
        )
        if can_advance:
            stored["edit_sweep_watermark_ms"] = max_processed_update_ms

        return posts_budget, stored, totals

    def _process_posts(
        self,
        transport: MattermostTransport,
        snapshot: MattermostSyncSnapshot,
        channel_context: MattermostChannelContext,
        posts: list[dict[str, Any]],
        posts_budget: int,
    ) -> tuple[_SyncTotals, int, dict[str, int] | None]:
        totals = _SyncTotals()
        last_anchor: dict[str, int] | None = None
        author_map = self._resolve_authors(transport, posts)

        for post in posts:
            if posts_budget <= 0:
                break
            change = self._upsert_post(
                snapshot=snapshot,
                channel_context=channel_context,
                post=post,
                author_map=author_map,
            )
            totals.synchronized += 1
            if change == "created":
                totals.created += 1
                totals.jobs_enqueued += 1
            elif change == "updated":
                totals.updated += 1
                totals.jobs_enqueued += 1
            elif change == "metadata_updated":
                totals.updated += 1
            else:
                totals.unchanged += 1

            post_id = str(post.get("id") or "").strip()
            create_at_ms = int(post.get("create_at") or 0)
            if post_id:
                last_anchor = {"post_id": post_id, "create_at_ms": create_at_ms}
            posts_budget -= 1
            self._session.commit()

        return totals, posts_budget, last_anchor

    def _ordered_posts(
        self,
        page: Any,
        cutoff_ms: int | None,
    ) -> list[dict[str, Any]]:
        posts: list[dict[str, Any]] = []
        for post_id in page.order:
            post = page.posts.get(post_id)
            if not isinstance(post, dict):
                continue
            create_at_ms = int(post.get("create_at") or 0)
            if cutoff_ms is not None and create_at_ms < cutoff_ms:
                continue
            posts.append(post)
        posts.sort(key=lambda item: int(item.get("create_at") or 0))
        return posts

    def _resolve_authors(
        self,
        transport: MattermostTransport,
        posts: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        user_ids: list[str] = []
        seen: set[str] = set()
        for post in posts:
            user_id = str(post.get("user_id") or "").strip()
            if user_id and user_id not in seen:
                seen.add(user_id)
                user_ids.append(user_id)
        users = transport.get_users_by_ids(user_ids)
        return {
            str(user.get("id") or ""): user
            for user in users
            if str(user.get("id") or "").strip()
        }

    def _upsert_post(
        self,
        snapshot: MattermostSyncSnapshot,
        channel_context: MattermostChannelContext,
        post: dict[str, Any],
        author_map: dict[str, dict[str, Any]],
    ) -> str:
        author_id = str(post.get("user_id") or "").strip()
        author = author_map.get(author_id)
        result = self._materializer.upsert_post(
            user_id=snapshot.user_id,
            normalized_server_url=snapshot.normalized_server_url,
            account_id=snapshot.account_id,
            channel=channel_context,
            post=post,
            author=author,
            skip_hidden=True,
        )
        return result.change

    def _find_existing(self, user_id: UUID, external_id: str) -> Object | None:
        return self._materializer.find_existing(user_id, external_id)

    def _apply_normalized(self, obj: Object, normalized: dict[str, Any]) -> None:
        self._materializer._apply_normalized(obj, normalized)

    def _merge_totals(self, totals: _SyncTotals, batch: _SyncTotals) -> None:
        totals.synchronized += batch.synchronized
        totals.created += batch.created
        totals.updated += batch.updated
        totals.unchanged += batch.unchanged
        totals.jobs_enqueued += batch.jobs_enqueued

    def _should_close_transport(self, transport: MattermostTransport) -> bool:
        if self._transport_factory is not None:
            return False
        return isinstance(transport, MattermostHttpTransport)

    def _open_transport(self, snapshot: MattermostSyncSnapshot) -> MattermostTransport:
        if self._transport_factory is not None:
            return self._transport_factory(snapshot)
        return MattermostHttpTransport(
            base_url=snapshot.normalized_server_url,
            access_token=snapshot.access_token,
        )


def build_mattermost_sync_service(
    session: Session,
    credential_key: str,
    sync_days: int,
    max_channels: int,
    initial_posts_per_channel: int,
    max_posts_per_run: int,
    overlap_seconds: int,
    transport_factory: Callable[[MattermostSyncSnapshot], MattermostTransport] | None = None,
    now_factory: Callable[[], datetime] | None = None,
) -> MattermostSyncService:
    account_store = MattermostAccountStore(
        session,
        MattermostAccountStore.build_encryption(credential_key),
    )
    job_queue = JobQueueService(session)
    return MattermostSyncService(
        session=session,
        account_store=account_store,
        job_queue=job_queue,
        sync_days=sync_days,
        max_channels=max_channels,
        initial_posts_per_channel=initial_posts_per_channel,
        max_posts_per_run=max_posts_per_run,
        overlap_seconds=overlap_seconds,
        transport_factory=transport_factory,
        now_factory=now_factory,
    )
