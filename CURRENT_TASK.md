# Current task — TL2 Task Layout v2: recursive local subtrees

Authorized base: `59b87c8350bbfed4a510fedad2f706971ac833ed`.
GFX-C human verification: ACCEPTED by the user on 2026-09-30. Rename persists across leaving/returning to Graph, long Add-relation results scroll correctly, duplicate-title disambiguation remains correct, and drag-created existing `part_of` remains usable.
Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`.

This is a presentation-geography slice only. The goal is to replace the current globally radial Task hierarchy with a deterministic **recursive local-subtree layout**.

Do not redesign semantic windows/pages in this task. Page/window locality will be handled by a later Semantic Windows v2 slice.

## Problem to solve

Human observation on a real multi-level academic Task tree:

- A direction such as «Публикации в научной прессе» with several direct Tasks forms a useful compact flower.
- When that direction is attached under a higher direction such as «Академ», and sibling directions such as «Преподавание» / «Создание курсов» gain their own children, the current algorithm places deeper descendants on increasingly global rings.
- Direct children of «Преподавание» therefore become long-legged leaves spread around the older whole tree instead of staying a compact local flower around «Преподавание».
- Secondary Task↔Task relations can then become unnecessarily long; sibling ordering/orientation may be obviously worse even when a nearby arrangement exists.

The current lifecycle is already broadly correct: Task topology mutations trigger canonical layout resolution and persisted Task centers are reused on ordinary entry. Fix the **geometry algorithm**, not by adding periodic redraw/recompute buttons.

## Core invariant

`part_of` remains exactly:

- child/source -> parent/target;
- confirmed `part_of` defines the structural forest;
- no ontology or relation-type changes.

Every parent in that forest is the center of its own local subtree/constellation.

A child that itself has descendants is not just a point on a global ring. Treat its **whole recursively laid-out subtree as one spatial module** when placing it around its parent.

## Required layout model

Implement a deterministic recursive hierarchy layout with the following behavior.

### 1. Bottom-up subtree modules

For every confirmed `part_of` tree:

- build child lists from the canonical child -> parent edges;
- recursively compute a local layout/envelope for each child subtree;
- a leaf has only its Task presentation bounds;
- an internal Task owns a local module containing:
  - the parent Task at/near that module's local center;
  - each direct child subtree placed around that parent;
  - enough clearance that Task presentation rects and child-subtree envelopes do not overlap.

The important property is **locality by parent**:

- grandchildren are positioned relative to their own parent/subtree, not on a radius measured from the root of the entire tree;
- growth under one branch may move that branch/subtree as a block, but must not stretch that branch's own direct leaves onto a global outer ring.

Do not use screen/page dimensions as layout input.

### 2. Compact local flowers

For a parent whose direct children are leaves, produce an approximately even compact flower around that parent.

For a parent whose children include non-trivial subtrees:

- allocate angular/space sectors according to child-subtree envelope/weight;
- place the child subtree root on the parent-facing side of that subtree module where practical;
- separate subtree envelopes with a bounded gap;
- keep the child's internal constellation compact.

Exact geometry/optimizer is implementation choice, but it must be deterministic and testable.

No Task presentation rectangles may overlap in the final canonical projection.

### 3. Structural edges dominate; secondary Task edges orient

Confirmed `part_of` is the structural constraint and must dominate geography.

Visible Task↔Task relations such as:

- `depends_on`;
- `references`;
- `related_to`;

may influence sibling/subtree **ordering and orientation** as weak secondary hints so that avoidably long Task↔Task lines are reduced.

They must not:

- break a `part_of` subtree apart;
- move a leaf away from its local parent merely to satisfy a secondary edge;
- create a second ontology or hierarchy;
- use Flow/Person positions.

A practical deterministic solution is acceptable: e.g. baseline/weighted preferred angles plus discrete orientation/order evaluation. A general-purpose global optimizer is not required.

Rejected edges must not influence layout. Proposed edges may remain visible according to existing presentation rules, but must not override confirmed structural locality.

### 4. Flow/evidence does not drive canonical Task geography

Mail, calendar, document/note/evidence objects and their compact «dandelion» presentation remain presentation satellites.

They must not affect canonical Task centers or subtree packing.

People continue to derive their projection from canonical Task centers exactly as in accepted PL1.

### 5. Independent components

Continue to pack independent Task components without overlap.

Prefer compact landscape packing, but component packing is secondary to preserving each recursively laid-out structural subtree.

Do not introduce page/window limits into this packer.

## Canonical snapshot/version behavior

This is a new canonical Task-layout algorithm.

- Bump `kTaskLayoutAlgorithmVersion` from `task-map-v1` to `task-map-v2`.
- Existing `task-map-v1` snapshots must therefore be considered non-current by the existing client contract.
- On first resolution with the new client, fetch the complete Task topology, compute the complete v2 centers, and persist one complete replacement through the existing `PUT /graph/task-layout` optimistic revision contract.
- Do not add a migration or schema change.
- Do not mutate Task metadata to store presentation state.
- Preserve fail-closed behavior: never persist a partial set of Task centers.
- Preserve bounded stale-topology retry behavior.

Ordinary Graph entry after a usable v2 snapshot exists should reuse it; do not recompute on every render.

Existing topology-changing Task↔Task mutations should continue to invalidate/re-resolve through the current topology-refresh path. No manual «rebuild graph» button is needed.

## No heavy spatial-inertia system in TL2

Do **not** add a complex distance-from-mutation pinning/inertia model in this slice.

Determinism and compact recursive locality are primary.

If several arrangements are equivalent, stable ID/baseline ordering may be used as a tie-breaker, but old coordinates are not hard pins.

Semantic preservation of whole trees/branches when the world is split into areas belongs to the later Semantic Windows v2 task.

## Required acceptance fixtures/tests

Add deterministic layout fixtures that make the old failure visible.

### A. Two-level local flowers

Synthetic structure:

- `Academic` root;
- direct children `Publications`, `Teaching`, `Courses`;
- `Publications` has at least 5 leaf Tasks;
- `Teaching` has at least 5 leaf Tasks;
- `Courses` may have 0–3 leaves.

Prove:

- all Tasks receive finite positions;
- no Task presentation rects overlap;
- direct leaves of `Publications` remain a compact local flower around `Publications`;
- direct leaves of `Teaching` remain a compact local flower around `Teaching`;
- those leaf distances are local to their parent and do not grow merely because that parent is one level deeper under `Academic`;
- the `Publications` and `Teaching` subtree envelopes do not overlap.

Do not assert one brittle exact coordinate map. Assert structural/locality metrics with reasonable tolerances.

### B. Growth of one branch stays local

Compare the same tree before/after adding several children under `Teaching`.

Prove:

- the Teaching subtree envelope grows/moves as needed;
- its children remain compact around Teaching;
- Publications remains a coherent subtree and is not interleaved with Teaching leaves;
- no overlaps are introduced.

This is not a requirement that unrelated coordinates be bit-identical.

### C. Secondary-edge orientation

Construct sibling/nearby Tasks where one placement/orientation would create a clearly longer confirmed `depends_on`/reference/related edge than an available alternative.

Prove the chosen deterministic layout/orientation reduces the avoidable secondary-edge distance without breaking the `part_of` subtree locality.

Do not optimize edge crossings at the expense of dramatically longer structural edges. Crossings themselves are allowed.

### D. Deep hierarchy

At least 3–4 structural levels with branching.

Prove descendants remain recursively local and direct structural edge lengths are governed by local subtree clearance rather than global root depth.

### E. Algorithm-version replacement

Prove:

- a usable `task-map-v1` snapshot is not reused by a v2 client;
- the client fetches complete topology and writes a complete `task-map-v2` snapshot;
- a usable complete v2 snapshot is reused without recomputation/write;
- incomplete/invalid topology still fails closed;
- stale PUT conflict behavior remains bounded as before.

### F. Existing regressions

Keep green:

- task-layout API/world tests;
- Graph smoke and large-canvas;
- rooted/unrooted Task rendering;
- Tasks<->People shared camera/world;
- People anchors/centroids/clusters/shelf/cue;
- GFX-A duplicate-title picker;
- GFX-B drag `part_of`;
- GFX-C rename and relation-picker scrolling.

## Human-check build is part of TL2

After implementation/tests pass, produce a fresh self-contained Linux debug bundle from a clean detached checkout of the exact TL2 implementation SHA.

Record:

- source SHA;
- UTC build time;
- bundle/executable path;
- launcher SHA-256;
- kernel SHA-256 if present;
- adjacent `BUILD_INFO.txt`.

Human checklist must ask the user to inspect a real multi-level tree such as the academic example:

1. «Публикации» remains its own compact flower.
2. «Преподавание» has its own compact flower instead of long leaves spread around the entire Academic tree.
3. «Создание курсов» similarly occupies its own local branch as it grows.
4. Secondary Task lines are not needlessly long where a sibling orientation can shorten them.
5. No Task cards overlap.
6. Tasks and People still share the same canonical world/camera.
7. Existing GFX-A/B/C interactions still work in a quick spot-check.

Do not install the bundle automatically.

## Explicitly out of scope

- Semantic-window/page partition redesign.
- Moving whole trees/branches between page areas.
- Continuation/page connectors.
- Changing current page/window limits.
- A manual graph rebuild button.
- Arbitrary manual Task positioning.
- New relation types or ontology changes.
- Backend API/schema/Alembic changes.
- Production deploy/ref movement.
- Old GUX1 polish.
- Secretary Agent/Harness work.

## Completion contract

When complete:

1. record implementation SHA, algorithm-version change, changed files, geometry metrics from the deterministic fixtures, exact regression checks, bundle path/hashes, and known limitations in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus a concise TL2 implementation + bundle summary;
3. commit/push to `main`;
4. STOP.

Do not begin Semantic Windows v2 until Architect review + user human verification of TL2.
