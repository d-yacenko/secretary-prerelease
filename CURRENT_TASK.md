# Current task — Graph Refined P4R: explicit-confirmation conflict safety

Architect review of P4 implementation `a0bfa2bc256cae628d492bce0a3562f624e48b76` confirms the main enrichment boundary: score/name similarity do not attach identities, explicit confirmation may authorize exact attach, existing conflicting owners are not reassigned, unknown public authors do not create People, and no live provider/model calls exist.

One blocking integrity case remains: multiple active explicit confirmations for the same external identity can be silently collapsed to "no confirmation" by `_confirmed_person()`.

Fix only this confirmation-conflict behavior. Do not start P5.

Do not add UI, Assistant lookup, send-by-person, live provider/directory calls, LLM calls, jobs, migrations, proactive integration, or auto-merge. Do not deploy.

## Problem

P2 evidence permits active `user_confirmed` rows for the same normalized identity tuple against different Person objects.

Current P4:
- queries distinct confirmed Person ids;
- returns a Person only when exactly one exists;
- returns `None` when zero OR multiple exist.

That conflates:
1. no explicit confirmation;
2. contradictory explicit confirmations.

Consequences:
- if an exact identity already has an owner, contradictory confirmation can be hidden and the planner may proceed as ordinary `exact_identity`;
- if there is no owner, contradictory confirmations may fall through to name/direct/unresolved logic instead of explicit fail-closed conflict.

## Required semantics

Replace the single-value confirmation lookup with an explicit confirmation-set/result.

For one normalized identity:

### zero active confirmed People
- existing P4 behavior remains.

### exactly one active confirmed Person
- existing P4 behavior remains:
  - if no owner: explicit confirmation may authorize exact attach to that Person;
  - if owner is same Person: ordinary exact-known path;
  - if owner is another Person: fail closed with explicit identity conflict; never reassign.

### more than one active confirmed Person
- NEVER attach;
- NEVER treat confirmation as absent;
- return a deterministic `needs_confirmation` / conflict candidate;
- reasons must explicitly indicate contradictory/multiple user confirmations, e.g. `multiple_user_confirmations` plus `identity_conflict` where an owner also exists;
- preserve all existing PersonIdentity ownership;
- do not retract or rewrite P2 evidence automatically;
- user correction/reversal remains a later explicit feedback action.

If multiple confirmations exist, candidate output should make the ambiguity explainable. It is acceptable to:
- emit one conflict candidate per confirmed active Person, bounded/deterministic; or
- emit one conflict candidate with no single Person target plus bounded confirmed-Person ids in a safe field if the current domain model is minimally extended.
Prefer the smallest design that keeps the ambiguity visible and testable.

## Active-state rules

Only active, same-user, non-rejected/non-deleted Person targets count as active confirmation holders.

Historical/retracted confirmations remain auditable but do not participate.

## Idempotency

Repeated `plan()` over the same contradictory confirmations:
- must not attach an identity;
- must not create duplicate evidence;
- must return stable deterministic conflict output.

## Focused proof

Add tests proving at minimum:
1. No owner + two active `user_confirmed` People => no attach, explicit multiple-confirmation conflict.
2. Existing owner + owner and another Person both actively confirmed => owner remains unchanged and conflict is surfaced.
3. Existing owner + two other confirmed People => owner remains unchanged and conflict is surfaced.
4. Retraction/rejection that leaves exactly one active confirmation restores normal single-confirmation behavior.
5. Rejected/deleted confirmed Person does not count toward active conflict.
6. Cross-user confirmation cannot participate.
7. Repeated planning is idempotent and deterministic.
8. Existing P4 exact attach, single-conflict, name-similarity, unknown-public, coverage, bounds, and no-provider-call tests remain green.
9. P1/P2/P3 focused tests remain green.

Run:
- `tests/test_person_enrichment.py`;
- P1/P2/P3 focused Graph Refined tests;
- Ruff/compile on touched Python;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose P5 and do not deploy.
