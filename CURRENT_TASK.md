# Current task — PL1-G2 canonical Task geography contract + invalidation

Authorized base: `a0b7ad1bb42716b7525908b3f764cd73dfd4f0e2`.
Production/runtime remains `666683134797948871266e84fd105f0ca0c43476`.
Repository Alembic head is `0052`; production Alembic remains `0051 / 0051`.

PL1-G1 persistence is accepted. This slice closes its pre-public completeness gap, adds a bounded backend contract for canonical Task geography, and wires topology revision invalidation to actual Task-map topology changes. No Flutter/UI changes yet.

## Goal

Expose one authoritative user-scoped Task world-space snapshot contract that is fail-closed when incomplete/stale, plus one complete bounded Task-topology read for the later client layout producer.

## Canonical layout-eligible Task set

For this slice, a layout-eligible Task is:

- owned by the current user;
- `kind == "task"`;
- not rejected;
- not hidden from active reads.

Terminal status alone does **not** remove a Task from canonical geography. Ordinary title/body/due/status edits must not move or invalidate geography.

## 1. Close PL1-G1 completeness semantics

Update `TaskLayoutService` so:

1. `replace_snapshot(...)` accepts a snapshot only when its Task-id set exactly equals the current layout-eligible Task-id set. Empty snapshot is valid only when that set is empty.
2. Validation remains atomic/fail-closed: stale revision, duplicate id, foreign/non-Task id, incomplete/extra current membership, or non-finite coordinate writes nothing.
3. `read().usable` requires:
   - `snapshot_revision == topology_revision`; and
   - every currently layout-eligible Task has a stored center in that snapshot.
4. Historical extra centers for Tasks that later became hidden/rejected/deleted must not by themselves force unrelated remaining geography stale. Current eligible Tasks are the required coverage.
5. Preserve old revision rows on invalidation.

## 2. Additive backend API contract

Add user-scoped schemas/routes under the graph API without changing existing `GraphWorkspaceOut` or `PeopleWorkspaceOut`.

### GET canonical layout

Add a read endpoint such as `GET /graph/task-layout` returning at least:

- `topology_revision`;
- `snapshot_revision`;
- `algorithm_version`;
- `usable`;
- centers `[{task_id, world_x, world_y}]`.

When stale, return the stored previous centers for diagnostics/reuse, but `usable=false`.

### PUT canonical layout snapshot

Add a write endpoint such as `PUT /graph/task-layout` with:

- `expected_topology_revision`;
- non-empty bounded `algorithm_version`;
- full list of Task centers.

Return the resulting layout view.

Map stale-revision conflict to HTTP 409 and validation failures to 422. User ownership must be enforced by current-user context; no cross-user ids/reads.

### GET complete layout topology

Add a bounded endpoint such as `GET /graph/task-layout/topology` returning:

- current `topology_revision`;
- the complete current layout-eligible Task objects needed by the existing client Task layout algorithm;
- Task<->Task edges that currently affect the Task map topology.

Do not include Flow or Person nodes. Do not include rejected/hidden topology. Keep this read bounded with explicit constants and fail closed (422) rather than truncate silently if the complete topology exceeds the cap. Use a Task cap consistent with the current complete graph safety ceiling (500 is acceptable); add a defensible edge cap.

This endpoint is the later PL1-G3 layout producer input. Do not calculate coordinates in the backend.

## 3. Topology invalidation semantics

Create one backend predicate/helper matching the current Task-map topology semantics and use it centrally in mutation paths.

A relation affects Task-map topology only when both endpoints are Tasks and its current presentation state participates in the map:

- rejected relation: does not affect;
- `part_of`: affects only when confirmed;
- the other Task<->Task relation types visible on the Tasks map (including current generic types and supported legacy visible types) affect while non-rejected;
- actor/person/label/temporal/Task<->Flow relations do not affect.

Wire invalidation in the same DB transaction:

1. Creating an affecting Task<->Task relation invalidates once.
2. Deleting an affecting relation invalidates once.
3. Relation state transition invalidates only when the before/after topology participation changes:
   - visible proposed non-`part_of` -> confirmed: no extra invalidation;
   - visible proposed -> rejected: invalidate;
   - proposed `part_of` -> confirmed: invalidate;
   - proposed `part_of` -> rejected: no invalidation.
4. TaskRelationService paths that directly reject edges must pass through the same central state-transition behavior; actor-edge mutations must remain topology-neutral.
5. Creating a new Task invalidates an **existing** layout state/snapshot so the new Task cannot be silently missing. If no layout state exists yet, do not create/increment one merely because Tasks are being seeded before first layout.
6. Ordinary Task field/status edits, Person/actor changes, evidence/Flow links, and reads must not invalidate.
7. Removing/hiding/terminalizing a Task must not opportunistically compact or move unrelated Tasks in this slice. Historical centers may remain.

Add a non-creating invalidation helper if needed so ordinary graph writes do not create layout state before the feature is initialized.

## Explicitly out of scope

- No migration beyond existing `0052`.
- No production migration/deploy.
- No Flutter/API-client changes.
- No Task renderer changes.
- No People renderer changes.
- No viewport persistence.
- No backend layout algorithm.
- No automatic coordinate generation/backfill.
- Do not start PL1-G3.

## Tests

Add focused backend/API tests proving at least:

- subset snapshot is rejected atomically;
- complete current Task set snapshot is usable;
- a newly eligible Task makes an old snapshot unusable and, when layout state already exists, advances topology revision;
- hiding/rejecting/removing a previously positioned Task does not require moving remaining Tasks and does not make coverage of remaining eligible Tasks incomplete solely because an old extra center exists;
- GET layout returns stale centers with `usable=false`;
- PUT layout enforces revision, completeness, ownership, finite coordinates, 409/422 behavior;
- topology endpoint returns the complete eligible Task set and only topology-affecting Task<->Task edges;
- topology cap overflow fails closed, never truncates;
- affecting relation create/delete increments topology revision exactly once;
- non-`part_of` proposed->confirmed does not increment again, proposed->rejected does;
- proposed `part_of` does not affect until confirmed;
- Task actor / Task->Flow evidence / ordinary Task edit or status change does not invalidate;
- cross-user access is isolated;
- Alembic head remains `0052`.

Run focused backend/API tests, relevant existing relation/task tests, Ruff for changed Python files, and `git diff --check`.

## Completion contract

When complete:

- record implementation SHA, changed files, exact test/Ruff/diff results, and known limitations in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-G2 summary;
- commit and push to `main`;
- STOP.

Do not deploy, migrate production, modify the installed client, or begin PL1-G3/later slices without a new explicit authorization in this file.
