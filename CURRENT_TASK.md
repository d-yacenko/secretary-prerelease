# Current task — Telegram MTProto M4BB1: remove 500-dialog scope-preview truncation blocker

## Status

Production runtime/ref:
`cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`

M4BA1 human preview was intentionally stopped before Apply Scope.

Observed UI:
- selected folder: `Личное`;
- configured folders: 1;
- previewed scope: 28 dialogs;
- skipped: `broadcast=12, bot=19, unsupported=19`;
- preview: TRUNCATED.

No Apply Scope and no Sync occurred.

## Root cause

Current folder-scope preview uses:

`fetch_dialog_universe(session, DISCOVERY_DIALOG_LIMIT)`

with:

`DISCOVERY_DIALOG_LIMIT = 500`.

The Telethon implementation calls `iter_dialogs(limit=scan_limit)` and sets:

`truncated = seen >= scan_limit`.

So reaching the 500-dialog boundary is treated as incomplete and `reconcile_scope` correctly fails closed.

This makes accounts with a larger dialog universe unable to activate even a small selected folder.

## Goal

BUILD / REVIEW ONLY.

Create a safe, bounded folder-scope dialog scan that supports a substantially larger account universe while keeping:
- manual group discovery bounded as today;
- scope activation fail-closed if the new bound is genuinely exceeded;
- no live provider call in this task.

Do NOT deploy.

## Product decision

Introduce a folder-scope-specific bound:

`TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT = 2000`

Do NOT change `DISCOVERY_DIALOG_LIMIT=500` for manual group discovery.

For folder scope:
- scan up to 2000 dialogs;
- determine truncation with one-item lookahead, not `seen >= limit`;
- exactly 2000 total dialogs is complete/not-truncated;
- 2001+ dialogs is truncated/fail-closed;
- return/retain at most the first 2000 scanned dialog results;
- no unbounded provider iteration.

The selected small folder still must not be activated in this task.

## Required implementation

Prefer the smallest transport/service change.

### Transport

For `fetch_dialog_universe(session, limit)`:
- clamp requested limit to the folder-scope-specific maximum;
- request/iterate at most `scan_limit + 1` provider dialogs for lookahead;
- only process/return the first `scan_limit`;
- set `truncated=true` only when an extra provider dialog beyond the limit is actually observed;
- preserve current skipped-count classification for the retained scan window;
- do not leak content/IDs through errors.

Do not change history fetching, auth taxonomy, writes, or manual group discovery.

### Scope service

Use `TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT` for the dialog-universe scan.

Folder definition discovery may continue using `DISCOVERY_DIALOG_LIMIT`.

### Safety

`reconcile_scope` must continue to refuse mutation whenever preview is genuinely truncated.

No partial activation.

## Required tests

Add/adjust focused DB-independent transport/service tests proving:

1. 499 dialogs -> not truncated.
2. exactly 500 dialogs -> not truncated (regression against current boundary behavior).
3. exactly 2000 dialogs -> not truncated.
4. 2001 dialogs -> truncated.
5. provider iteration stops after at most 2001 items.
6. returned descriptors never exceed 2000.
7. skipped counts only cover retained first 2000 rows.
8. scope service requests the new 2000 bound for universe.
9. folder discovery still uses existing 500 bound.
10. manual group discovery remains at existing bound/behavior.
11. genuinely truncated scope still fails closed before `store.reconcile_scope`.
12. non-truncated scope reconciliation behavior remains unchanged.
13. provider/auth error taxonomy unchanged.
14. no schema/Alembic change.
15. shallow bootstrap/history semantics unchanged.
16. recurring remains scope-only.
17. Q1 AI quarantine unchanged.

Prefer fake async dialog iterators; no live Telegram.

If DB-backed tests cannot initialize locally, report them blocked honestly and ensure the truncation boundary behavior itself has DB-independent executable tests.

## Validation

Run:
- focused M4BB1 DB-independent tests;
- relevant A4.2 scope tests as available;
- relevant A4.4 recurring tests as available;
- Q1 as available;
- Python compile;
- Ruff;
- `git diff --check`.

## Strictly forbidden

Do NOT:
- deploy;
- move production ref;
- use production SSH;
- call Telegram/provider live;
- click Apply Scope;
- run live Sync;
- change selected folders live;
- login/re-login;
- mutate production;
- add migration / `0047`;
- enable MTProto AI;
- change Bot API.

## Deliverable

If PASS:
- commit/push canonical main;
- update `PROJECT_STATE.md`;
- do NOT deploy.

Report:
- commit SHA;
- exact files changed;
- exact scan/lookahead/truncation semantics;
- focused test results;
- DB-backed status;
- confirmation manual group discovery unchanged;
- confirmation shallow bootstrap unchanged;
- recurring/Q1 unchanged;
- Ruff/diff-check;
- production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_M4BB1_SCOPE_SCAN_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
