# REL1D-HG2 provider repair / refetch capability audit

Source review of `main` at authorization `9ffd0e0909614cf4ee20e288362af713096c8176`.
No provider call, production database access, mutation, deployment, or schema change was performed for this document.

Telegram Business remains a separate architecture and parser decision. It is not part of this repair plan. `TelegramObjectMaterializer.upsert_business_message` and `normalize_telegram_business_message` are a different external-id space from MTProto and are not a repair path for MTProto rows.

## 1. Scope and invariants

- This document is a source review only.
- No provider or model API was called.
- No production database was read or written.
- No product data was mutated.
- No deployment, client install, schema change, or migration was made.
- Production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`.
- Alembic remains `0054 / 0054`.
- Accepted HG2 source contracts are not rolled out. `75e006b93b71ca9088e8ce725907768cf0b8f874` (HG2B1), `9cc6b696d4cc489e0ca248eafeb4560963ab197d` (HG2B2), and `efcf5c48771e1d1bf6bb352f6812822033643c35` (HG2B3) are not ancestors of the production SHA. `92aef7e6c9fb2e5acd6afc7056b26ea67ea99d07` (Teams `sender_kind`) is an ancestor of that production SHA.

Accepted source contracts this audit assumes a later repair would run after rollout:

| Contract | SHA | What a refetch must preserve |
| --- | --- | --- |
| HG2A / HG2A.1 | `2cb5a2fe583333da5dfd1fd13d40be404b6fecae`, `260021fbe5526312fef82afd7f6fc0decea52043` | Role-import scan ceiling. Not a provider refetch path. |
| HG2B1 | `75e006b93b71ca9088e8ce725907768cf0b8f874` | Mattermost `author_display_name` from profile display or first+last only. |
| HG2B2 | `9cc6b696d4cc489e0ca248eafeb4560963ab197d` | Gmail/Yandex `to_participants` / `cc_participants` when a display name exists. |
| HG2B3 | `efcf5c48771e1d1bf6bb352f6812822033643c35` | MTProto `sender_display_name` / `sender_kind` from the cached Telethon sender. |
| HG2B3.1 / HG2B3.2R | `b3744c9a6a02171cfbe30466df49172c73262ce9`, `7dc1dcc0694ec878c1af53acf6c0107e609b467d` | Test-only. No runtime repair behavior. |

## 2. Provider capability matrix

### Mattermost — `REQUIRES_DEDICATED_BOUNDED_REPAIR`

| Question | Source fact |
| --- | --- |
| Entrypoints | `MattermostSyncService.sync_account` in `backend/app/connectors/mattermost/sync.py`. Worker `handle_sync_mattermost` calls it with `include_history_pass=True` (`backend/app/jobs/source_sync_handlers.py`). Live path: `_sync_bootstrap` or `_sync_new_posts`, then `_sync_edit_sweep`. History path: `_run_history_pass`. |
| Can it revisit stored posts? | Yes, when a post is fetched again. `MattermostObjectMaterializer.upsert_post` finds `provider=mattermost`, `kind=chat_message`, same `external_id` and applies the new normalization (`materialize.py`). `test_reprocessing_enriched_profile_updates_the_same_object` in `backend/tests/test_phase_27b_mattermost.py` shows the same Object gains `author_display_name`. |
| Bounds | Live cutoff is `sync_days`, clamped by `MAX_SYNC_DAYS = 90` (`constants.py`; service constructor). Default setting `mattermost_sync_days = 14` (`config.py`). User preference is clamped by `clamp_history_days` to the deployment min/max (`source_sync_preference_service.py`; config default max 90). Per run: `max_channels` (default 50, cap 100), `max_posts_per_run` (default 500, cap 1000), `initial_posts_per_channel` (default 100, cap 200). History page size is `min(initial_posts_per_channel, max_posts_per_run)`. One history channel per `_run_history_pass` via `select_history_channel`. Edit sweep uses `get_posts_since` from `edit_sweep_watermark_ms` minus overlap (default 300s, cap 3600s). `MATTERMOST_PROVIDER_SINCE_LIMIT = 1000`. |
| Fetch primitives | `MattermostTransport.get_posts_page`, `get_posts_after`, `get_posts_before`, `get_posts_since`, `get_users_by_ids` (`transport.py`). There is no single-post fetch on that protocol. |
| HG2B1 normalizer | `normalize_mattermost_post` stores `author_display_name` only from `_author_human_display` (`normalize.py`). |
| Object identity | `build_external_id` is `{normalized_server_url}\|{post_id}`. |
| Same Object or duplicate? | Same Object. Integrity conflict reloads that external id. Hidden Objects are left unchanged: `passive_sync_should_skip_existing` (`object_visibility.py`). |
| Sync state mutated? | Yes. Channel `last_processed_post_id`, `bootstrap_complete`, `edit_sweep_watermark_ms`, and per-channel `history_backfill` (`covered_start_ms`, `active_before_post_id`, `last_history_channel_id`) are persisted with `update_sync_state` and `commit`. |
| Targeted repair without moving ordinary state? | No. `plan_history_active_scan` returns no scan once `covered_start_ms` already reaches the desired window, so a completed history pass does not walk those posts again. Resetting coverage to force a walk would itself move ordinary history state. |
| Evidence | `sync.py` `_run_history_pass`, `_sync_edit_sweep`; `mattermost_history_state.py` `plan_history_active_scan`, `complete_active_history`; `materialize.py` `find_existing`, `_apply_existing`. |

### Gmail — `REQUIRES_DEDICATED_BOUNDED_REPAIR`

Rows whose stored provenance cannot name both the Gmail message id and the Google account are `NOT_REPAIRABLE_FROM_CURRENT_PROVENANCE`. Do not reconstruct a missing `source_account_email`.

| Question | Source fact |
| --- | --- |
| Entrypoints | `GmailSyncService.sync_account` (`gmail_sync.py`). Worker `handle_sync_google_gmail` sets `include_history_pass=True`. Live: `_run_live_pass`. History: `_run_history_pass`. |
| Can it revisit stored mail? | The list can see an id again. `_materialize_message_ids` then skips every id already stored for that user (`provider=gmail`, `kind=email`) and does not call `get_message`. `updated` stays 0 on that path. `test_known_backfill_messages_skip_get_message` in `backend/tests/test_phase_28c_b2b1_gmail_history_runtime.py`. |
| Bounds | `sync_days` comes from `effective_history_days_for_source` (default `gmail_sync_days = 30`, preference clamp default max 90). `GmailSyncService` itself does not apply `MAX_SYNC_DAYS`. Page size `effective_limit` default 50, cap `MAX_SYNC_LIMIT = 100`. History is one `list_message_ids_page` per run, cursor `next_page_token`, window from `plan_history_active_window`. List query is `build_gmail_list_query`: `after:` / optional `before:` plus exclusions `-in:spam -in:trash -category:promotions -category:social -category:forums`. A completed scanned interval is not listed again. |
| Fetch primitives | `GmailTransport.list_message_ids`, `list_message_ids_page`, `get_message` (`gmail_transport.py`). `get_message` is the primitive a later repair would need. The current sync path does not call it for a known id. |
| HG2B2 normalizer | `normalize_gmail_message` adds `to_participants` / `cc_participants` only when `_named_participants` returns a non-empty list. Bare `recipients` / `cc` stay on `_parse_addresses`. |
| Object identity | `external_id` is the Gmail API message `id`. `source_account_email` is copied from `GoogleAccount.email` at sync time, not from the message. `GoogleAccount` is unique on `(user_id, email)`, so one user may have more than one account (`models.py`). |
| Same Object or duplicate? | Known ids are skipped, so the existing Object is not updated and a second Object is not inserted. There is no Gmail update/upsert branch in `_materialize_message_ids`. |
| Sync state mutated? | History pass writes `history_backfill` (`scanned_start` / `scanned_end` or `next_page_token`) through `update_gmail_sync_state`. Live pass does not advance that backfill. |
| Targeted repair without moving ordinary state? | No. Reusing `_run_history_pass` both skips known messages and advances the scanned window. |
| Provenance split | Refetchable only when the stored row has a Gmail message id (`external_id` or metadata `message_id`) and `source_account_email` that still matches a connected `GoogleAccount` for that user. Missing `source_account_email` does not identify which account token `get_message(..., user_id="me")` must use. Missing message id is not refetchable. |

### Yandex Mail — `REQUIRES_DEDICATED_BOUNDED_REPAIR`

Rows without a stable `INBOX` UID plus the UIDVALIDITY that still belongs to that mailbox are `NOT_REPAIRABLE_FROM_CURRENT_PROVENANCE`.

| Question | Source fact |
| --- | --- |
| Entrypoints | `YandexMailSyncService.sync_account` (`mail_sync.py`). Worker `handle_sync_yandex_mail` sets `include_history_pass=True`. Live: `_run_live_pass`. History: `_run_history_pass`. Folder is only `DEFAULT_MAIL_FOLDER` (`INBOX`). |
| Can it revisit stored mail? | `_materialize_uids` skips any `external_id` already stored (`provider=yandex_mail`, `kind=email`) and does not call `fetch_message`. `test_known_historical_uid_skips_fetch` in `backend/tests/test_phase_28c_b2c1b_yandex_mail_history_runtime.py`. |
| Bounds | `sync_days` clamped by `MAX_SYNC_DAYS = 90` (default setting 30). Page `effective_limit` default 50, cap 100. History search is `search_uids_history_page` with `SINCE` / `BEFORE` and `UID 1:{uid_upper}` (`imap_transport.py`). Cursor is `active_before_uid`, initially `MAX_IMAP_UID + 1`. One history page per run. `plan_history_active_scan` does not rescan an already covered date interval. |
| Fetch primitives | `ImapTransport.fetch_message(folder, uid)` after `select_folder`. History discovery is `search_uids_history_page`. No separate repair entrypoint exists. |
| HG2B2 normalizer | `normalize_imap_message` adds named `to_participants` / `cc_participants` the same way as Gmail, and stores `folder`, `imap_uid`, `imap_uidvalidity`. |
| Object identity | `build_external_id` is `{folder.lower()}:{uidvalidity}:{uid}`. `source_account_email` is `snapshot.email` at sync time. |
| Same Object or duplicate? | Known external ids are skipped. No update branch. A UIDVALIDITY change makes the old external id a different identity; `_clear_history_on_mailbox_uidvalidity_change` clears history state only (`test_uidvalidity_change_clears_history_and_uses_initial_live`). It does not rewrite old Objects. |
| Sync state mutated? | Live pass writes `inbox_uidvalidity` and `inbox_last_uid`. History pass writes `history_backfill` and does not move `inbox_last_uid` (`test_history_does_not_change_forward_last_uid`). |
| Targeted repair without moving ordinary state? | No. The history pass skips known UIDs and persists the history cursor. Fetching a UID under a new UIDVALIDITY is not the same message. |
| Exact repair condition | A later repair can be exact only for stored `folder=INBOX`, integer `imap_uid`, and `imap_uidvalidity` equal to the UIDVALIDITY `select_folder` returns now, plus `source_account_email` selecting that account. Other folders, a UIDVALIDITY mismatch, or a missing UID are not safely refetchable from current source. |

### Microsoft Teams — `REQUIRES_DEDICATED_BOUNDED_REPAIR`

Current sync cannot target old rows. Rows that lack `chat_id`, `message_id`, and the account identity needed to call Graph are `NOT_REPAIRABLE_FROM_CURRENT_PROVENANCE`. Missing `sender_kind` stays ambiguous. It must not be mapped to `user`.

| Question | Source fact |
| --- | --- |
| Entrypoints | `TeamsSyncService.sync_account` → `_sync_with_transport` (`teams/sync.py`). Worker `handle_sync_teams` has no history-pass flag. A separate single-message path is `process_graph_notification` (`notifications.py`). |
| Can it revisit stored messages? | Only inside the overlap above the per-chat watermark. Floor is `last_created_at` minus overlap, or `sync_start_at` when no watermark exists. Messages older than that floor are skipped. `_can_skip_chat_message_list` skips the chat entirely when `lastMessagePreview.createdDateTime <= watermark`. There is no history/backfill planner. `deployment_default_history_days` for Teams is `source_sync_user_min_history_days`; `TeamsSyncService` does not take `history_days`. |
| Bounds | Overlap default 300s, cap 3600s. Chat list: default 20 pages, cap 50. Messages: `$top=50`, default 20 pages per chat, cap 50 (`transport.py` `list_chat_messages`, `constants.py`). Hitting the page cap raises `TeamsSyncError` and must not be treated as a completed historical scan. |
| Fetch primitives | Sync uses `list_chats` and `list_chat_messages`. `TeamsTransport.get_chat_message` exists and is used by `process_graph_notification`, not by the history-less sync walk. |
| Current normalizer | `sender_identity_from_message` returns kind `user` or `application` only from the live Graph `from` object. `normalize_teams_message` stores that `sender_kind` (it may be null). Commit `92aef7e6c9fb2e5acd6afc7056b26ea67ea99d07` is what added the kind. Before it, user and application both returned only id and display name. A stored row with no `sender_kind` therefore matches both shapes. Current code does not fill kind when the key is absent. |
| Object identity | `build_external_id(tenant_id, microsoft_user_id, chat_id, message_id)`. |
| Same Object or duplicate? | `TeamsObjectMaterializer.upsert_message` updates the existing Object. Metadata is replaced, with `quoted_message_id` merged. If title and body are unchanged, `_apply_existing` still writes metadata and then returns change `unchanged`. Hidden Objects are skipped. |
| Sync state mutated? | Sync writes per-chat `last_created_at`, `chat_type`, and `display_title`. Notification may also write `chats` state when the chat type was not cached. |
| Targeted repair without moving ordinary state? | The sync walk cannot select an old message without also moving watermarks if a newer message is processed. `get_chat_message` plus `upsert_message` is the smallest existing pair a future repair can reuse. That pair is not exposed as a repair entrypoint. Calling `process_graph_notification` is not that repair: it depends on a Graph notification payload and can write chat sync state. |
| Classification | `REQUIRES_DEDICATED_BOUNDED_REPAIR` for rows that already store account, tenant, Teams user id, `chat_id`, and `message_id`. Otherwise `NOT_REPAIRABLE_FROM_CURRENT_PROVENANCE`. |

### Telegram MTProto — `REQUIRES_DEDICATED_BOUNDED_REPAIR`

| Question | Source fact |
| --- | --- |
| Entrypoints | Ordinary ingest: `TelegramMtprotoHistoryService.sync_scope_peer` / `sync_group` → `_sync_selection` (`telegram_mtproto_history_service.py`). Revisit path: `reconcile_recent_messages`. Recurring job `TelegramMtprotoRecurringSyncService` calls `sync_scope_peer` and then `reconcile_recent_messages` on the same job `payload` (`telegram_mtproto_recurring_sync_service.py`). |
| Can it revisit stored messages? | Yes. Reconcile selects existing MTProto Objects for active scope peers (`transport=mtproto`, same `account_id` and `peer_id`, `deleted_at is None`) and calls `fetch_message` for a positive integer `message_id`. |
| Bounds | Per call: `TELEGRAM_MTPROTO_RECONCILE_MAX_LOOKUPS = 20`, `TELEGRAM_MTPROTO_RECONCILE_MAX_PER_PEER = 5`, candidate query `TELEGRAM_MTPROTO_RECONCILE_SCAN_LIMIT = 100`, head window 5. Peers rotate through `telegram_reconcile_peer_rotation`. Modes alternate `head` and `sweep`. Sweep cursor walks older `occurred_at` / `id`. This is not a 90-day window. `_normalize_entry` is called with cutoff `datetime.min`, so the history cutoff does not drop the refetched row. Ordinary `_sync_selection` is separate and uses `TELEGRAM_MTPROTO_HISTORY_MAX_MESSAGES_PER_RUN = 200` plus selection history cursors. |
| Fetch primitive | `TelethonMtprotoTransport.fetch_message` → `client.get_messages(input_peer, ids=message_id)`. Sender fields come from the cached message sender (`_history_entry_from_message`). Reconcile does not call `get_sender` or `get_entity`. |
| HG2B3 flow | Reconcile copies `sender_display_name` and `sender_kind` onto `TelegramMtprotoHistoryEntry`. `_normalize_entry` stores them only when present and when kind is `user`, `bot`, `channel`, or `chat`. `test_reconcile_reconstruction_keeps_sender_fields` and `test_reprocessing_the_same_message_adds_sender_identity` in `backend/tests/test_rel1d_hg2b3_mtproto_sender.py`. |
| Object identity | `mtproto\|{account.id}\|{peer_id}\|{message_id}`. |
| Same Object or duplicate? | `upsert_mtproto_message` updates the same external id. Metadata-only change returns `metadata_updated`. A provider miss (`fetch_message` returns `None`) can `tombstone_object` the existing Object. Empty text or a service message is left in place (`continue` before upsert). Hidden Objects are not updated. |
| Sync state mutated? | Reconcile writes only the passed `payload` keys `telegram_reconcile_peer_cursors`, `telegram_reconcile_peer_heads`, `telegram_reconcile_peer_modes`, and `telegram_reconcile_peer_rotation`. It does not call `_persist_history_cutoff`. The recurring caller uses that same payload for `telegram_peer_cursor` and embedding catch-up. |
| Suitable as-is? | No. The ordinary recurring call shares payload with live peer rotation, caps a repair at 20 lookups, and can tombstone a message the provider does not return. A later repair needs an isolated payload and an explicit decision to allow or suppress tombstones. The reusable primitives are `fetch_message`, `_normalize_entry`, and `upsert_mtproto_message`. |

## 3. Answers required by the task

### Mattermost

Existing history/backfill can enrich the same Object with HG2B1 fields only for posts it actually fetches again. `upsert_post` is safe for that identity. Ordinary history state is advanced on every history page and, once `covered_start_ms` covers the desired window, the planner will not revisit those posts. Edit sweep revisits only the overlap behind `edit_sweep_watermark_ms`, not the stored legacy set. Direct reuse of `sync_account(..., include_history_pass=True)` is unsuitable for a one-off controlled repair.

### Gmail

Stored Gmail message id plus `source_account_email` is enough provenance to call `get_message` on that account later. The current history/backfill path does not do that for known ids, and it does change `history_backfill`. Rows missing `source_account_email`, or missing a message id, cannot be repaired from current provenance. A missing `source_account_email` must not be reconstructed.

### Yandex Mail

Stored repair identity is `INBOX` + `imap_uid` + `imap_uidvalidity`, with `source_account_email` selecting the account. `fetch_message` can read that UID. The current history path skips known UIDs and writes `history_backfill`. Live sync separately writes the forward UID checkpoint. UIDVALIDITY must still match; a changed UIDVALIDITY does not preserve the old UID as the same message. No other refetch path is exposed. Non-INBOX folders are not synced by `YandexMailSyncService`.

### Teams

`TeamsSyncService` is forward/overlap sync. It has no bounded historical refetch of pre-`92aef7e6c9fb2e5acd6afc7056b26ea67ea99d07` rows. Missing legacy `sender_kind` stays ambiguous and must not be treated as `user`. The smallest primitive a future dedicated repair would reuse is `TeamsTransport.get_chat_message` followed by `TeamsObjectMaterializer.upsert_message`, limited to rows that already store `chat_id`, `message_id`, and the account/tenant/user identity. This audit does not implement that path.

### Telegram MTProto

`reconcile_recent_messages` loads at most 100 candidate Objects per active peer, then performs at most 20 `fetch_message` calls per invocation and at most 5 per peer. Peer order rotates. Cursors live in the job payload, not in `history_cutoff_at`. The fetched message is normalized with HG2B3 sender fields and upserted onto `mtproto|{account}|{peer}|{message}`. A missing provider message can tombstone the Object. Because the recurring job mixes this with live sync payload, it is not suitable as-is for an isolated repair. It needs a dedicated wrapper and isolated cursor state. This audit did not run reconcile.

## 4. Proposed repair sequence — design only

Stop and review after each provider. Do not run one cross-provider batch.

Materializers that update an Object overwrite `metadata_` in place. Gmail and Yandex current sync never update an existing Object. None of these paths write a prior-version row. A general database rollback of a committed repair is `UNPROVEN FROM CURRENT SOURCE`. The practical stop control is: one committed batch, then compare counts, and do not start the next provider until that review.

Preflight counts below are the counts a later authorized repair must compute before mutation. This audit did not query them.

### 1. Telegram MTProto

- Prerequisite source SHA: `efcf5c48771e1d1bf6bb352f6812822033643c35` must be the runtime that performs the refetch.
- Preflight: MTProto Objects with `transport=mtproto`, active scope peer, positive `message_id`, and missing `sender_display_name` or `sender_kind`; separately, hidden or already tombstoned rows.
- Bound: `TBD — dedicated repair required`. Existing per-call caps to preserve if the isolated wrapper reuses reconcile are 20 lookups, 5 per peer, 100-row candidate read. Tombstone-on-miss must be an explicit authorized choice, not an accidental reuse of the recurring job.
- Stop: provider unavailable, authorization invalid, tombstone count above the preflight allowance, or payload cursors shared with the live recurring job.
- Post-run: count of Objects that gained a closed `sender_kind`; count tombstoned; count still missing kind. Confirm `history_cutoff_at` and `history_latest_message_id` did not move.
- Rollback: in-place metadata replace only. Previous metadata is not retained by `TelegramObjectMaterializer`.

### 2. Mattermost

- Prerequisite source SHA: `75e006b93b71ca9088e8ce725907768cf0b8f874`.
- Preflight: Mattermost `chat_message` Objects missing `author_display_name` while `author_user_id` is present; Objects without `post_id` / channel / server identity.
- Bound: `TBD — dedicated repair required`. Do not call `sync_account` history mode. A future pager must not write `history_backfill` or `edit_sweep_watermark_ms`. Existing caps it must not exceed: 200 posts per channel page, 1000 posts per run, 100 channels, 90-day window unless a later task explicitly authorizes a wider window. Posts older than the covered history window are outside `plan_history_active_scan`.
- Stop: transport error, hidden-row skip count unexplained, or any write to Mattermost sync state.
- Post-run: same-Object updates with `author_display_name` set, Objects still missing it, duplicate external-id count unchanged.
- Rollback: in-place metadata replace only. `MattermostObjectMaterializer` does not keep the previous metadata.

### 3. Teams

- Prerequisite source SHA: `92aef7e6c9fb2e5acd6afc7056b26ea67ea99d07` for kind recording. It is already an ancestor of production `bc69c6fa5c0735db9509d12dd5f77e6285e45901`. Repair still requires a dedicated fetcher that does not exist.
- Preflight: Teams Objects with missing `sender_kind`, split by whether `chat_id`, `message_id`, `account_id`, `tenant_id`, and `teams_user_id` are all present.
- Bound: `TBD — dedicated repair required`. Current overlap sync is not a repair bound. The future call is one `get_chat_message` per selected row. Do not advance `last_created_at`.
- Stop: any row updated by a heuristic kind, Graph throttle (`TeamsRateLimitedError`), or a watermark change.
- Post-run: count of rows that gained `sender_kind` in `user|application`; count still missing kind; count skipped for missing provenance. Missing kind remains unresolved, not `user`.
- Rollback: in-place metadata replace. The change label may stay `unchanged` when only metadata differs (`TeamsObjectMaterializer._apply_existing`). Verify by metadata, not by that label. Previous metadata is not retained.

### 4. Gmail

- Prerequisite source SHA: `9cc6b696d4cc489e0ca248eafeb4560963ab197d`.
- Preflight: Gmail Objects missing `to_participants` and `cc_participants`, split into (message id and `source_account_email` present) versus provenance missing. Named participants are omitted when no display name exists, so absence after a successful refetch can be legitimate.
- Bound: `TBD — dedicated repair required`. Do not use `_run_history_pass`. Existing list cap is 100 ids per page and is the wrong primitive because known ids are skipped. A future repair would call `get_message` per selected id and needs an update path the current materializer does not have.
- Stop: account email mismatch, attempt to invent `source_account_email`, or any write to `history_backfill`.
- Post-run: Objects that gained a non-empty named participant list; Objects refetched and still without one; Objects left untouched for missing provenance. Created-Object count for those external ids must stay 0.
- Rollback: current sync inserts only. An update path is not in source, so its rollback is `UNPROVEN FROM CURRENT SOURCE` until that path exists. Do not delete Objects as a rollback.

### 5. Yandex Mail

- Prerequisite source SHA: `9cc6b696d4cc489e0ca248eafeb4560963ab197d`.
- Preflight: `yandex_mail` Objects missing named participant lists, split by complete `INBOX` + UID + UIDVALIDITY + `source_account_email`, versus incomplete provenance. Compare stored UIDVALIDITY to the live mailbox only inside a later authorized run; this audit did not.
- Bound: `TBD — dedicated repair required`. Do not use `_run_history_pass`. Existing history page cap is 100 UIDs and skips known ids.
- Stop: UIDVALIDITY mismatch, non-INBOX folder, history-cursor write, or forward `inbox_last_uid` write.
- Post-run: same counts as Gmail, plus Objects skipped because UIDVALIDITY changed.
- Rollback: same as Gmail. Current code does not update an existing Yandex Object.

## 5. Release boundary

This audit does not authorize:

- selecting or moving a release SHA to production;
- backend rollout;
- client rollout;
- provider repair or refetch;
- backfill;
- reconcile;
- Telegram Business parsing;
- human REL1D acceptance.

A later Architect action selects one accepted source release SHA, and separately authorizes rollout and each data-repair slice.
