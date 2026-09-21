# Current task — Telegram MTProto M4AY1: shallow folder-scope bootstrap

## Status

The ordinary MTProto transport path is production-proven end-to-end for a manually selected group.

Production runtime/ref remains:
`2db36510fe884eadc40d63fed8661ed3627f1cbb`

Next selected product phase:
folder-derived Telegram scope with a shallow initial bootstrap instead of deep/time-window backfill.

This is the final major MTProto transport feature phase. Deploy, folder selection, Apply Scope, and live acceptance are later separately authorized steps.

## Product decision

For a peer that enters the folder-derived active scope with no history cursor yet:

- fetch at most the latest **20 provider history entries**;
- materialize only entries accepted by the existing canonical normalization/materializer;
- do **not** paginate backward for historical backfill;
- do **not** use the 14-day cutoff to request/fill older pages;
- establish `history_latest_message_id` from the fetched page;
- leave `history_backfill_before_message_id=None`;
- mark the scope bootstrap history as complete for backfill purposes;
- subsequent scope syncs fetch only messages newer than `history_latest_message_id`.

This intentionally means a scope-bootstrapped peer does not later surprise the user with automatic deep history loading.

The count of 20 is a fixed product constant for this phase, not a new environment/config surface.

## Important separation

### Manual-selected path

Keep the existing manual `sync_group` history behavior unchanged in M4AY1.

Do not regress the already production-proven manual-selected group behavior.

### Folder-scope path

`sync_scope_peer` gets the new shallow-bootstrap semantics.

After a scope peer has a `history_latest_message_id`, scope sync is incremental-only.

If an existing row already has a legacy/manual backfill cursor:
- scope sync must NOT consume the backfill cursor;
- scope sync must NOT perform historical backfill;
- preserve the existing backfill cursor/completion state so a separate manual path is not silently rewritten.

### Recurring sync

Keep recurring selection semantics unchanged:
- only `scope_active=true` peers;
- max peers per run remains bounded as today;
- newly activated scope peers naturally receive the shallow bootstrap when recurring sync reaches them;
- later runs are incremental-only.

Do not make `manual_selected=true` peers recurring unless they are also `scope_active=true`.

## AI / compliance invariants

Production canonical flag remains:
`TELEGRAM_MTPROTO_AI_ENABLED=false`

No scope-bootstrap message may enter:
- embedding;
- LLM context;
- semantic assistant retrieval;
- summarization/classification;
- proactive AI processing.

Preserve Q1 quarantine and all existing AI-gate tests.

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

```bash
git fetch origin
git switch main
git pull --ff-only
git remote get-url origin
git rev-parse HEAD
git status --short
```

Require canonical origin, current `origin/main`, and clean worktree.

Read at minimum:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `DECISIONS.md`
- `backend/app/services/telegram_mtproto_history_service.py`
- `backend/app/services/telegram_mtproto_scope_service.py`
- `backend/app/services/telegram_mtproto_recurring_sync_service.py`
- `backend/app/connectors/telegram/mtproto_transport.py`
- `backend/app/connectors/telegram/mtproto_account_store.py`
- `backend/tests/test_telegram_mtproto_a3.py`
- `backend/tests/test_telegram_mtproto_a4_2.py`
- `backend/tests/test_telegram_mtproto_q1.py`

## Implementation shape

Prefer the smallest service-level change.

Introduce an explicit constant, e.g.:

`TELEGRAM_MTPROTO_SCOPE_BOOTSTRAP_MESSAGES = 20`

Do not add a migration or new DB column.

Do not change provider auth/discovery/scope reconciliation semantics.

Do not make `Apply Scope` fetch history directly. Scope reconciliation remains scope reconciliation; history arrives through the existing scope-sync/recurring path.

Keep provider retry/taxonomy behavior unchanged.

## Required behavior

### Fresh folder-scope peer

Given:
- `scope_active=true`;
- `history_latest_message_id=None`.

One `sync_scope_peer` call must:
- issue one newest-first history fetch with limit 20;
- use no min-message bound;
- use no max-message/backfill bound;
- materialize the eligible subset;
- set latest message id from the page when entries exist;
- set backfill cursor to None;
- mark history complete;
- make no second historical page request even if provider says `has_more=true`.

If the page is empty:
- remain bounded;
- mark bootstrap complete;
- do not fetch another page.

### Existing scope peer

Given a positive `history_latest_message_id`:
- request only newer messages using the existing incremental semantics;
- do not fetch historical/backfill pages;
- preserve any pre-existing manual/legacy backfill cursor and `history_complete` state.

### Manual sync

`sync_group` retains the existing 14-day / bounded backfill behavior.

## Regression matrix

Add focused tests proving at minimum:

1. Fresh scope peer requests newest-first limit exactly 20.
2. Fresh scope peer with provider `has_more=true` still performs exactly one history fetch.
3. Fresh scope peer stores latest id, clears/no backfill cursor, marks complete.
4. Empty fresh scope page performs one fetch and marks complete.
5. Eligible text subset can be less than 20 without causing a second page.
6. Existing scope peer uses incremental min-id semantics only.
7. Existing scope peer with legacy backfill cursor does not consume/advance it.
8. Manual `sync_group` initial behavior still uses the existing manual history constants/backfill contract.
9. Scope deactivation/reactivation preserves latest cursor and does not re-bootstrap when latest id already exists.
10. Recurring sync still selects only `scope_active=true`.
11. Recurring fresh peers call the scope path, not manual path.
12. Q1 AI quarantine remains intact with flag false.
13. No schema/Alembic change.
14. Existing provider error taxonomy remains unchanged.

Use exact transport call assertions: direction, bounds, limit, and call count.

## Validation

Run:
- focused M4AY1 tests;
- relevant A3 history tests;
- relevant A4.2 scope/recurring tests;
- Q1 tests;
- Ruff;
- `git diff --check`.

If local PostgreSQL is unavailable:
- report exactly which DB-backed tests cannot initialize;
- do not fabricate PASS;
- do not use production DB to compensate.

## Strictly forbidden

Do NOT:
- deploy;
- move `production` ref;
- use production SSH;
- connect to Telegram/provider in live mode;
- login/re-login;
- Sync live;
- select/save folders live;
- preview scope live;
- Apply Scope live;
- mutate production;
- add migration / `0047`;
- enable MTProto AI;
- change Bot API.

## Deliverable

If implementation/review passes:
- commit/push canonical main;
- update `PROJECT_STATE.md`;
- do NOT deploy.

Report:
- commit SHA;
- exact files changed;
- exact fresh-scope transport call semantics;
- test counts/results;
- confirmation manual path unchanged;
- confirmation recurring remains scope-only;
- Q1 result;
- Ruff/diff-check;
- production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_M4AY1_SHALLOW_SCOPE_BOOTSTRAP_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
