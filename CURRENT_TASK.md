# Current task — Telegram MTProto M4AU1: prove manual-only ordinary visibility semantics

## Status

Production runtime/ref:
`b7fbdc71584cfde042a998fbfefb06015175a205`

Current production state for the one selected group:
- `MANUAL_SELECTED=true`
- `SCOPE_ACTIVE=false`
- `HISTORY_COMPLETE=true`
- `BACKFILL_CURSOR_PRESENT=false`
- `IMPORTED_OBJECT_COUNT=228`
- `ACTIVE_VISIBLE_OBJECT_COUNT=0`

The import is complete. The objects are hidden from ordinary Inbox visibility only because current transport visibility requires `scope_active=true`.

The human selected product direction **option 1**:
make an explicitly manual-selected peer visible in ordinary non-AI product read surfaces without broadening folder-derived scope.

## Goal

BUILD / REVIEW ONLY.

Implement and prove the smallest safe semantics change so a Telegram MTProto object is transport-visible when its matching owned selection is:

`manual_selected=true OR scope_active=true`

while preserving all existing fail-closed account/peer/metadata ownership checks.

Do NOT deploy this task.

## Important separation

This task is about **ordinary transport visibility**, not AI eligibility.

Production remains:

`TELEGRAM_MTPROTO_AI_ENABLED=false`

MTProto objects MUST remain excluded from:
- embeddings;
- LLM/assistant context;
- semantic/AI retrieval;
- summarization/classification;
- proactive AI processing.

Do not weaken the Q1 AI quarantine.

If the current helper coupling between transport visibility and AI-enabled predicates would accidentally broaden AI eligibility, refactor the policy boundary so ordinary transport visibility can include manual-selected peers while AI eligibility remains explicitly controlled and tested.

## Executor workspace

Work only from:

`~/work/secretary-executor`

Canonical origin:

`https://github.com/d-yacenko/secretary-prerelease.git`

Do not use `~/work/secretary` or `~/work/secretary-prerelease` for Executor implementation work.

## Required bootstrap

```bash
git fetch origin
git switch main
git pull --ff-only
git remote get-url origin
git rev-parse HEAD
git status --short
```

Require canonical origin, current `origin/main`, clean worktree.

Read at minimum:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `DECISIONS.md`
- `backend/app/domain/telegram_mtproto_visibility.py`
- `backend/app/domain/telegram_mtproto_ai.py`
- `backend/app/services/recent_source_service.py`
- `backend/app/services/object_query_service.py`
- `backend/app/services/context_service.py`
- `backend/app/services/graph_service.py`
- `backend/app/services/retrieval_service.py`
- `backend/app/services/telegram_mtproto_recurring_sync_service.py`
- `backend/tests/test_telegram_mtproto_a4_3.py`
- `backend/tests/test_telegram_mtproto_q1.py`

## Required ordinary-visibility semantics

For canonical Telegram MTProto chat-message objects with correct owned account+peer metadata:

1. `manual_selected=true, scope_active=false` -> ordinary transport-visible.
2. `manual_selected=false, scope_active=true` -> ordinary transport-visible.
3. `manual_selected=true, scope_active=true` -> ordinary transport-visible.
4. `manual_selected=false, scope_active=false` -> hidden.

Manual-only visibility must not mutate `scope_active`.

Do not make `Apply Scope` necessary for a manually-selected peer.

Deselecting a manual-only peer must hide retained objects again if `scope_active=false`; objects/history/cursors remain retained.

## Ordinary surfaces to prove

At minimum prove the manual-only row is visible through the same non-AI read surfaces that currently use the transport visibility gate, including:
- ObjectQuery;
- RecentSource / Inbox feed eligibility;
- ordinary graph/context visibility where the existing transport gate applies.

Preserve exact-target retention semantics already accepted where applicable.

Do not claim ordinary Search/assistant retrieval if that path is intentionally AI-gated under Q1.

## AI quarantine invariants

With `TELEGRAM_MTPROTO_AI_ENABLED=false`:
- manual-only visible MTProto objects remain AI-ineligible;
- retrieval candidate SQL excludes them;
- no embedding jobs are enqueued;
- no LLM context/assistant semantic retrieval path gains them.

Run focused Q1 regressions.

If tests reveal transport-visibility helpers are coupled unsafely into future AI-enabled behavior, isolate the policies rather than silently changing AI semantics.

## Recurring-sync boundary

Do NOT change recurring-sync selection semantics in M4AU1.

The recurring worker currently follows `scope_active=true` peers. Leave that unchanged.

Record this explicitly as follow-up product behavior: a manual-only visible peer can be manually synced but is not yet authorized for automatic recurring refresh.

## No schema/client/provider change

No migration.
No `0047`.
No Flutter/UI change required for this proof unless a test fixture strictly requires it.
No provider calls.
No Telegram login/Sync/Apply Scope.
No production SSH.
No production mutation.
Bot API untouched.

## Required regression matrix

Add focused tests proving:
- all four manual/scope truth-table cases;
- wrong account/user/peer metadata remains fail-closed;
- malformed metadata remains fail-closed;
- manual deselect from manual-only state hides retained object without deleting it;
- scope-active-only behavior remains visible;
- ordinary Inbox/RecentSource sees manual-only object;
- inactive/unselected object remains absent;
- Q1 AI quarantine remains intact with AI flag false;
- recurring-sync query remains `scope_active=true` only.

Run the existing relevant A4.3 and Q1 matrices plus focused new tests.

## Validation

Run:
- focused new tests;
- relevant A4.3 tests;
- Q1 tests;
- any ObjectQuery/RecentSource/graph/context tests touched;
- Ruff;
- `git diff --check`.

If local PostgreSQL is unavailable for DB-backed tests:
- report exactly which tests could not initialize;
- do not fabricate PASS;
- static/unit tests must still pass;
- do not use production DB to compensate.

## Deliverable

If implementation/review passes:
- commit/push canonical main;
- update `PROJECT_STATE.md`;
- do NOT deploy;
- do NOT move `production` ref.

Report:
- commit SHA;
- exact files changed;
- semantic truth table;
- test counts/results;
- Q1 quarantine result;
- recurring-sync unchanged confirmation;
- lint/diff-check;
- production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_M4AU1_MANUAL_VISIBILITY_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
