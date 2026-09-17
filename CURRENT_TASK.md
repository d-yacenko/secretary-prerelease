# Current task — Telegram Depth A4.4 recurring scope + history sync

## Status

- Telegram A4.1: ACCEPTED through `43944ca47b407889f87eb891b898a1c55097f7f0`.
- Telegram A4.2: ACCEPTED through `5de67b6a6cf746c9af911ddfcc671833d1d3d62e`.
- Telegram A4.3: **ACCEPTED** through final SHA `6e6120d38cc3b1e3b677b1ca16cf97a002ea91d3` on `review/telegram-depth-a4-folder-scope`.
- A4.3 acceptance includes the A4.3R retained-history correction `84efe88d31e10acd6852acf59a85636834582026`, A4.3T `d9007c2d5a717d26428df8056b3d6d2734fd99dc`, and A4.3U final test commit `6e6120d...`.
- The previously requested "two MTProto accounts for the same Secretary user" regression is not a blocker: the current schema enforces `uq_telegram_mtproto_accounts_user_id`, so that state is structurally impossible. The canonical visibility predicate nevertheless compares exact `account_id`, `peer_id`, and same-user ownership.
- Telegram A4.4 — ACTIVE / IMPLEMENTATION AUTHORIZED.

A4.4 adds automatic recurring Telegram MTProto scope reconciliation and bounded history synchronization by extending the **existing Postgres-backed source-sync scheduler/worker/queue**. Do not create a new scheduler service, queue, worker, broker, or microservice.

## Fixed branch and baseline

- Repository: `d-yacenko/secretary-prerelease`.
- Work only in existing branch/worktree `review/telegram-depth-a4-folder-scope`.
- Fetch and fast-forward only to current `origin/review/telegram-depth-a4-folder-scope` after Architect bookkeeping.
- Preserve all accepted/candidate ancestry through exact accepted A4.3 SHA `6e6120d38cc3b1e3b677b1ca16cf97a002ea91d3`.
- Do not reset, rebase, squash, cherry-pick, or rewrite accepted history.
- Alembic head remains `0046`; **A4.4 requires no schema migration**.

## Architectural objective

Use the existing:

- `SourceSyncScheduler`;
- `JobQueueService`;
- recurring source-sync worker lane;
- `TelegramMtprotoScopeService.reconcile_scope()`;
- `TelegramMtprotoHistoryService.sync_scope_peer()`;
- durable `TelegramMtprotoChatSelection.scope_active` and history cursors.

A recurring Telegram account run must perform, in this order:

1. validate that the recurring job belongs to the current Secretary user/account;
2. reconcile the current Telegram folder scope;
3. if reconciliation succeeds completely, select a bounded batch of **currently `scope_active=true`** peers;
4. sync those peers using the existing A3/A4.2 history engine;
5. persist fair round-robin progress in the existing recurring Job payload;
6. let the existing recurring-job finalization re-arm the account job.

If reconciliation fails closed, **no peer history sync may occur in that run**.

## Job identity and worker integration

Add exactly one recurring job type for MTProto account synchronization, for example:

`sync_telegram_mtproto`

Use one recurring job per connected `TelegramMtprotoAccount`, not one recurring job per peer.

The Telegram job must join the existing `RECURRING_SOURCE_JOB_TYPES` and therefore the existing source-sync worker lane. Register its handler in the existing handler map.

Do not introduce Celery/Redis/Rabbit/Kafka, a Telegram-specific worker process, or a second scheduler loop.

### Interval

Add a deployment setting:

`source_sync_telegram_mtproto_interval_seconds = 300`

with the same >= 60-second validation policy as other source-sync intervals.

The recurring finalization path must resolve this Telegram job type to that deployment interval.

### Generic user source preferences are deferred

Do **not** add `telegram_mtproto` to the generic `SUPPORTED_SOURCE_KEYS` / `UserSourcePreference` surface in A4.4.

Reason: the generic preference contract necessarily exposes `history_days`, while MTProto history already has a durable A3/A4 fixed 14-day cutoff (`TELEGRAM_MTPROTO_HISTORY_DAYS`) persisted per selection. Do not expose a setting whose semantics would be false or only partially effective.

Therefore:

- `SourceSyncPreferenceService.is_job_type_enabled()` may continue to treat this unmapped Telegram job as enabled;
- `deployment_default_interval_seconds_for_job_type()` (or the narrow equivalent) must explicitly return `source_sync_telegram_mtproto_interval_seconds` for the Telegram job rather than falling back to Gmail;
- do not change existing source-preference API/UI behavior in this phase.

## Scheduler lifecycle

Extend `SourceSyncScheduler` using the existing account-maintenance pattern.

### Ensure

When runtime MTProto configuration is usable:

- `SECRETARY_CREDENTIAL_KEY` present;
- `telegram_api_id > 0`;
- non-blank `telegram_api_hash`;

then each existing `TelegramMtprotoAccount` gets exactly one recurring Telegram account job.

The job may exist even when no folders are configured. This is intentional: `reconcile_scope()` with zero configured folders must be able to deactivate previously active durable rows without a Telegram history fetch.

### Retire

A stale Telegram recurring job must be retired, using existing recurring-job semantics, when:

- its account no longer exists / no longer belongs to that user; or
- deployment MTProto runtime configuration is unavailable.

Do not retire a currently running job out from under the worker; follow the existing scheduler rule for running jobs.

Account deletion/log-out cleanup and FK cascades remain the account lifecycle mechanism; do not add a new auth-status column or migration.

### Manual trigger

`SourceSyncScheduler.trigger_all_for_user()` must trigger the Telegram recurring account job when the user has a valid connected MTProto account and runtime configuration is present.

Do not add a new API endpoint solely for A4.4 if the existing trigger-all path already exposes the required behavior.

## Recurring orchestration service

Prefer a small dedicated orchestration service/module for the account-level run so the source-sync handler remains thin and tests can exercise the orchestration independently.

The orchestration must use one database Session/transaction supplied by the worker and the existing encryption/configuration objects. A synchronous worker handler may bridge the existing async Telegram service calls in the smallest safe way (for example, an `asyncio.run()` boundary local to the Telegram handler/orchestrator). Do not redesign the worker to async globally.

### Account ownership

The payload `account_id` must match the connected `TelegramMtprotoAccount` for `user_id`.

A stale/mismatched/deleted account job must not synchronize another user's account or peers. Follow the existing source-handler style: a stale job may no-op safely and be retired by maintenance, but ownership mismatch must never result in provider calls.

## Reconcile-before-sync rule

Every recurring run must call `TelegramMtprotoScopeService.reconcile_scope(user_id)` **before** selecting peers for history sync.

Consequences to prove:

- a peer muted or removed from configured folders at reconciliation is not synced in the same run;
- a newly eligible private/group/supergroup peer activated by reconciliation may be synced in the same run;
- unsupported/bot/broadcast dialogs do not become history jobs/rows beyond the already accepted scope semantics;
- a missing/ambiguous folder, truncated discovery, authorization failure, or other fail-closed scope error prevents all peer history work for that run;
- existing imported Objects remain retained; A4.4 does not purge or mutate retrieval visibility directly — A4.3 reads `scope_active`.

## Bounded peer batch and fair progress

Define one explicit constant, default:

`TELEGRAM_MTPROTO_RECURRING_MAX_PEERS_PER_RUN = 10`

A recurring account run may attempt at most this many active peers.

Do not select a fixed "first N" forever.

Persist a lightweight round-robin cursor in the existing recurring Job JSON payload; no schema migration is allowed. Use a stable peer ordering (numeric `peer_id` is sufficient). A suggested payload key is:

`telegram_peer_cursor`

The cursor must:

- survive normal recurring success/failure finalization;
- advance after a successful peer sync;
- advance after a **peer-local** skip/failure so one poison peer cannot starve later peers;
- wrap deterministically when the end of the active peer set is reached;
- tolerate peers leaving/entering scope between runs;
- not expose encrypted provider references or Telegram session data.

The existing Job payload is public operational state only; keep it limited to non-secret account/cursor/status metadata.

## Error policy

Use the existing Telegram exception taxonomy; do not leak provider/session details into Job errors.

### Peer-local: continue the batch

Treat errors that mean one peer became unusable after reconciliation as peer-local and continue with later peers, while advancing the round-robin cursor for fairness. This includes the existing peer-local unavailable/reference/scope-race errors where semantically appropriate, such as:

- `TelegramMtprotoGroupUnavailableError`;
- `TelegramMtprotoProviderReferenceInvalidError`;
- `TelegramMtprotoPeerNotInActiveScopeError` caused by a race after reconciliation.

Do **not** set `scope_active=false` merely because a history request failed. Folder/mute reconciliation remains the canonical scope authority.

### Account/provider-wide: stop the run

Errors affecting the account/provider/run as a whole must stop further peers and propagate to the existing worker finalization path, including:

- `TelegramMtprotoProviderUnavailableError`;
- `TelegramMtprotoAuthorizationInvalidError`;
- account/configuration errors;
- fail-closed scope reconciliation errors.

Add narrow Telegram retry classification to the existing job error handling:

- provider unavailable is retryable;
- if `TelegramMtprotoProviderUnavailableError.retry_after_seconds` is present, honor it as the recurring job `run_after` delay;
- authorization-invalid / account-not-connected / deployment configuration errors are non-retryable for the immediate attempt and fall back to the existing recurring failure cooldown/rearm behavior;
- scope-unavailable may use bounded retry/cooldown semantics, but must never continue to history sync in the same run.

Sanitized `last_error` must not contain encrypted session content, provider references, phone/auth state, API hash, credential key, or raw provider payloads.

## History semantics

For every selected peer, call the existing `TelegramMtprotoHistoryService.sync_scope_peer(user_id, peer_id)`.

Do not duplicate the history importer.

Preserve A3/A4.2 behavior:

- max 200 scanned messages per peer run;
- existing forward + backfill cursors;
- fixed 14-day cutoff;
- Telegram materializer and downstream enqueue semantics;
- `history_last_synced_at` updates only through the existing history service;
- private/group/supergroup support;
- no manual-selection gate for scoped sync.

A4.4 must not reset history cursors on recurring runs, scope deactivation, or re-entry.

## Deliberate boundaries

Do NOT implement in A4.4:

- a new database migration;
- a Telegram-specific queue/worker/scheduler daemon;
- per-peer recurring Job rows;
- Redis/Celery/Rabbit/Kafka;
- UI/Flutter changes;
- generic `UserSourcePreference` / `history_days` exposure for Telegram;
- changing the 14-day Telegram history policy;
- physical purge/delete of retained Telegram Objects;
- embedding/retrieval redesign;
- provider-side Telegram mutations/sends;
- legacy Bot API removal;
- merge to `main`;
- production deployment, production migration, SSH, or runtime production probing.

## Required tests

Add a focused A4.4 test file (for example `backend/tests/test_telegram_mtproto_a4_4.py`) plus minimal additions to existing scheduler/worker tests where they prove integration better.

Use PostgreSQL-backed Jobs/accounts/selections for the core scheduling state. Cover at minimum:

1. **Recurring job identity/lane**
   - Telegram job type is in the existing recurring source lane;
   - handler registered;
   - one recurring account job is ensured, repeated maintenance does not duplicate it;
   - payload contains account id and only safe operational cursor metadata.

2. **Scheduler lifecycle**
   - valid runtime config + MTProto account => job exists;
   - missing Telegram runtime config => stale non-running job retired / no new job;
   - deleted account => stale non-running job retired;
   - running stale job is not retired mid-run;
   - `trigger_all_for_user()` triggers the Telegram account job.

3. **No generic source-preference exposure**
   - Telegram is not silently added to `SUPPORTED_SOURCE_KEYS_ORDERED` / generic history-days preference surface;
   - recurring finalization still resolves Telegram's own 300-second deployment interval.

4. **Reconcile before history**
   - verify call/order explicitly;
   - fail-closed reconcile => zero `sync_scope_peer` calls;
   - peer deactivated by reconcile => not selected in same run;
   - newly activated peer => eligible in same run.

5. **Active peer filtering**
   - only `scope_active=true` rows for the payload account are attempted;
   - `manual_selected` does not matter;
   - other account/user rows are never attempted.

6. **Batch bound + round robin**
   - at most 10 peers attempted per run;
   - cursor persists in recurring Job payload;
   - subsequent run continues after cursor and wraps;
   - scope churn does not break cursor behavior;
   - peer-local failure advances cursor and later peer is still attempted.

7. **Provider/account failures**
   - provider-wide failure stops later peer attempts;
   - authorization/config failure stops later peers;
   - provider `retry_after_seconds` is reflected in worker recurring retry timing;
   - sanitized job error contains no credential/session/provider-reference secrets.

8. **History engine reuse**
   - recurring orchestration calls `sync_scope_peer()` rather than a duplicate importer;
   - private/group/supergroup peer ids pass through;
   - existing selection history cursors are not reset before/after invocation.

9. **Empty folders / deactivation**
   - recurring account job still runs with no configured folders;
   - reconciliation to an empty scope deactivates formerly active rows;
   - no Telegram history fetch occurs for those deactivated rows.

10. **Regression safety**
   - existing Gmail/Google Calendar/Yandex/Mattermost/Teams recurring job behavior and source preferences remain unchanged;
   - source-sync lane/general-worker exclusion still behaves correctly.

## Required verification

Use only local development PostgreSQL:

`docker compose -f infra/compose.yaml -f infra/compose.dev.yaml up -d db`

Wait for healthy.

From `backend` run:

`alembic upgrade head`

Run complete Telegram suite including A4.4:

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py tests/test_telegram_mtproto_a4_3.py tests/test_telegram_mtproto_a4_4.py`

Also run existing focused scheduler/queue/worker/source-sync preference tests and any Telegram handler/history/scope tests changed or relied on. Report the exact files/commands and results; do not replace new A4.4 acceptance tests with old-suite compatibility only.

Run:

`alembic heads`

Run `ruff check` over every changed Python/test file.

Run:

`git diff --check`

## Completion report

Commit and push only to `review/telegram-depth-a4-folder-scope`. Do not merge to `main`.

Return:

- starting Architect bookkeeping HEAD;
- A4.4 implementation commit SHA(s);
- final remote review HEAD;
- changed files;
- confirmation no migration and Alembic remains `0046`;
- exact DB startup + `alembic upgrade head` result;
- exact Telegram suite and focused scheduler/worker/queue test commands/results;
- exact ruff and `git diff --check` results;
- job type, interval, batch-size constant, and round-robin payload key;
- evidence reconcile runs before peer history;
- evidence muted/removed peers are excluded and newly active peers may sync in the same run;
- evidence max-10 + cursor wrap/fairness including a peer-local failure;
- evidence provider-wide failure stops the batch and Retry-After is honored;
- evidence sanitized Job error contains no sensitive Telegram values;
- evidence no generic Telegram `history_days` preference was exposed;
- confirmation existing A3/A4 history cursors/materializer are reused and not reset;
- confirmation no scheduler service/queue daemon/UI/production/A4.5 work was started;
- `git status --short`;
- final marker exactly: `TELEGRAM_A4_4_RECURRING_SYNC_READY`.

Then STOP. Do not begin another Telegram phase.

## Production boundary

No production deployment, production migration application, rollback, SSH, production Compose, runtime probing, credential changes, or provider-side Telegram mutation is authorized.
