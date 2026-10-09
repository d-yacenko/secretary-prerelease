# CURRENT_TASK

ACTIVE

## REL1D-HG4B — instant Task-actor feedback for a Person selected from unrooted People overview

### Context

HG4A production audit is Architect-accepted.

Source review confirmed a client-only correctness bug:

- a Person selected from the unrooted People overview has `controller.rootId == null`;
- the Person detail card can still load rooted truth for that selected Person;
- `_mutatePersonTaskRole` currently applies the returned server edge only when `_personSurfaceStill(personId)` is true;
- `_personSurfaceStill` requires `controller.rootId == personId`;
- therefore a successful add/remove/confirm/reject mutation for an unrooted selected Person can persist on the server while the visible card remains stale until a later refresh.

HG3.2/HG3.2.1/HG3.2.2 already established the correct foreground/background mutation model for a centered/rooted Person. This task extends that same contract to the normal unrooted overview-selection surface.

### Goal

For a Person selected from People overview without pressing `В центр`, apply successful Task actor mutations to the visible Person card immediately after the server mutation response, then reconcile authoritative rooted Person truth in the background without changing the current overview/root.

### Required behavior

1. Distinguish:
   - **visible Person detail still current**: People mode, the same selected/tracked Person detail card is still visible;
   - **controller is rooted on this Person**: `controller.rootId == personId`.

   Do not require the second condition merely to apply a successful foreground mutation to the first surface.

2. For add/remove/confirm/reject on an unrooted selected Person:
   - while the actual mutation request is in flight, preserve the existing foreground busy cue and block conflicting actor mutations;
   - do not show success before the server response;
   - after a successful response, increment the mutation generation and apply exactly the returned edge to the visible `_rootedPerson.taskInvolvement` immediately;
   - match/update/remove by edge id;
   - preserve unrelated actor rows;
   - preserve the prior authoritative `openTaskCount` until reconciliation.

3. The immediate update must work when:
   - `controller.mode == people`;
   - `controller.rootId == null`;
   - the selected/tracked Person matches `personId`;
   - the detail card was loaded via rooted truth for that Person.

4. A successful unrooted mutation must NOT:
   - call `reRoot`;
   - change `controller.rootId`;
   - replace the unrooted overview workspace with a rooted workspace;
   - discard other overview People;
   - reset the current People overview camera/window/search state merely to update one Person card.

5. Background reconciliation must still fetch authoritative rooted Person truth for the mutated Person.

6. Reuse/generalize the existing single-flight generation-aware Person reconciliation mechanism rather than adding an unrelated second race-control system.

7. When a reconciliation response completes:
   - if the controller is currently rooted on that same Person, preserve the existing rooted install behavior;
   - if the controller is still unrooted and the same Person detail card is selected, update only that Person detail presentation from the rooted response; do not install the rooted workspace into the unrooted controller;
   - if the Person/mode/root surface changed incompatibly, discard the response.

8. The existing stale-response invariants remain:
   - an older reconciliation/detail response cannot overwrite a newer successful mutation;
   - a response for Person A cannot alter Person B;
   - at most one Person reconciliation request is in flight;
   - if a newer successful mutation happens while reconciliation is in flight, coalesce one final reconciliation for the latest target/generation;
   - no unbounded concurrent People-workspace refreshes.

9. Reconciliation failure after successful mutation:
   - must not roll back the local confirmed mutation;
   - must not show the foreground mutation as failed;
   - may show the existing non-blocking warning `Изменение сохранено, обзор обновится позже`;
   - must leave actor controls usable.

10. Foreground mutation failure:
   - preserves previous rows;
   - shows the existing retryable mutation error;
   - must not schedule a fake successful reconciliation.

11. Rooted Person behavior from accepted HG3.2.x must remain unchanged.

12. No backend/API/schema changes are expected or authorized.

### Explicitly out of scope

Do NOT:

- change People overview ranking, limit, paging, or visibility in this task;
- change manual Person creation;
- change Person promotion behavior;
- change Task actor backend semantics or edge direction;
- add relation types;
- modify PersonRole semantics;
- deploy/install anything;
- touch production data;
- call providers/models;
- modify raster role-import extraction;
- resume historical HG2 repair/backfill.

The incomplete People overview is a separate Architect-planned HG4C after HG4B review.

### Expected implementation scope

Prefer changes limited to:

- `client/lib/graph/graph_workspace_screen.dart`;
- focused Person task bridge tests.

Touch `graph_workspace_controller.dart` only if a very small existing-state helper is strictly needed. Do not refactor unrelated graph state.

### Required tests

At minimum add/update focused Flutter tests proving:

1. Open unrooted People overview, select Person A without centering, delay the actor DELETE response:
   - row stays while mutation request is pending;
   - busy cue is visible.

2. Release successful DELETE:
   - exactly that edge disappears immediately;
   - unrelated actor rows remain;
   - controller remains `rootId == null`;
   - delayed background reconciliation may still be held.

3. Successful ADD for an unrooted selected Person appears immediately while existing rows remain and controller stays unrooted.

4. Proposal confirm/reject for an unrooted selected Person applies returned edge state immediately.

5. A delayed background rooted-Person reconciliation for an unrooted selected Person updates authoritative detail truth without re-rooting/replacing the overview.

6. A stale older reconciliation cannot restore an edge after a newer unrooted mutation.

7. If Person A reconciliation is in flight, then Person B is selected unrooted and successfully mutated, exactly one final B reconciliation follows after A finishes; max concurrent reconciliation requests remains 1.

8. Switching away from the Person or leaving People mode before a delayed response returns prevents that response from changing the new surface.

9. Unrooted reconciliation failure preserves the successful local actor mutation and shows only the non-blocking sync warning.

10. Foreground failure preserves prior rows and remains retryable.

11. Prior rooted HG3.2.x tests remain green, including stale detail-load guards, explicit pending reconciliation target, and authoritative `openTaskCount` preservation.

12. Duplicate Task-title disambiguation remains green.

Run the smallest focused Flutter suite covering these contracts. Run Dart formatting/analyzer checks appropriate for touched files and `git diff --check`.

### Completion protocol

When implementation and checks are green:

1. update `PROJECT_STATE.md` with a concise factual HG4B implementation/test entry;
2. replace this file with `HOLD`, recording implementation SHA and checks;
3. commit + push to canonical `main`;
4. STOP.

Do not start People overview paging/HG4C or any other phase.

Production/backend remains:
`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic remains:
`0054 / 0054`

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
