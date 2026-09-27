# Current task — Graph G3A-R1: fresh relayout after Task-to-Task topology mutation

Graph G3A and its production human gate are ACCEPTED.

Production application/runtime and `origin/production` remain:
`489741540e30a775e2ea086f3976d7305512afe2`

Alembic remains:
`0050`

This task authorizes one bounded CLIENT Graph corrective on `main` only.

NO production deploy is authorized.
Do not start the reversible `Показать связи` / `Скрыть связи` corrective.
Do not start G3B, S3, or H2D.

## Human evidence

On exact R4 client, the human created a structural relation attaching Task/Direction “Публикации в научной прессе” under Direction “Академ”.

Persistence/topology updated, but geometry became stale:

- the Direction anchor moved;
- already-positioned Task cards stayed at their previous coordinates;
- long relation rays crossed the map;
- switching app tabs did not repair geometry;
- pressing fit-to-view did not repair geometry.

A full fresh overview/restart is expected to repair it.

## Confirmed root cause

Current client relation write path:

1. `createRelation(...)`;
2. `mergeRelationContext(...)`;
3. optimistic `_stageCreatedRelation(...)`;
4. rooted fetch;
5. `_mergeWorkspace(...)`;
6. `GraphLayout.computePositions(... existing: _positions, freshRoot: false)`.

In `GraphLayout._layoutOverview`, when `freshRoot == false` and existing positions are non-empty, existing nodes are treated as fixed geography. Only newcomers are positioned; already-positioned nodes are not recomputed after topology changes.

Therefore a new Task<->Task edge can change graph connectivity while the old geometry is retained.

Fit-to-view changes only the camera transform and cannot repair stale node coordinates.

## Product invariant

**A mutation that changes visible Task-to-Task topology invalidates Task geometry.**

After a successful map-visible Task<->Task relation activation/deactivation:

- authoritative workspace membership must be refreshed;
- the affected current overview/rooted workspace must receive a FRESH layout;
- stale Task coordinates must not be preserved merely for geography stability;
- the controller should request one fit after that fresh layout.

Task<->Flow evidence writes remain incremental and should NOT cause whole-window relayout.

## What counts as topology-invalidating in this task

A relation mutation is topology-invalidating when:

- both endpoints are `kind=task`; and
- the relation is visible on the Tasks map under the existing canonical relation presentation.

This includes Task<->Task:
- `part_of`;
- `related_to`;
- `references`;
- `depends_on`.

Do not add new relation types.

### Extra rule for `part_of`

`part_of` additionally changes semantic constellation membership.

After `part_of` activation/deactivation:
- refresh semantic-window membership from the backend;
- refresh window metadata (`window_index`, `window_count`, previous/next flags, constellation roots);
- do not rely on the pre-mutation in-memory node set.

## Part A — relation creation

After the server successfully creates a relation:

### Task<->Task map-visible relation

Do NOT use the ordinary optimistic `_stageCreatedRelation + _mergeWorkspace(freshRoot:false)` path as the final state.

Instead:

- refresh the authoritative current workspace;
- replace/rebuild its Graph state;
- compute positions with fresh layout semantics;
- request fit after layout;
- preserve current Preserve/Relax mode.

### Task<->Flow or other non-topology relation

Keep the existing incremental merge behavior unless a focused regression proves it broken.

Do not move unrelated Task anchors for ordinary Flow evidence addition.

## Part B — user relation deletion

Current user relation deletion calls:

`deleteRelation(edge.id)` -> `controller.removeEdge(edge.id)`

For topology-invalidating Task<->Task relations, this is insufficient because removing an edge can split components/constellations while old coordinates remain.

After successful server deletion:

- refresh authoritative current workspace;
- fresh relayout;
- refresh semantic-window metadata for `part_of`;
- do not leave a stale disconnected spatial arrangement.

For ordinary Task<->Flow relation deletion, keep the smallest existing behavior unless needed for correctness.

## Part C — proposed relation decisions

Current agent proposal decision may activate or deactivate an edge.

When confirming or rejecting a topology-invalidating Task<->Task relation:

- run the same authoritative refresh + fresh relayout contract.

At minimum cover:
- proposed Task<->Task `part_of` -> confirm;
- proposed Task<->Task `part_of` -> reject when it had been locally represented;
- map-visible Task<->Task non-`part_of` decisions where applicable.

Do not change provenance/state transition semantics.

## Part D — overview refresh semantics

When current mode is Tasks overview (`rootId == null`):

- prefer refreshing the current semantic `windowIndex`;
- replace the old workspace rather than merge;
- preserve selection only if the selected object is still present;
- request fit after fresh layout.

A `part_of` mutation can change window packing/window count.

If the previous `windowIndex` is no longer valid after the mutation:
- recover deterministically to a valid overview window (window 0 is acceptable for this corrective);
- do not leave the controller in an error/stale geometry state.

Do NOT scan production data client-side.
Do NOT add a new backend “find window by object” API in this task.

## Part E — rooted refresh semantics

When current Graph state is rooted:

- refresh the authoritative rooted workspace;
- replace existing geometry with a fresh rooted layout;
- keep the root selected when it still exists;
- request fit.

Existing rooted Task behavior from G3A remains:
- complete semantic constellation first;
- bounded ordinary context after it.

Rooted non-Task behavior remains unchanged apart from fresh geometry after a topology-invalidating relation mutation involving visible Task endpoints.

## Part F — layout invalidation boundary

Do NOT globally change `GraphLayout.computePositions` so every incremental update becomes fresh.

Preserve the accepted stable-geography behavior for:
- ordinary Flow satellite admission;
- `Показать связи` local evidence expansion;
- non-structural newcomers;
- bookmarks;
- selection/focus;
- ordinary refreshes that do not mutate Task<->Task topology.

Implement an explicit controller-level topology invalidation path.

It is acceptable for this corrective to fresh-relayout the WHOLE CURRENT SEMANTIC WINDOW after Task<->Task topology mutation. G3A bounds that window and makes this safe.

Do not attempt a complex minimal subgraph relayout unless it is demonstrably simpler and fully tested.

## Part G — fit-to-view semantics

Do not redefine the fit button.

The fit button remains camera-only.

After a topology-invalidating mutation:
1. fresh geometry is computed first;
2. then `shouldFitAfterLayout` requests one camera fit.

Add a regression proving that geometry changes before fit; the fix must not merely zoom out to hide long rays.

## Part H — failure behavior

The relation write may succeed on the server while the follow-up workspace refresh fails.

Do not pretend the write failed if persistence already succeeded.

Use a clear recoverable UI error in substance:

`Связь сохранена, но граф не удалось обновить. Обновите обзор.`

Requirements:
- do not rollback persistence client-side;
- do not continue optimistic stale Task geometry as if authoritative;
- keep a retry path through existing overview/root refresh;
- no automatic repeated network loop.

## Client regression requirements

Add focused tests covering at least:

1. **part_of creation between two already-positioned Task constellations**
   - old positions exist;
   - relation succeeds;
   - authoritative overview is refetched;
   - workspace state is replaced, not merged;
   - fresh positions are recomputed;
   - long stale geometry cannot survive;
   - fit is requested.

2. **part_of changes semantic window metadata**
   - old page metadata differs from refreshed response;
   - controller adopts refreshed metadata.

3. **invalid old window after part_of**
   - refresh of prior window is out of range;
   - controller deterministically recovers to window 0;
   - no stale state remains.

4. **Task<->Task related_to/references/depends_on**
   - map-visible topology mutation also gets fresh relayout.

5. **Task<->Flow control**
   - existing incremental path remains;
   - already-positioned unrelated Task anchors are preserved.

6. **delete part_of**
   - successful deletion refreshes and fresh-relayouts the split topology.

7. **proposal decision**
   - confirming/rejecting a Task<->Task structural proposal invokes topology refresh.

8. **rooted mode**
   - topology mutation refreshes rooted workspace with fresh geometry and keeps root when valid.

9. **refresh failure after successful write**
   - persistence success is not reported as persistence failure;
   - recoverable Graph refresh error is exposed;
   - no retry loop.

10. **fit is not the fix**
    - existing fit transform behavior remains camera-only;
    - mutation path itself invalidates/recomputes geometry.

Run relevant existing client tests:
- Graph workspace controller;
- Graph workspace/screen;
- semantic-window G3A;
- relation creation/deletion/decision;
- map relation presentation;
- part_of;
- G1R;
- hybrid/focus LOD.

Run Flutter analyze on touched client files.
Run Linux debug build.
Run `git diff --check`.

The three documented object-detail client finder failures are not authorization to modify unrelated code.

## Backend

No backend product change is expected.

If implementation discovers a backend contract defect is required to solve this correctly:
- STOP;
- report the exact missing contract;
- do not widen scope.

No schema/Alembic changes.

## Explicitly forbidden

Do NOT:

- deploy;
- move `origin/production`;
- inspect/mutate production user data;
- add migration;
- add raw Node Limit setting;
- implement `Скрыть связи`;
- implement pan-trigger loading/G3B;
- alter semantic-window packing;
- change G2 priority predicate;
- change relation semantics;
- change Preserve/Relax product meaning;
- change saved API URL precedence;
- start S3;
- start H2D;
- fix unrelated failures.

## Completion

On completion:

1. update `PROJECT_STATE.md` with:
   - confirmed client root cause;
   - exact topology invalidation predicate;
   - refresh/fresh-layout behavior;
   - part_of window metadata behavior;
   - failure behavior;
   - exact tests/analyze/build results;
   - implementation SHA;
   - whether the corrective is client-only and schema-neutral;
2. return `CURRENT_TASK.md` to HOLD;
3. push implementation/HOLD commits to `main`;
4. do not deploy;
5. STOP.

Final report must state:

- confirmed root cause;
- exact Task<->Task topology-invalidating predicate;
- behavior for create/delete/decision;
- behavior for part_of semantic-window repacking;
- behavior for Task<->Flow;
- failure-after-successful-write behavior;
- client tests/analyze/build;
- whether backend product code changed;
- implementation SHA;
- HOLD/main SHA;
- rollout requirement.

Then STOP. Do not start `Скрыть связи`, G3B, S3, or H2D yourself.
