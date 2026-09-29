# Current task — PC1-H1: fail-closed Task actor/evidence preservation

## State

- PC1 implementation under review: `47df2709472fc120cb78e61d2fe309a455bdd636`.
- Production/runtime/origin-production remains `9aaeb8db1a04851bcae17aa50f9a4d185c2753bb`.
- Alembic remains `0051`.
- Architect review found correctness blockers in merge reuse/preservation semantics.
- Do not deploy PC1 until H1 is accepted.

## Goal

Make Person consolidation strictly fail closed when an existing survivor Task actor fact or evidence row is not semantically equivalent to what would be transferred.

PC1 must never silently drop, weaken, or reinterpret explicit Task->Person facts or identity evidence merely to complete a merge.

## A. Exact Task actor preservation

For every non-rejected duplicate Task->Person actor edge admitted by preview:

- source must be an active same-user `Object(kind=task)`;
- role must be one of `requested_by`, `delegated_to`, `waiting_on`, `involves`;
- if survivor has no non-rejected edge for the same Task+role, apply may create an exact copy preserving:
  - state;
  - origin;
  - confidence;
- if survivor already has a Task+role edge, reuse is allowed only when it is semantically equivalent for PC1.

For H1, define equivalent conservatively as same:
- Task id;
- role;
- state;
- origin;
- confidence.

If a survivor edge for the same Task+role exists but differs in any of those fields, preview must return `can_merge=false` with a bounded blocker and apply must fail closed.

Do not auto-upgrade proposed->confirmed.
Do not reject/replace pre-existing survivor actor edges.
Do not reconcile confidence/origin differences.
That belongs to Task-relation semantics, not Person consolidation.

### Hidden/tombstoned Task

A duplicate actor edge whose source Task is hidden, tombstoned, rejected, cross-user, or otherwise not an active same-user Task must block the merge.

Do not silently skip it in apply.

Every actor edge counted in a mergeable preview must either:
- already have an exactly equivalent survivor fact, or
- be successfully copied exactly during apply.

If not, abort the whole transaction before duplicate tombstone.

## B. Evidence reuse must be genuinely equivalent

The DB active-evidence unique signature is:

`user + person + provider + identity_type + realm + canonical_value + evidence_type + polarity + provenance_key`.

Current PC1 may reuse a survivor row with that signature even if payload fields differ.

When duplicate evidence meets an existing survivor row with the same DB-unique signature, treat it as reusable only if the preservation payload is also equal:

- weight;
- provenance_kind;
- source_object_id;
- explanation;
- details.

If any differs, preview must block merge and apply must fail closed.

Do not overwrite the survivor row.
Do not discard the duplicate evidence.
Do not invent a second active row that violates the existing unique constraint.

## C. Apply-time revalidation

Apply already re-runs assessment; preserve that behavior.

After assessment and before duplicate tombstone:

- do not use a broad boolean helper that merely asks whether a Task+role exists;
- explicitly verify/create every assessed actor fact;
- any unexpected divergence/failure aborts the nested transaction;
- duplicate remains active and identities/evidence/edges remain as before.

No partial merge.

## D. Undo

Existing undo semantics should remain unchanged for successful H1 merges.

Because H1 blocks divergent pre-existing actor/evidence state up front, undo must continue to remove/retract only merge-created rows and never mutate pre-existing survivor facts.

## Required backend regressions

At minimum add:

1. duplicate confirmed Task role + survivor proposed same Task/role -> preview blocked, apply blocked, no mutation;
2. duplicate proposed + survivor confirmed same Task/role -> preview blocked under conservative exact-equivalence rule;
3. same Task/role/state/origin/confidence on both -> merge allowed and no duplicate survivor edge;
4. same Task/role but different confidence -> blocked;
5. same Task/role but different origin -> blocked;
6. duplicate actor edge from hidden/tombstoned Task -> blocked;
7. duplicate actor edge from rejected Task -> blocked where representable;
8. no survivor actor edge -> exact state/origin/confidence copied;
9. actor-copy failure aborts entire merge and duplicate remains active;
10. existing evidence same DB signature + same preservation payload -> reusable;
11. same DB signature but different weight -> blocked;
12. different provenance_kind -> blocked;
13. different source_object_id -> blocked;
14. different explanation/details -> blocked;
15. conflict/block preview remains read-only;
16. existing PC1 identity transfer, audit, idempotence, safe undo, divergent-undo, salience attribution tests remain green.

No Alembic migration. Head remains `0051`.

## Flutter

No product UX redesign is expected.

If blocker strings are surfaced in preview, ensure the existing merge dialog:
- disables final confirmation;
- shows a concise user-readable blocker;
- does not overflow.

Run focused consolidation Flutter tests. No new broad UI work.

## Verification

Run:
- `test_person_consolidation.py`;
- relevant TaskRelationService tests;
- Person identity/evidence/People workspace suites used by PC1;
- focused People consolidation Flutter tests;
- Ruff;
- touched Dart analyze if Dart changes;
- `git diff --check`.

Report unrelated existing Graph failures separately only if the suite is run.

## Explicitly out of scope

- No production deploy.
- No migration.
- No new merge capability.
- No actor-state reconciliation.
- No Task relation inference.
- No raw Person delete.
- No Task↔Person visualization.
- No People Landscape.
- No Secretary Person context.
- No social/organization ontology.
- No MCP/G3B/S3.

## Completion

1. Commit the narrow H1 correction + regressions.
2. Update `PROJECT_STATE.md` with exact behavior/tests/SHA.
3. Return `CURRENT_TASK.md` to HOLD with:
   - PC1-H1 source ready / human gate pending;
   - production still `9aaeb8db1a04851bcae17aa50f9a4d185c2753bb`;
   - Alembic still `0051`.
4. Push implementation + HOLD to `main`.
5. Report exact SHAs/tests and STOP.

Do not deploy.
