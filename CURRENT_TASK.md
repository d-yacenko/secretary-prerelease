# Current task — Telegram MTProto M4AY1R2: never persist scope normalization cutoff

## Status

M4AY1 base:
`443dc8c91bd7e66f5c24fdf8ab0f2bd270402673`

M4AY1R corrective:
`e0f89a30bb204b904bb49e47974dc4dbba5bbb48`

M4AY1R fixed the runtime normalization cutoff for scope mode, but review found one remaining blocker.

Do NOT deploy either commit yet.

## Remaining blocker

Current persistence logic is effectively:

```python
if not (scope_mode and previous_latest_message_id is not None):
    selection.history_cutoff_at = cutoff
```

For a FRESH scope peer:
- `scope_mode=true`
- `previous_latest_message_id=None`

so the condition is true and the row persists:

`history_cutoff_at = datetime.min(UTC)`

This violates the product contract that folder-scope bootstrap is count-bounded and must not create a synthetic time cutoff.

It also creates a cross-mode bug:
if the same retained row is later `manual_selected=true`, manual `sync_group` sees the stored `datetime.min` as an existing cutoff and can deep-backfill arbitrarily old history instead of establishing the normal 14-day manual cutoff.

## Goal

BUILD / REVIEW ONLY.

Make scope mode NEVER write `history_cutoff_at`.

Scope sync may use `datetime.min(UTC)` internally for normalization, but that value is transient only and must never be persisted.

## Exact persistence semantics

### Scope mode

For BOTH fresh and existing scope peers:
- preserve `selection.history_cutoff_at` byte-for-byte/value-for-value;
- if it starts `None`, it stays `None`;
- if it starts as a legacy/manual datetime, preserve it exactly;
- do not replace it with `datetime.min`;
- do not replace it with now-14-days.

### Manual mode

For `sync_group`:
- keep current behavior unchanged;
- if cutoff is absent, establish the existing 14-day cutoff;
- if cutoff already exists, retain/use it per current manual semantics.

## Preferred smallest fix

The persistence condition should be equivalent to:

```python
if not scope_mode:
    selection.history_cutoff_at = cutoff
```

or an equally clear helper.

Do not change the scope normalization decision introduced in M4AY1R.

## Required regressions

Because local PostgreSQL is unavailable, add DB-independent executable coverage for the persistence policy, not only the normalization policy.

At minimum prove without DB:

1. scope-mode normalization cutoff is aware `datetime.min`;
2. scope-mode cutoff persistence decision is NEVER write;
3. manual-mode cutoff persistence decision is write;
4. fresh scope starting cutoff=None remains conceptually None;
5. existing scope with a legacy cutoff preserves the exact original value;
6. manual-mode absent cutoff still resolves to now-14-days behavior.

Also retain/collect DB-backed tests for:
- fresh scope old messages materialize;
- fresh scope one fetch limit=20;
- fresh scope cutoff remains None;
- pre-existing scope cutoff preserved;
- existing scope cursor/backfill/completion preserved;
- manual path cutoff/backfill unchanged;
- scope deactivate/reactivate no re-bootstrap;
- recurring scope_active-only;
- Q1 quarantine;
- no schema/Alembic change;
- provider taxonomy unchanged.

Do not claim DB-backed PASS if PostgreSQL cannot initialize.

## Validation

Run:
- DB-independent M4AY1R/M4AY1R2 tests;
- DB-backed A3/A4.2/A4.4/Q1 as available;
- Python compile;
- Ruff;
- `git diff --check`.

## Strictly forbidden

Do NOT:
- deploy;
- move production ref;
- use production SSH;
- call Telegram/provider live;
- run live Sync;
- save/preview/apply folders live;
- login/re-login;
- mutate production;
- add migration / `0047`;
- enable MTProto AI;
- change Bot API.

## Deliverable

If corrected:
- commit/push canonical main;
- update `PROJECT_STATE.md`;
- do NOT deploy.

Report:
- corrective commit SHA;
- exact files changed;
- exact normalization semantics;
- exact persistence semantics;
- DB-independent test results;
- DB-backed blocked/pass status;
- manual path unchanged;
- recurring unchanged;
- Q1 unchanged;
- Ruff/diff-check;
- production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_M4AY1R2_SCOPE_CUTOFF_TRANSIENT_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
