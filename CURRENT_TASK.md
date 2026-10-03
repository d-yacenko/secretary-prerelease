# Current task — ACTIVE

## REL1A.1 — preserve Person roles through consolidation

REL1A implementation `e7f1e79dd83e3007bc97a6dff7aa1bd083128d93` is directionally accepted but NOT yet source-accepted because one existing Person lifecycle operation can silently hide the new role truth.

Do only this bounded corrective.

## Verified blocker

Current `PersonConsolidationService` transfers/reconciles:

- PersonIdentity;
- PersonIdentityEvidence;
- Task actor edges;
- bookmark state;

but it does not inspect or preserve `PersonRoleAssignment`.

Therefore, if duplicate Person B has an active role and the user merges B into survivor A:

1. B is tombstoned;
2. B's active role rows remain attached to B;
3. People workspace only projects visible Persons;
4. A does not receive those roles;
5. the role truth effectively disappears from the merged Person.

This violates the meaning of Person consolidation and is a blocking REL1A integration defect.

## Baseline

- REL1A implementation: `e7f1e79dd83e3007bc97a6dff7aa1bd083128d93`
- Executor HOLD before review: `113ec8f786a9642a98e5709c6fe1e34585ed39a7`
- Production: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Production Alembic: `0052 / 0052`
- Repository head schema remains `0053`
- No new migration is allowed in REL1A.1.

## Required consolidation semantics

Extend existing reversible `PersonConsolidationService` to include active Person role assignments.

### Assessment / preflight

For duplicate and survivor, load current-user active role assignments with their RoleTerms.

Semantic assignment identity is:

`(role_term_id, context_key)`

Before mutation:

- compute the survivor's active semantic assignment set;
- compute duplicate's active semantic assignment set;
- exact overlap is not a conflict and must not duplicate;
- distinct duplicate assignments that are missing on survivor are candidates to copy;
- the resulting distinct active survivor assignment count must remain <= `MAX_ACTIVE_ASSIGNMENTS` (16);
- if merge would exceed the cap, preview/apply must fail closed with a clear blocker before any mutation.

Do not compare roles by display text if `role_term_id` is available. RoleTerm is already user-scoped canonical vocabulary.

### Apply

For every active duplicate assignment not already represented by the same `role_term_id + context_key` on survivor:

- create one active assignment on survivor;
- preserve:
  - `role_term_id`;
  - `context_text`;
  - `context_key`;
  - `origin`;
  - `provenance_kind`;
  - `provenance_key`;
  - `source_object_id`;
- do not create a new RoleTerm;
- do not alter the duplicate's original assignment row;
- do not create graph edges or touch importance/salience.

Leaving the duplicate's original role assignment in place is intentional: the duplicate becomes hidden, and the original row is needed for clean reversible undo.

If survivor already has the exact semantic role/context assignment:

- do not create a duplicate survivor row;
- leave the survivor's pre-existing row untouched;
- record enough audit state to make undo deterministic.

### Merge audit

Extend the existing consolidation audit with explicit role information.

At minimum record:

- ids of survivor role assignments created by this merge;
- enough immutable expected fields to verify each created row before undo;
- semantic role/context keys that were pre-existing on survivor if needed for deterministic checks.

Do not put user-visible role text into generic graph edges.

### Undo safety

Undo must remain fail-closed.

Before undo:

- every survivor role assignment created by the merge must still exist;
- it must still belong to the same user/survivor;
- it must still be active;
- its `role_term_id`, `context_key`, `context_text`, origin/provenance/source fields must still match the merge audit.

If a merge-created role assignment was later retracted/changed, undo must fail rather than silently resurrecting ambiguous truth.

On successful undo:

- retract the survivor role assignments that were created only by the merge;
- do not physically delete them;
- do not retract survivor assignments that existed before the merge;
- restore duplicate Person through the existing path;
- duplicate's original role assignments become visible again because they were never mutated.

Repeated merge/undo/idempotent paths must stay compatible with the existing consolidation contract.

## API contract correction

REL1A authorization required assignment responses to expose the owning Person.

Add `person_id` to typed `PersonRoleAssignmentOut` and to the corresponding Flutter model.

It must be present for:

- POST assignment response;
- DELETE/retract response;
- People workspace role assignment projection.

Do not derive it in the client from surrounding UI state when the backend already owns the fact.

## Retract target safety

`PersonRoleService.retract(person_id, assignment_id)` must enforce the same active-Person target boundary as assignment:

- current user;
- `kind=person`;
- not rejected;
- not hidden/deleted.

A stale route to a tombstoned/merged Person must fail closed rather than mutating hidden Person state through the first-party endpoint.

Cross-user and mismatched person/assignment ids must remain 404/fail-closed.

Internal consolidation undo may manipulate merge-created role rows directly inside the consolidation transaction if needed; do not weaken the public service boundary to support undo.

## Required tests

Add focused deterministic tests proving at least:

1. **duplicate-only role survives merge**
   - B has `директор · Arenadata`;
   - A does not;
   - merge B -> A;
   - A workspace exposes that role;
   - B is hidden;
   - no new RoleTerm is created.

2. **overlap dedupes**
   - A and B both have same RoleTerm + same context key;
   - merge creates no second active assignment on A.

3. **different contexts remain distinct**
   - A has `директор · Arenadata`;
   - B has `директор · МГУ`;
   - merge leaves both active on A.

4. **cap preflight**
   - survivor + distinct duplicate roles would exceed 16;
   - preview/apply fail before Person/identity/role mutation.

5. **undo**
   - merge-created survivor role is retracted on undo;
   - duplicate original role becomes visible again;
   - survivor pre-existing overlapping role is not retracted.

6. **undo stale fence**
   - retract or otherwise invalidate a merge-created survivor role after merge;
   - undo fails closed.

7. **merge idempotence**
   - repeated apply of established merge does not create another role assignment.

8. **assignment response shape**
   - POST, DELETE, and workspace projection include exact `person_id`.

9. **retract active-Person boundary**
   - rejected/deleted/merged-away Person cannot be mutated through public retract API;
   - normal active Person retract remains idempotent.

10. Existing Person consolidation identity/evidence/Task actor/bookmark tests remain green.

Also rerun:

- `backend/tests/test_rel1a_person_roles.py`;
- Person consolidation suite;
- Person workspace suite;
- SEM1 relation boundary;
- focused Task relation regressions;
- focused Flutter role/model/API tests;
- analyze changed client files;
- Linux debug build;
- Ruff;
- `git diff --check`.

Record exact counts.

## Explicit non-goals

Do not:

- change Alembic 0053 or add 0054;
- change RoleTerm lexical normalization;
- add semantic synonym merging;
- change role autocomplete UX except what is required for `person_id` model compatibility;
- change PersonalRelevance or Proactive;
- add Assistant role tools;
- add screenshot/document import;
- add Organization;
- change Scheduled Activity;
- deploy/migrate production;
- install client;
- call real model/provider.

## Completion protocol

After correction:

1. append compact REL1A.1 result to `PROJECT_STATE.md`;
2. return `CURRENT_TASK.md` to HOLD with:
   - corrective implementation SHA;
   - exact merge/undo role semantics;
   - exact test counts;
   - confirmation schema head remains 0053;
   - production remains `2314bf72101fbd83d50a7b264154d73740e28db1`, Alembic `0052 / 0052`;
   - no deploy/migration/client install/model/provider call;
3. commit + push `main`;
4. STOP.

Do not start REL1B/REL1C/REL1D from HOLD.
