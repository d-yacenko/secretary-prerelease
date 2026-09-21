# Current task — Telegram MTProto M4AY1R: remove legacy time cutoff from shallow scope bootstrap

## Status

M4AY1 implementation commit:
`443dc8c91bd7e66f5c24fdf8ab0f2bd270402673`

is integrated to canonical main but is NOT yet accepted for deploy.

The one-page scope flow is correct:
- one newest-first fetch;
- limit 20;
- no second historical page;
- incremental-only after latest cursor exists.

Review found one semantic blocker.

## Blocker

`_sync_selection(..., scope_mode=True)` still computes:

`now - TELEGRAM_MTPROTO_HISTORY_DAYS`

and passes that cutoff into `_apply_page -> _normalize_entry`.

Therefore a quiet folder chat whose latest 20 provider entries are older than 14 days can:
- fetch the intended latest 20 entries;
- then discard all of them because of the old manual-history cutoff.

That violates the selected product rule:

**folder scope bootstrap is count-bounded, not time-bounded.**

The current code also persists a synthetic 14-day `history_cutoff_at` for a fresh scope row, which misrepresents the scope bootstrap semantics.

## Goal

BUILD / REVIEW ONLY.

Correct M4AY1 so scope-mode history sync has no legacy time-window filter.

Do NOT deploy.

## Required semantics

### Scope mode — fresh peer

Given:
- `scope_active=true`;
- `history_latest_message_id=None`.

Then:
- fetch exactly one newest-first page, limit 20;
- no min/max history bound;
- materialize canonical eligible entries from those latest 20 regardless of age;
- service/textless/malformed entries may still be skipped by normal canonical rules;
- do not fetch another page even when fewer than 20 entries materialize;
- latest message ID still advances from provider entries;
- backfill cursor becomes/remains None;
- history complete becomes true;
- do NOT create a 14-day `history_cutoff_at`;
- if `history_cutoff_at` was already set for some retained legacy state, preserve it rather than overwriting it.

### Scope mode — existing peer

Given positive `history_latest_message_id`:
- incremental min-id only;
- no historical page;
- do not apply the legacy 14-day cutoff as a reason to discard newer-id provider entries;
- preserve pre-existing `history_backfill_before_message_id`;
- preserve pre-existing `history_complete`;
- preserve pre-existing `history_cutoff_at` exactly.

### Manual path

`sync_group` remains unchanged:
- existing 14-day cutoff semantics;
- existing bounded backfill;
- existing cursor behavior.

## Suggested implementation shape

Keep the change small.

For scope mode, use a non-time-limiting normalization cutoff, e.g. UTC-aware `datetime.min`, or an equivalent explicit code path that preserves the existing non-time validation while disabling the 14-day filter.

Persist `history_cutoff_at` only according to the manual path; scope mode should preserve its prior value.

Do not change `_normalize_entry` globally in a way that weakens manual history semantics.

## Required regressions

Add tests proving:

1. Fresh scope peer with latest provider entries older than 14 days still materializes those eligible entries.
2. Fresh scope peer with 20 old entries and `has_more=true` still makes exactly one provider fetch.
3. Fresh scope peer leaves `history_cutoff_at=None` when it started None.
4. Fresh scope peer preserves a pre-existing cutoff if one exists.
5. Existing scope peer preserves cutoff/backfill/history-complete state exactly.
6. Existing scope peer does not discard an incremental newer-id entry solely because its timestamp is older than 14 days.
7. Manual initial sync still filters entries older than the 14-day cutoff as before.
8. Manual backfill behavior remains unchanged.
9. Existing M4AY1 exact limit/direction/bounds/call-count tests remain.
10. Recurring remains `scope_active=true` only.
11. Q1 AI quarantine remains unchanged.
12. No schema/Alembic change.
13. Provider taxonomy unchanged.

Because the executor DB host is currently unavailable, add at least one **DB-independent focused unit test** that proves the scope-mode cutoff decision itself is non-time-limiting, so the core regression can actually execute in the local environment. Do not claim DB-backed PASS if PostgreSQL still cannot initialize.

## Validation

Run:
- DB-independent focused M4AY1R unit test(s);
- collect/run the DB-backed A3/A4.2/A4.4/Q1 matrix as available;
- Python compile;
- Ruff;
- `git diff --check`.

If PostgreSQL remains unavailable:
- report exact number of DB-backed tests collected/blocked;
- do not use production DB.

## Strictly forbidden

Do NOT:
- deploy;
- move production ref;
- production SSH;
- live Telegram/provider calls;
- live Sync;
- folder save/preview/Apply Scope;
- login/re-login;
- production mutation;
- migration / `0047`;
- AI enable;
- Bot API changes.

## Deliverable

If corrected:
- commit/push canonical main;
- update `PROJECT_STATE.md`;
- do NOT deploy.

Report:
- corrective commit SHA;
- exact files changed;
- exact scope cutoff semantics;
- DB-independent test result;
- DB-backed test status;
- manual path unchanged;
- recurring scope-only unchanged;
- Q1 unchanged;
- Ruff/diff-check;
- production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_M4AY1R_SCOPE_COUNT_BOUND_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
