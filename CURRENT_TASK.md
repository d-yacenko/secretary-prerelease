# CURRENT_TASK

ACTIVE

## REL1D-HG3.2.1 — preserve latest Person reconciliation target and authoritative linked-task count

### Context

Architect review of HG3.2 implementation `462a4c5102e68153c5dd6e320383b8585f3b85d3` found two narrow client-side correctness defects. The overall HG3.2 architecture is accepted in direction; only these defects are authorized for correction.

### Defect A — reconciliation target can be lost across Person switch

Current coalescing stores only a boolean `_personReconcileAgain`.

Failure scenario:

1. Person A has a People-workspace reconciliation in flight.
2. User switches directly to Person B.
3. A Task actor mutation for B succeeds.
4. `_kickPersonReconcile(B)` sees reconciliation active and sets only `_personReconcileAgain=true`.
5. A's request finishes.
6. `finally` clears the boolean and attempts the follow-up using A's `personId`.
7. Because A is no longer current, no follow-up runs.
8. B's successful mutation never receives its required final authoritative reconciliation.

The stale A response is already correctly prevented from applying; that behavior must remain.

### Defect B — local openTaskCount is derived from an incomplete subset

HG3.2 currently recalculates:

`openTaskCount = distinct taskId values in taskInvolvement`.

That is not the backend contract.

Backend `PersonGraphWorkspaceService._open_task_count` counts distinct active Tasks linked to the Person by any active/non-rejected Task edge. `taskInvolvement` contains only the canonical Task actor roles.

Therefore the immediate local actor-list patch must not replace an authoritative global linked-task count with a value derived from actor rows only.

### Goal

Keep HG3.2 instant foreground feedback, while making background reconciliation lossless across Person switches and keeping the linked-task count truthful.

### Required behavior

1. Replace targetless reconciliation coalescing with an explicit pending target that identifies at least:
   - `personId`;
   - mutation/reconciliation generation.

2. At most one People-workspace reconciliation may be in flight.

3. If another successful actor mutation occurs while reconciliation is in flight:
   - replace/coalesce the pending target with the latest successful mutation target;
   - do not start another concurrent request.

4. When the current in-flight reconciliation finishes, start exactly one follow-up for the latest pending target when that target is still relevant/current.
   - This must work when the pending target belongs to a different Person than the request that just finished.
   - Do not reuse the completed request's Person id for the pending target.

5. A stale response must still never overwrite:
   - a newer mutation generation;
   - a different current Person/root/mode.

6. Direct switching Person A -> Person B must invalidate A's surface state appropriately. A late A response must not alter B.

7. If A reconciliation is held, the user switches to B, a B actor mutation succeeds, and A later completes:
   - B's local mutation remains visible;
   - A's response is ignored for B;
   - one B reconciliation is subsequently executed;
   - no unbounded/concurrent reconciliation requests occur.

8. During immediate local actor-list patching, preserve the existing authoritative `PersonPresentation.openTaskCount`.
   - Do NOT recompute it from `taskInvolvement`.
   - The later authoritative People-workspace reconciliation may replace it with the backend value.

9. Do not change the backend `_open_task_count` contract and do not add API/schema fields merely to make the count update immediately.

10. Preserve all accepted HG3.2 behavior:
   - no optimistic success before server mutation response;
   - immediate add/remove/confirm/reject card update after successful response;
   - foreground busy clears after mutation response;
   - unrelated actor edges preserved;
   - foreground failure remains retryable;
   - reconciliation failure does not roll back a successful mutation;
   - duplicate Task title disambiguation remains unchanged.

### Explicitly out of scope

Do NOT:

- redesign People workspace;
- add polling or timers;
- add arbitrary delays;
- change Task actor backend semantics;
- change relation decision semantics;
- add schema/Alembic changes;
- change API response contracts;
- modify PersonRole assignments;
- modify role-import image extraction;
- deploy/install anything;
- touch production data;
- resume historical HG2 repair/backfill.

Prefer a client-only corrective.

### Required tests

At minimum add/update focused tests proving:

1. With Person A reconciliation held, switch directly to Person B, perform a successful B actor mutation, then release A:
   - A response does not apply to B;
   - exactly one B reconciliation follows;
   - max concurrent People-workspace requests remains 1.

2. If more than one successful mutation occurs while reconciliation is in flight, only the latest pending reconciliation target/generation is eventually reconciled.

3. Switching away without a newer mutation does not cause an unnecessary follow-up reconciliation.

4. Immediate local add/remove actor patch preserves the prior `openTaskCount` even when actor-row distinct Task count differs.

5. Latest authoritative reconciliation replaces `openTaskCount` with the server value.

6. Existing HG3.2 delayed add/remove/confirm/reject, stale-generation, failure, and duplicate-label tests remain green.

Run the smallest focused Flutter test set covering these contracts. Run formatting/analyzer checks appropriate for touched Dart files and `git diff --check`.

### Completion protocol

When implementation and required checks are green:

1. update `PROJECT_STATE.md` with a concise factual HG3.2.1 implementation/test entry;
2. replace this file with `HOLD`, recording implementation SHA and checks;
3. commit + push to canonical `main`;
4. STOP.

Do not start the raster role-import extraction follow-up or any other next phase.

Production/backend remains:
`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic remains:
`0054 / 0054`

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
