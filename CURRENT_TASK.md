# Current task — TL2.1 sibling ordering + complete-flower human correction

Authorized base: `3648d25c4271fa8fd49a8be857a2dbda604ed293`.
Accepted TL2 implementation under human review: `e98435fa492b3f362122f752df08bb81b573e423`.
Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`.

Human review of TL2: **major visual improvement, but human gate is not fully closed yet**.

Observed on the real Academic map:
- recursive local flowers are visibly better overall;
- page/window splitting still tears two publication petals away from their parent flower; this is expected to be solved later by Semantic Windows v2 and is NOT part of TL2.1;
- a long dashed Task↔Task relation between «Трудоустройство в МФТИ» and «Преподавание Java в МФТИ» remains unnecessarily long even though both local positions could be reordered to shorten it;
- the upper-left Publications flower looks like a rightward tail in area 1. Because two publication petals are currently on area 2, do **not** treat that screenshot alone as proof of a canonical TL2 geometry defect. The complete canonical flower must be validated before changing its geometry.

## Root cause to correct

Current `_arrangeChildren` explores only:
- baseline sibling order;
- fully reversed sibling order;
- four global spins.

`_tuneRotations` can rotate a child **subtree**, but a leaf child has no internal geometry to rotate.

Therefore a confirmed secondary edge between two leaf siblings cannot make those leaves become adjacent unless they already happen to be adjacent in the baseline/reversed order.

That is the TL2.1 defect.

## Goal

Allow deterministic, bounded **sibling module reordering** so confirmed secondary Task↔Task relations can shorten avoidably long lines while preserving recursive `part_of` locality, compact flowers, and non-overlap.

This is still canonical Task presentation geography. No ontology change.

## Required behavior

### 1. Bounded deterministic sibling-order optimization

For each confirmed `part_of` parent with 2+ child modules:

- start from deterministic baseline sibling order;
- permit child modules to change circular order, not only full reversal;
- evaluate confirmed visible secondary Task↔Task relations among nodes inside the local parent frame;
- choose a deterministic order/orientation that reduces the total relevant Euclidean edge length where possible.

Do not use unbounded factorial search.

Use a bounded deterministic method appropriate for typical fan-out, for example:
- exact permutations only below a very small safe threshold;
- otherwise deterministic local search / pairwise swaps / insertion moves / 2-opt with a fixed pass/iteration cap.

Implementation choice is yours, but runtime must stay bounded and deterministic.

### 2. Preserve structural locality

Sibling reordering may move whole child modules around the parent but must not:

- detach descendants from their `part_of` parent;
- stretch direct structural edges merely to satisfy a weak secondary edge;
- break subtree envelopes apart;
- introduce Task-card overlap;
- let Flow/People influence Task centers.

A child subtree moves/rotates as a module.

### 3. Secondary relations used for optimization

Only **confirmed** visible Task↔Task relations may influence this reordering.

At minimum:
- `depends_on`
- `references`
- `related_to`

Rejected and proposed edges must not influence canonical geography.

`part_of` remains the structural constraint, not part of the weak secondary objective.

If several candidate orders have the same secondary score within tolerance, prefer the deterministic baseline-nearest order rather than arbitrary churn.

### 4. Complete-flower sanity check

Add a fixture matching the human Publications case:

- one parent;
- 5 direct leaf Tasks;
- no secondary edges.

Prove the **complete canonical set of five** is approximately distributed around the parent rather than collapsing into one narrow angular tail.

Do not optimize against a partial semantic window here. The fixture must use all five children because page/window slicing is out of scope.

This is a sanity guard only. If current TL2 already passes it, preserve the behavior rather than changing geometry unnecessarily.

## Algorithm version

This correction changes canonical Task coordinates.

Bump:
- `task-map-v2` -> `task-map-v2.1`

A usable `task-map-v2` snapshot must therefore be recomputed once into a complete v2.1 snapshot through the existing topology + optimistic PUT path.

No schema/Alembic change.

## Required regression fixtures

### A. Leaf-sibling secondary edge

Create one parent with at least 6 equal leaf children.

Choose two children that are far apart in the deterministic no-secondary baseline and connect them with confirmed `depends_on`.

Prove:
- their distance is materially shorter with the edge than without it;
- ideally they become adjacent or near-adjacent on the flower;
- all children remain at the local structural radius;
- no Task rect overlaps;
- the parent remains the structural parent of every child.

This fixture must fail under the old baseline/reverse-only search.

### B. Multiple secondary links

Use one parent with several leaf/module children and at least two confirmed secondary links.

Prove the chosen ordering reduces total secondary-edge length compared with baseline while remaining deterministic.

Do not require a mathematically global optimum.

### C. Mixed leaf + subtree modules

A parent has:
- several leaf children;
- one child with its own local descendants.

Allow sibling reordering, but prove:
- the nested child subtree remains intact;
- its internal child distances remain local;
- no envelope/card overlap is introduced.

### D. Five-leaf no-link flower

Complete 5-child flower, no secondary links.

Prove angular spread covers the circle reasonably and does not collapse into one narrow sector. Avoid brittle exact coordinates.

### E. Snapshot replacement

Prove:
- usable `task-map-v2` is not reused by v2.1;
- complete topology is fetched and one complete `task-map-v2.1` snapshot is written;
- usable v2.1 is reused;
- stale PUT retry/fail-closed behavior remains unchanged.

## Preserve existing TL2 behavior

Keep green:
- recursive local flowers;
- branch-growth locality;
- deep hierarchy locality;
- subtree envelope separation;
- Flow/People exclusion from canonical Task geography;
- Tasks/People shared world/camera;
- GFX-A duplicate-title disambiguation;
- GFX-B drag-created canonical `part_of`;
- GFX-C rename and relation-picker scroll;
- Graph smoke/large-canvas;
- People anchors/clusters/shelf/cue.

## Human-check build is part of TL2.1

After implementation/tests pass, build a fresh self-contained Linux debug bundle from a clean detached checkout of the exact TL2.1 implementation SHA.

Record:
- exact source SHA;
- UTC build time;
- executable path;
- launcher SHA-256;
- kernel SHA-256 if present;
- adjacent `BUILD_INFO.txt`.

Human checklist:
1. Compare «Трудоустройство в МФТИ» ↔ «Преподавание Java в МФТИ»: the dashed relation should become clearly shorter if a sibling reorder can achieve that.
2. Confirm the Teaching flower still looks compact and coherent.
3. Confirm Publications canonical flower has not become worse.
4. Do **not** judge page tearing yet; two petals may still be on area 2 until Semantic Windows v2.
5. Quick GFX-A/B/C regression spot-check.

Do not install automatically.

## Explicitly out of scope

- Semantic Windows v2.
- Moving whole flowers/branches between areas/pages.
- Continuation/page connectors.
- Page/window limits.
- New relation types.
- Backend/API/schema/Alembic changes.
- Production deploy/ref movement.
- Manual free positioning.
- Global continuous optimizer.
- Old GUX1 / Secretary Agent work.

## Completion contract

When complete:

1. record root cause, implementation SHA, algorithm-version change, measured before/after sibling-link distances, regression results, bundle provenance/hashes, and limitations in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus TL2.1 summary and human-check bundle path;
3. commit/push to `main`;
4. STOP.

Do not begin Semantic Windows v2 until Architect review + human check of TL2.1.
