# Current task — TL2.2 secondary-star local halo

Authorized base: `2f9f73943f3792c7c57244369afca30627ea326e`.

Production remains `1b6943ba4f7cc49df1465791d812d45db6d26b52`, Alembic `0052 / 0052`.

SW2-A / SW2-A-R1 is HUMAN-ACCEPTED for the observed normal pagination case:
- separate semantic Task components/trees move to neighboring overview areas whole;
- the real Publications component is no longer torn across areas;
- overview pagination remains active;
- splitting one truly oversized single connected Task component is still unverified in real usage and SW2-B remains deferred.

The only currently observed Graph defect is visual: the real Publications direction and its six publication Task neighbors are all present in one area, but the publication Tasks form a one-sided rightward tail instead of a balanced local flower.

## Root cause

Current TL2.1.1 gives recursive local flower semantics only to confirmed `part_of` children.

Confirmed non-`part_of` Task relations (`related_to`, `depends_on`, `references`) join the visual component and influence layout weakly, but Tasks not belonging to the `part_of` forest are placed later by `_placeFreeTasks`.

`_placeFreeTasks` is sequential:
- choose an already placed neighbor as anchor;
- copy the baseline delta from `GraphLayout`;
- call `_clearFree` to push away overlaps.

Several free Tasks attached to one already placed Task can therefore inherit baseline vectors on one side and then be pushed farther in the same direction, producing a tail.

This is NOT caused by semantic-window/page bounds. Canonical Task layout does not use viewport/page dimensions, and the whole component is packed after local geometry is drafted.

## Goal

Add a deterministic **secondary-star local halo** for the common case where several free leaf Tasks are attached by confirmed visible non-`part_of` Task relations to one already placed Task.

The visual result should read as a balanced local flower around the anchor while preserving ontology:
- `part_of` remains the only structural parent/child relation;
- secondary links remain secondary links;
- the halo is presentation geometry only and must not invent hierarchy.

## Required behavior

### 1. Detect eligible secondary-star leaves

Before generic sequential `_placeFreeTasks`, identify groups of free Tasks that can safely be treated as one presentation halo around an already placed anchor.

A free Task is eligible for a halo around anchor A when:

- the free Task is not already placed by the confirmed `part_of` forest;
- A is already canonically placed;
- there is at least one **confirmed visible** non-`part_of` Task↔Task relation directly between the free Task and A;
- proposed/rejected/hidden relations do not count;
- Flow/Person/label/temporal relations do not count;
- the free Task does not require choosing between multiple equally meaningful already placed anchors in a way that would invent hierarchy.

For ambiguous multi-anchor cases, preserve/fallback to the generic free-Task placement unless there is a deterministic presentation-only rule that demonstrably reduces total confirmed secondary-edge length without implying ownership.

Do not force every free Task into a halo.

### 2. Balanced 360-degree halo

For an anchor with at least 3 eligible free leaf neighbors:

- place those neighbors around the anchor over the full circle;
- use deterministic approximately even angular spacing;
- choose a local radius large enough for Task presentation rectangles not to overlap the anchor or one another;
- allow the halo to extend in any world direction, including negative/local-left coordinates;
- do not reserve screen/page margins and do not use viewport/window dimensions;
- after component packing, the whole envelope may be translated as today.

For 1-2 eligible neighbors, a simpler local placement is fine; do not make those cases worse.

### 3. Orientation, not collapse

Confirmed secondary relations may choose halo rotation/order to shorten avoidable secondary edges, but:

- they must not collapse six neighbors into one sector;
- they must not stretch the ring excessively;
- they must not override `part_of` subtree locality;
- equal scores should prefer a deterministic baseline-nearest rotation/order.

Use a bounded discrete optimization. No global continuous optimizer.

### 4. Collision with existing structural geometry

A secondary halo may sit around an anchor that is already inside a structural `part_of` tree.

The halo must:

- preserve all existing structural Task centers/subtree shapes;
- avoid Task-rectangle overlap with the anchor and existing placed Tasks;
- prefer bounded ring growth and/or deterministic rotation if one side is occupied;
- retain broad angular spread rather than pushing every free neighbor to the same unoccupied side;
- fall back safely if a valid halo cannot be found within bounded search.

Do not move the whole structural subtree merely to fit secondary leaves unless the existing final component-packing stage already does so.

### 5. Generic free graphs remain supported

Free Tasks that do not form an eligible star must continue through a deterministic generic path.

Do not regress:
- chains;
- multi-anchor networks;
- independent free components;
- mixed structural + free graphs.

The correction should specialize the star case rather than replacing all free-graph layout with hierarchy semantics.

## Canonical algorithm version

This changes canonical Task coordinates.

Bump:

- `task-map-v2.1.1` -> `task-map-v2.2`.

A usable v2.1.1 snapshot must be treated as old and replaced once by a complete v2.2 snapshot through the existing full-topology + optimistic PUT path.

No backend/schema/Alembic change is required.

## Required regression fixtures

### A. Six-petal confirmed related_to star — primary human case

Fixture:
- one anchor Task already placed as part of a structural tree;
- six free Task leaves;
- each leaf has one confirmed `related_to` edge to the anchor;
- no other secondary edges.

Prove:
- all six leaves remain local to the anchor;
- angular positions cover the full circle rather than one narrow sector;
- maximum angular gap / circular-spread metric demonstrates an approximately even flower without brittle exact coordinates;
- no Task rect overlaps;
- structural anchor/subtree coordinates are unchanged by the halo pass.

This fixture should expose the old one-sided sequential placement.

### B. Same star at a component-envelope edge

Construct geometry where the anchor is the leftmost or rightmost structural Task before halo placement.

Prove:
- halo still uses both sides of the anchor in canonical local coordinates;
- there is no artificial page/world-edge constraint;
- final component packing translates the envelope safely;
- no overlap.

### C. Occupied-side structural neighbor

Anchor has six secondary leaves and structural geometry already occupies one sector.

Prove:
- bounded rotation/radius adjustment avoids overlap;
- broad circular spread remains;
- leaves do not all collapse onto the opposite side.

### D. Proposed/rejected/hidden relation boundaries

A proposed or rejected `related_to` / `depends_on` / `references` must not qualify a Task for the halo.

Actor-role / label / temporal / Task↔Flow edges must not qualify.

### E. Ambiguous multi-anchor leaf

A free Task linked to two already placed Tasks must not be silently assigned as a semantic child of one.

Prove deterministic fallback or explicitly presentation-only choice, with no ontology mutation and no `part_of` fabrication.

### F. Secondary edge orientation

Within a six-leaf halo, add confirmed secondary edges among leaves or from a leaf to another nearby module.

Prove bounded order/rotation can shorten avoidable total secondary distance while preserving broad angular spread and local radius.

### G. Version replacement

Prove:
- usable `task-map-v2.1.1` is not reused;
- complete topology is fetched and a complete `task-map-v2.2` snapshot is written;
- usable complete v2.2 is reused;
- incomplete/invalid snapshots fail closed;
- stale PUT retry remains bounded.

## Preserve existing accepted behavior

Keep green:

- recursive `part_of` local flowers and subtree modules;
- TL2.1 sibling reorder;
- TL2.1.1 confirmed-only canonical geography;
- short «Трудоустройство в МФТИ» ↔ «Преподавание Java в МФТИ» secondary relation;
- SW2-A page membership semantics (backend is already production);
- Tasks/People shared canonical world/camera;
- GFX-A duplicate-title disambiguation;
- GFX-B drag-created `part_of`;
- GFX-C rename + relation-picker scroll;
- People anchors/clusters/shelf/cue;
- Graph smoke and large-canvas.

## Human-check build

After implementation/tests pass, build a fresh self-contained Linux debug bundle from a clean detached checkout of the exact TL2.2 implementation SHA.

Record:
- exact source SHA;
- UTC build time;
- executable path;
- launcher SHA-256;
- kernel SHA-256 if present;
- adjacent `BUILD_INFO.txt`.

Human checklist:

1. On the real Publications direction, the six publication Tasks should form a balanced flower/halo rather than a one-sided rightward tail.
2. The flower may extend to the left of its anchor; being near the visual edge must not force all leaves rightward.
3. Teaching/Courses and other accepted structural flowers remain coherent.
4. The previously shortened dashed secondary link remains short.
5. SW2-A pagination continues to keep separate trees/components whole.
6. No Task-card overlap.
7. Quick GFX-A/B/C spot-check.

Do not install automatically.

## Explicitly out of scope

- changing any real relation type or converting `related_to` into `part_of`;
- SW2-B oversized-component splitting;
- continuation markers;
- backend API/schema/Alembic changes;
- production rollout;
- viewport/page-size-driven layout;
- manual free positioning;
- global optimizer;
- GUX1 / Secretary Agent work.

## Completion contract

When complete:

1. record root cause, implementation SHA, algorithm-version bump, before/after star-spread metrics, regression results, bundle provenance/hashes, and limitations in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus TL2.2 summary and human-check bundle path;
3. commit/push to `main`;
4. STOP.

Do not deploy production and do not begin SW2-B.
