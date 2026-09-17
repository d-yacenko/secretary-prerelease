# Current task — Telegram Depth A4.4 accepted / STOP

## Status

- Telegram A4.1: ACCEPTED through `43944ca47b407889f87eb891b898a1c55097f7f0`.
- Telegram A4.2: ACCEPTED through `5de67b6a6cf746c9af911ddfcc671833d1d3d62e`.
- Telegram A4.3: ACCEPTED through `6e6120d38cc3b1e3b677b1ca16cf97a002ea91d3`.
- Telegram A4.4: **ACCEPTED** at exact SHA `153f663a1ca0f787ec0be2cbb90d28758e539d39` on `review/telegram-depth-a4-folder-scope`.

## A4.4 accepted result

A4.4 adds recurring Telegram MTProto scope reconciliation and bounded history synchronization by extending the existing Postgres-backed source-sync scheduler/worker/queue.

Accepted contract:

- recurring job type `sync_telegram_mtproto`;
- one recurring Job per connected `TelegramMtprotoAccount`, not per peer;
- existing `SourceSyncScheduler`, `JobQueueService`, recurring source-sync lane and worker only;
- deployment interval `300` seconds through `source_sync_telegram_mtproto_interval_seconds`;
- generic `UserSourcePreference` / Telegram `history_days` exposure remains deferred;
- every recurring run validates account ownership and reconciles folder/mute scope before history work;
- failed/truncated/unavailable reconciliation performs zero peer history sync in that run;
- only current `scope_active=true` peers for the payload account are considered;
- max `10` peer attempts per run;
- round-robin progress uses safe Job payload key `telegram_peer_cursor`;
- peer-local stale/unavailable/reference/scope-race failures do not block later peers;
- provider/account-wide failures stop the run;
- Telegram provider Retry-After is propagated into recurring retry timing;
- Job errors are sanitized and do not expose Telegram session/provider-reference/provider payload values;
- existing `TelegramMtprotoHistoryService.sync_scope_peer()` and A3/A4 cursors/materializer are reused and not reset;
- no migration was added; review Alembic head remains `0046`.

Executor reported:

- `alembic upgrade head`: PASS;
- Telegram A1–A4.4 suite: `137 passed`;
- A4.4 focused suite: `12 passed`;
- scheduler/queue/worker/source-preference suites: `89 passed`;
- Ruff: PASS;
- `git diff --check`: PASS;
- clean worktree.

Architect independently reviewed exact commit ancestry/diff and the scheduler/orchestrator/worker/finalization paths before acceptance.

## Current authorization

**No implementation work is currently authorized. Executor must STOP.**

Do not begin A4.5 or any other Telegram phase until this file is replaced by a new explicit Architect task.

Do not independently start:

- UI/Flutter changes;
- generic Telegram source-preference/history-days work;
- legacy Bot API removal;
- merge of A3/A4 code to `main`;
- production deployment or runtime probing;
- migration deployment planning/execution;
- SSH or production Compose;
- provider-side Telegram mutations/sends;
- cleanup/refactor not explicitly authorized.

## Branch/state boundary

- Accepted review implementation SHA: `153f663a1ca0f787ec0be2cbb90d28758e539d39`.
- Review Alembic head: `0046`.
- Production application/runtime remains `5cce4b57b14e0052a038acae1354a2821a2bb77b`.
- Production Alembic remains `0041 / 0041`.
- A3/A4 Telegram code is not production deployed.
- Eventual Telegram production rollout remains migration-bearing and requires a separate explicit Architect-authorized migration deployment plan.

## Executor instruction

If you are the Executor and reached this file after the A4.4 acceptance bookkeeping commits: report the exact current review HEAD if asked, make no code changes, and STOP.
