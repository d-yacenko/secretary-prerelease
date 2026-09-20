# Current task — Telegram MTProto M4AT1: build/review read-only visibility-state probe

## Status

Production runtime/ref:
`b7fbdc71584cfde042a998fbfefb06015175a205`

Telegram MTProto bounded initial history import for the one manually selected group is complete.

Last human Sync aggregate:
- scanned=100
- materialized=49
- created=49
- updated=0
- unchanged=0
- skipped=51
- history_complete=true

No further initial backfill Sync is required.

Important product invariant:
- MTProto objects are visible through normal read paths only when the matching `TelegramMtprotoChatSelection.scope_active=true`;
- `manual_selected=true` alone does not grant normal Inbox/search/retrieval visibility.

Apply Scope has not been used in this diagnostic line, so do not assume imported objects should already be visible in Inbox.

## Goal

BUILD / REVIEW ONLY.

Create a human-shell, read-only production probe that determines whether the imported selected-group objects are currently eligible for normal product visibility.

Do NOT run it live in this task.

## Executor workspace

Work only from:

`~/work/secretary-executor`

Canonical origin:

`https://github.com/d-yacenko/secretary-prerelease.git`

Do not use:
- `~/work/secretary`
- `~/work/secretary-prerelease`

for Executor implementation work.

## Required bootstrap

Before implementation:

```bash
git fetch origin
git switch main
git pull --ff-only
git remote get-url origin
git rev-parse HEAD
git status --short
```

Require exact canonical origin, current `origin/main`, and clean worktree.

Read:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `backend/app/domain/telegram_mtproto_visibility.py`
- `backend/app/services/recent_source_service.py`
- `backend/app/db/models.py`
- existing manual human-shell probe wrappers for trust/protocol patterns.

## New artifact

Create a new read-only human-shell probe under `ops/production/`, for example:

`manual_mtproto_visibility_state_probe.sh`

A small Python helper/parser plus focused local tests are allowed.

## Future live semantics

The future human-shell run must be strictly read-only and zero-provider.

### Production guards

Verify:
- canonical target.json;
- exact pinned ED25519 host key;
- production HEAD exact `b7fbdc71584cfde042a998fbfefb06015175a205`;
- remote `origin/production` exact same SHA;
- production worktree clean;
- Compose/db/api/worker running;
- DB healthy;
- Alembic `0046`.

### Read-only state

Inside the API container using `SessionLocal(autoflush=False)` and no commit/flush:

1. Require exactly one MTProto account.
2. Require exactly one `manual_selected=true` Telegram selection.
3. Read only safe booleans:
   - `MANUAL_SELECTED=true`
   - `SCOPE_ACTIVE=true|false`
   - `HISTORY_COMPLETE=true|false`
   - `BACKFILL_CURSOR_PRESENT=true|false`
4. Count persisted Telegram MTProto objects for that exact account+peer:
   - provider=telegram
   - kind=chat_message
   - metadata transport=mtproto
   - matching account_id + peer_id
5. Count how many of those exact objects pass `telegram_mtproto_active_object_predicate()`.
6. Optionally, if it can be done safely without content/IDs, report how many of those exact objects are present in the current recent-source read surface.

## Safe output

Allowed aggregate output only:

- production guard booleans;
- `ACCOUNT_EXACTLY_ONE=true|false`
- `MANUAL_SELECTED_EXACTLY_ONE=true|false`
- `MANUAL_SELECTED=true|false`
- `SCOPE_ACTIVE=true|false`
- `HISTORY_COMPLETE=true|false`
- `BACKFILL_CURSOR_PRESENT=true|false`
- `IMPORTED_OBJECT_COUNT=<bounded nonnegative integer>`
- `ACTIVE_VISIBLE_OBJECT_COUNT=<bounded nonnegative integer>`
- optional `RECENT_SOURCE_VISIBLE_COUNT=<bounded nonnegative integer>`
- `TELEGRAM_NETWORK_CALLS=0`
- allowlisted failure stage/class
- explicit terminal marker.

Never print:
- Telegram/account/group/peer/message IDs;
- message text/title/sender/timestamps;
- session/reference/access hash;
- DB credentials;
- raw SQL rows;
- traceback/raw stderr.

## Strictly forbidden

Do NOT:
- construct TelegramClient;
- connect to Telegram;
- call any provider API;
- Sync;
- login/re-login;
- Apply Scope;
- change folder/group selections;
- write/flush/commit DB;
- materialize/upsert;
- restart/recreate services;
- edit production files/env/refs;
- run migrations;
- enable MTProto AI;
- change Bot API.

## Interpretation contract

The later human run will be interpreted as:

- `IMPORTED_OBJECT_COUNT > 0` and `SCOPE_ACTIVE=false`:
  import succeeded; missing Inbox visibility is expected due to active-scope gate. Do not call it an import defect.

- `IMPORTED_OBJECT_COUNT > 0` and `SCOPE_ACTIVE=true` and `ACTIVE_VISIBLE_OBJECT_COUNT > 0`:
  proceed to human UI verification in Inbox.

- `IMPORTED_OBJECT_COUNT == 0`:
  STOP for read-only diagnosis; do not Sync again.

- any structural/protocol uncertainty:
  fail closed and STOP.

## Local tests/review

Run local-only checks. No production connection.

At minimum:
- `bash -n`;
- valid inactive-scope transcript;
- valid active-scope transcript;
- zero imported objects;
- premature EOF;
- unsafe/unknown output fails closed;
- static proof of no provider calls and no DB write/commit/flush path;
- Ruff/diff-check as applicable.

## Deliverable

If review passes:
- commit/push canonical main;
- update `PROJECT_STATE.md`;
- do NOT run live probe.

Report:
- commit SHA;
- changed files;
- test counts;
- lint/diff-check;
- production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_M4AT1_VISIBILITY_PROBE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
