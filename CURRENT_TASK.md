# CURRENT_TASK

ACTIVE

## REL1D-HG3.2.2 — prevent stale rooted-Person detail loads from overwriting newer task-role mutations

### Context

Architect review of HG3.2.1 implementation `72c9f50f8a8fba1c3719f6ae3939b5afbf0fa4c8` confirmed that the two explicitly authorized HG3.2.1 defects were fixed correctly.

One adjacent client-side stale-read race remains:

1. controller re-roots to Person B and already receives a full rooted People-workspace response containing authoritative Person truth;
2. `_trackPersonSelection` still starts a second `_loadRootedPerson(B)` request;
3. `_adoptCenteredPerson` can expose the controller's already-fetched rooted Person B while that duplicate request remains in flight;
4. user performs a successful Task actor mutation for B;
5. the local HG3.2 actor patch immediately shows the correct newer state;
6. the older duplicate `_loadRootedPerson(B)` response can later return and overwrite `_rootedPerson` because that path is guarded by `_rootedToken` but not by the task-mutation generation.

This violates the accepted invariant that an older People response must never overwrite a newer confirmed Task actor mutation.

### Goal

Eliminate the redundant rooted-Person detail fetch when rooted controller truth is already available, and make every remaining `_loadRootedPerson` request stale-safe with respect to newer Task actor mutations.

### Required behavior

1. When the selected Person is already the controller root and `controller.personFor(personId)` is available from the rooted People workspace:
   - adopt that PersonPresentation directly;
   - do not start a second `GET /graph/people-workspace?root_id=<same person>` merely to populate the detail card.

2. Selecting a Person from a non-rooted People overview/search must still fetch rooted Person truth when no authoritative rooted controller presentation is already available.

3. Any `_loadRootedPerson(personId)` request that is started must capture the current Person task-mutation generation.

4. If a successful Task actor mutation increments the generation before that request returns:
   - the older detail response must not replace `_rootedPerson`;
   - it must not revert task-involvement rows;
   - it must not revert the reconciliation warning/error state;
   - it must not make the UI appear older than the confirmed mutation.

5. Existing `_rootedToken` supersession behavior for Person switches/retries remains.

6. A late detail response for Person A must never update Person B.

7. Preserve all accepted HG3.2/HG3.2.1 behavior:
   - mutation result is applied only after successful server response;
   - add/remove/confirm/reject visible feedback is immediate after that response;
   - background reconciliation stays at most one in flight and follows the latest explicit pending target;
   - stale reconciliation generations do not overwrite newer mutations;
   - authoritative `openTaskCount` is preserved during local actor-list patching;
   - background reconciliation may later replace it with the backend value;
   - duplicate Task-title disambiguation remains unchanged.

### Explicitly out of scope

Do NOT:

- redesign the People workspace;
- change backend/API/schema contracts;
- introduce polling, fixed delays, or timers;
- change Task actor semantics;
- change PersonRole semantics;
- modify role-import image extraction;
- deploy/install anything;
- touch production data;
- resume historical HG2 repair/backfill;
- refactor unrelated Person-detail refresh paths merely for cleanup.

Prefer a client-only corrective limited to the rooted Person detail load/adoption path and focused tests.

### Required tests

At minimum add/update focused Flutter tests proving:

1. Re-rooting to Person B with a rooted People-workspace response does not trigger an immediate duplicate rooted People-workspace fetch solely for the detail card.

2. Non-root Person selection still performs the rooted detail fetch needed to obtain truth data.

3. A delayed `_loadRootedPerson(B)` response started before a successful B Task actor mutation cannot restore the pre-mutation actor row after the mutation response has been applied.

4. A delayed Person A detail response cannot alter Person B after switching.

5. Existing A->B pending reconciliation test remains green.

6. Existing delayed add/remove/confirm/reject, foreground failure, reconciliation failure, latest-generation, linked-task count, and duplicate-label tests remain green.

Run the smallest focused Flutter suite covering these contracts. Run formatting/analyzer checks appropriate for touched Dart files and `git diff --check`.

### Completion protocol

When implementation and required checks are green:

1. update `PROJECT_STATE.md` with a concise factual HG3.2.2 implementation/test entry;
2. replace this file with `HOLD`, recording implementation SHA and checks;
3. commit + push to canonical `main`;
4. STOP.

Do not start raster role-import extraction or any other phase.

Production/backend remains:
`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic remains:
`0054 / 0054`

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
