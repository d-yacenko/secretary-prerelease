# Current task — Telegram Depth A4.2 durable active scope + explicit scoped history sync

## Status

Telegram Depth A4.1 — ACCEPTED on `review/telegram-depth-a4-folder-scope` through final SHA `43944ca47b407889f87eb891b898a1c55097f7f0`.

Accepted A4.1 includes durable custom-folder configuration, corrected Telegram `DialogFilter` semantics, read-only dynamic scope preview, stable provider filter IDs, independent current-mute exclusion, private/group/supergroup candidates, and required provider regression coverage.

Telegram Depth A4.2 — ACTIVE / IMPLEMENTATION AUTHORIZED.

This phase materializes the accepted dynamic folder scope into durable active peer state and connects an explicitly requested active peer to the already accepted A3 bounded history engine. It does NOT authorize bulk history synchronization, recurring scheduling, assistant retrieval filtering, UI work, merge to main, or production deployment.

## Fixed branch and baseline

- Repository: `d-yacenko/secretary-prerelease`
- Work only in the existing review worktree/branch: `review/telegram-depth-a4-folder-scope`.
- Required code baseline includes A4.1 accepted SHA `43944ca47b407889f87eb891b898a1c55097f7f0` plus any Architect bookkeeping commits already pushed to that branch.
- Exact accepted A3 SHA `4777c32deb055f5024f3dbced125b4dd6db97e85` must remain in ancestry.
- Fetch and fast-forward only to current `origin/review/telegram-depth-a4-folder-scope` before implementation.
- Do not rebase or rewrite accepted commits.

## Architectural intent

`telegram_mtproto_chat_selections` is a legacy-named table that already owns the A3 provider reference and durable history cursors. A4.2 must evolve that row into durable peer sync state instead of creating a parallel cursor table.

Two independent concepts must coexist during the transition:

1. `manual_selected` — legacy A2/A3 manual group-selection compatibility.
2. `scope_active` — canonical A4 dynamic folder-scope membership.

A row may be both, either, or neither. The row and its history cursors MUST survive temporary scope inactivity so re-entry does not restart the bounded backfill.

## Authorized implementation

### 1. Migration 0046 — evolve durable peer state

Add the next Alembic migration after `0045` (expected head `0046`) that evolves `telegram_mtproto_chat_selections` without renaming or replacing the table.

Add at minimum:

- `manual_selected BOOLEAN NOT NULL`;
- `scope_active BOOLEAN NOT NULL`.

Migration semantics:

- all rows that already exist before `0046` represent legacy A2 manual selections, therefore backfill them to `manual_selected = true`;
- future newly materialized folder-scope rows must be able to start with `manual_selected = false`;
- `scope_active` starts false for pre-existing rows;
- relax the peer-kind check constraint from only `group/supergroup` to exactly `private/group/supergroup`;
- keep uniqueness `(account_id, peer_id)` and all A3 history cursor columns intact.

Do not reset or rewrite A3 cursor data during migration.

### 2. Dialog descriptor completeness

Extend the A4 dialog descriptor only as needed for durable peer state, including `is_forum` for supergroups. Private/basic-group descriptors use false.

The durable row must keep encrypted provider peer reference, current peer kind, title, username and forum flag. Provider references remain encrypted with the existing credential encryption; never persist raw access hashes/session data in plaintext columns.

### 3. Legacy manual-selection compatibility

Update `TelegramMtprotoAccountStore` / A2 behavior so legacy manual selection remains semantically correct while rows are retained for A4 history continuity:

- `list_selections()` returns only rows with `manual_selected = true`;
- `save_selection()` sets `manual_selected = true` and updates descriptor fields without resetting history cursors or `scope_active`;
- legacy deselection sets `manual_selected = false` instead of deleting the durable row;
- do not delete the row merely because both flags become false; cursor/history state must remain available for future scope re-entry;
- A3 legacy `/groups/{peer_id}/sync` must still require `manual_selected = true`, not merely row existence.

Existing A1/A2/A3 behavior visible to legacy API callers must remain compatible.

### 4. Atomic dynamic-scope reconciliation

Add a store/service reconciliation path that accepts the complete eligible descriptors produced by accepted A4.1 and atomically updates durable scope state for one MTProto account.

On a complete scope snapshot:

- every eligible private/group/supergroup peer is upserted by `(account_id, peer_id)` and gets `scope_active = true`;
- existing row history cursor fields are preserved exactly;
- existing `manual_selected` is preserved exactly;
- provider reference and current descriptor metadata may be refreshed for active peers;
- every previously `scope_active = true` row absent from the complete eligible set becomes `scope_active = false`;
- rows becoming inactive are NOT deleted;
- no imported Telegram object/message is deleted or purged;
- unsupported/bot/broadcast peers never receive scope rows.

A peer that later re-enters scope must reactivate the same durable row and resume from its existing A3 cursors.

### 5. Fail closed on incomplete dynamic scope

A4.1 exposes bounded/truncated status. A4.2 reconciliation MUST NOT use an incomplete snapshot to deactivate peers.

Therefore:

- if folder discovery or dialog-universe evaluation reports `truncated = true`, reconciliation fails closed with a sanitized scope error;
- the prior durable `scope_active` set remains unchanged;
- missing persisted folder IDs and other A4.1 fail-closed errors likewise leave active-scope state unchanged;
- an explicit complete empty scope (for example zero configured folders) is different from truncation and is allowed to deactivate all previously active scope rows while retaining the rows/cursors.

No partial reconciliation.

### 6. Reconcile API

Add an explicit authenticated/user-scoped backend operation, preferably:

`POST /telegram/mtproto/sync-scope/reconcile`

It should:

1. evaluate current A4.1 dynamic folder scope;
2. reject incomplete/truncated results before scope-state mutation;
3. atomically reconcile durable `scope_active` rows;
4. return a sanitized summary such as active/activated/deactivated/unchanged counts and current active peer descriptors.

This endpoint MUST NOT fetch Telegram message history.

### 7. Reuse A3 history engine for one active peer

Generalize A3 internals minimally so the same bounded history/cursor/materializer path can sync any supported active peer kind.

Preserve the legacy `sync_group()` behavior for A3 compatibility, but factor a shared internal sync implementation and add a scoped operation such as `sync_scope_peer(user_id, peer_id)` that:

- requires the durable row to exist and `scope_active = true`;
- supports `private`, `group`, and `supergroup`;
- uses the row's existing encrypted provider reference and A3 cursors;
- uses the same A3 bounds (`14` days, max messages per run, page size) unless an existing test proves a narrower requirement;
- uses the existing Telegram materializer and idempotent external ID scheme;
- updates the same durable A3 cursor fields;
- rejects inactive/not-in-scope peers before any `fetch_history` provider call.

Add a sanitized error for “peer not in active Telegram sync scope” if needed rather than reusing misleading “group not selected” wording.

### 8. Scoped per-peer history API

Add an explicit authenticated/user-scoped endpoint, preferably:

`POST /telegram/mtproto/sync-scope/peers/{peer_id}/sync`

Path semantics must support Telegram marked IDs for private users and groups/supergroups across signed 64-bit range, excluding zero.

This endpoint syncs exactly ONE already-active peer per request.

Do NOT add a “sync all active peers” loop in A4.2.

### 9. History metadata for private peers

A3 normalized objects currently contain group-oriented metadata names. Add generic metadata fields needed for private dialogs, at minimum `peer_id`, `peer_kind`, `peer_title`, and `peer_username`.

For group/supergroup rows, preserve existing legacy group metadata fields if tests or downstream compatibility require them. Do not break existing A3 object identity/external IDs.

### 10. Boundaries deliberately deferred past A4.2

Do NOT implement in this task:

- recurring Telegram jobs/scheduler integration;
- automatic bulk iteration over all active peers;
- assistant/retrieval query filtering based on `scope_active`;
- physical deletion or purge of previously imported Telegram history;
- automatic history sync as a side effect of folder config replacement or scope reconciliation;
- removal of A2/A3 legacy manual endpoints;
- Flutter/UI changes;
- production deployment or production migrations.

The durable `scope_active` flag created here becomes the canonical gate that later scheduler/retrieval work will consume.

## Required tests

Prefer a dedicated `backend/tests/test_telegram_mtproto_a4_2.py` plus focused updates to A2/A3 tests where compatibility must be demonstrated.

Cover at minimum:

- Alembic has single `0046` head;
- model/check constraint permits exactly private/group/supergroup;
- existing legacy rows are represented as manual-selected and not scope-active under migration semantics;
- folder-created private/group/supergroup rows use `manual_selected = false`, `scope_active = true`;
- reconciliation activates eligible peers and deactivates peers that leave folders or become muted;
- deactivation retains the database row, encrypted provider reference and all A3 history cursor values;
- re-entry reactivates the same row with cursor values preserved;
- a legacy manually selected row entering/leaving folder scope preserves `manual_selected = true`;
- legacy manual deselection makes it disappear from A2 `list_selections` but does not destroy durable cursor state;
- legacy A3 group sync still requires manual selection;
- explicit complete empty scope deactivates all scope-active rows without deleting them;
- truncated scope fails before reconciliation and leaves all prior active flags unchanged;
- missing configured folder fails closed and leaves active flags unchanged;
- unsupported/bot/broadcast peers do not become durable scope rows;
- reconcile endpoint never calls `fetch_history`;
- scoped sync rejects inactive peer before provider history call;
- scoped sync works for a private peer and uses the existing A3 bounded history/materializer/cursors;
- scoped group/supergroup sync remains compatible with A3 cursor behavior;
- repeated sync remains idempotent with the existing external ID scheme;
- generic peer metadata is emitted for private history while legacy group metadata remains compatible where required;
- no bulk “sync all” behavior and no scheduler/queue orchestration is introduced.

Run at minimum from `backend`:

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py`

`alembic heads`

Run `ruff check` over every changed Python file and `git diff --check`.

## Completion report

Commit and push only to `review/telegram-depth-a4-folder-scope`. Do not merge to `main`.

Return exactly:

- starting branch HEAD after Architect bookkeeping fast-forward;
- A4.2 implementation commit SHA(s);
- final pushed branch HEAD;
- changed files;
- migration head;
- exact test/lint/diff-check commands and results;
- schema explanation for `manual_selected` vs `scope_active`;
- reconciliation summary and fail-closed behavior on truncation;
- confirmation deactivation/re-entry preserves A3 cursors and rows;
- confirmation private/group/supergroup scoped history uses the shared A3 engine;
- confirmation reconcile never fetches history and per-peer endpoint syncs only one active peer;
- confirmation no scheduler/bulk/retrieval/UI/production work was started;
- `git status --short` for review worktree;
- final marker exactly: `TELEGRAM_A4_2_DURABLE_SCOPE_READY`.

Then STOP. Do not begin the next Telegram phase.

## Production boundary

No production deployment, migration application, rollback, SSH, Compose, runtime probing, credential changes, or provider-side mutations beyond the existing read-only Telegram reads/history read explicitly invoked by the scoped per-peer sync are authorized.
