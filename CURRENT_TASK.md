# Current task — Visual Task Map V3B: fCoSE local-refinement spike

The current Graph renderer remains the leading product-map candidate.

Graphviz V3A/V3A-R is paused because the Executor Linux host lacks Graphviz and installing it requires an interactive sudo password. Do not retry Graphviz in this task.

Evaluate pure-Dart `fcose` 0.1.0 only as a LOCAL geometry refiner over the existing stable `GraphLayout` positions.

Secretary keeps:
- semantic scene selection;
- current global map/geography from `GraphLayout`;
- focus semantics;
- Flutter card rendering;
- canonical detail/Task Profile behavior;
- current edge rendering unless an adapter explicitly provides routes.

No ontology/backend/Task semantic/Area/hierarchy/proactive/deploy changes.

## 1. Add fCoSE dependency

Add exactly:

`fcose: 0.1.0`

as the only new geometry dependency in V3B.

Do not add:
- another layout package;
- Graphviz;
- WebView/JavaScript;
- native FFI.

If `fcose: 0.1.0` does not resolve on the accepted Dart 3.13 baseline, record blocker, return HOLD, push, STOP.

## 2. Introduce the reusable geometry-refinement contract

Because V3A never reached implementation, introduce the engine-neutral local-refinement boundary now.

Use names equivalent to:

- `GraphGeometryScene`
  - node id;
  - width/height;
  - current/global top-left position;
  - fixed/movable flag;
  - visible edges;
- `GraphGeometryRefiner`
  - scene -> normalized result or typed failure;
- `GraphGeometryResult`
  - refined node positions/rectangles;
  - optional routed edge paths;
  - diagnostics.

Important:
- routed edge paths are OPTIONAL in this contract;
- fCoSE is not required to route edges;
- an adapter returning only refined positions is valid.

Canonical Graph/API/Task models must not depend on fCoSE-native types.

`package:fcose` imports must be isolated to the fCoSE adapter.

The contract should remain usable by a later Graphviz adapter without changing product semantics.

## 3. Preserve current global geography

Input positions MUST come from the current renderer / `GraphLayout`.

Use fCoSE in incremental/refinement mode:
- `randomize: false`;
- every movable leaf receives its current initial position;
- selected Task is fixed;
- geometric obstacle nodes are fixed.

Do not ask fCoSE to create a new global layout.

Current renderer remains startup/default.
V1 GraphView remains unchanged.
V2 ELK remains unchanged.
People mode remains unchanged.

## 4. Local focus scene

For a selected Task build a bounded geometry scene from already-loaded workspace data.

Semantic focus:
- selected Task;
- directly connected loaded neighbors;
- only existing edges between semantic focus nodes.

Mobility:
- selected Task = fixed;
- direct semantic neighbors = movable;
- other global nodes remain at original positions.

Add nearby loaded nodes as FIXED geometric obstacles when their current rectangles intersect a deterministic guard band around the current focus neighborhood.

The guard band:
- is geometry-only;
- does not create semantic relations;
- does not fetch new data;
- does not create Areas/groups.

No selected Task:
- no refinement;
- display the current graph unchanged.

## 5. fCoSE configurations

Evaluate exactly two bounded configurations on the SAME starting positions.

### A. Preserve

Use a conservative deterministic incremental run:
- `randomize: false`;
- selected Task and obstacles in `fixedNodes`;
- deterministic seed where supported;
- otherwise documented default force values.

Goal:
- remove/reduce local collisions while minimizing displacement.

Do not tune a large parameter matrix.

### B. Relax

Use the same incremental/fixed-node setup with ONE deliberately stronger but still reasonable relaxation configuration.

Choose the smallest documented parameter change that meaningfully allows more separation, such as a modest force/spacing/quality adjustment.

Record exactly which option differs from Preserve and why.

Do not perform parameter search or optimization.

## 6. Fixed-node proof

This is the main reason for V3B.

Prove on deterministic fixtures:
- selected Task stays fixed within <= 1 px;
- fixed obstacle nodes stay fixed within <= 1 px;
- movable neighbors may move;
- same inputs/config produce repeatable normalized coordinates.

If fCoSE's public fixed-node constraints do not actually preserve fixed nodes in this use case, record the drift and treat that as a major negative result.

Do not compensate by translating individual fixed nodes after layout.

Uniform whole-result coordinate normalization is allowed only if it preserves relative geometry and is documented.

## 7. Overlap behavior

Use actual card rectangles/sizes.

Measure:
- overlap count before;
- overlap count after;
- max overlap area before/after if easy to compute with a small test helper;
- max displacement of movable nodes;
- count of movable nodes changed >1 px.

Do not implement a custom collision solver around fCoSE.

If overlap remains, report it.

## 8. Edge behavior

fCoSE does not need to route edges in V3B.

Keep current straight current-renderer edge behavior for the product UI.

After refined node positions, measure with the existing/simple geometry helper:
- number of focus-edge segments crossing unrelated node rectangles before;
- number after.

This tells us whether local node relaxation improves line readability even without a router.

Do not implement a separate router.

## 9. Experimental UI

Add a fourth Task renderer labelled `fCoSE`.

Graphviz UI was never implemented; do not add a Graphviz renderer in this task.

The fCoSE renderer must look like the CURRENT graph:
- same full/global map;
- same cards;
- same focus dimming;
- same detail panel;
- same selection behavior.

Only the bounded selected local neighborhood may use refined positions.

All nodes outside refinement scene remain at their existing current positions.

Add compact submode selector:
- `Preserve`;
- `Relax`.

No selected Task:
- show unmodified current map.

fCoSE failure:
- show concise experimental warning;
- canonical workspace remains untouched;
- switching back to `Текущий` is immediate.

## 10. Shared fixtures

Reuse V2 flower and cluster fixture semantics where practical but start from CURRENT `GraphLayout` positions.

Add one deterministic overlap-stress fixture where at least two local card rectangles overlap before refinement.

For each configuration run:
- flower;
- cluster/local selected Task case;
- overlap-stress case.

Also test one evidence leaf added to the same selected Task.

## 11. Required metrics

For each configuration/fixture record:

- success or typed failure;
- fixed-node count;
- max fixed-node displacement;
- movable-node count;
- movable nodes changed >1 px;
- max movable-node displacement;
- overlaps before -> after;
- edge-vs-unrelated-node intersections before -> after;
- deterministic repeatability;
- one-leaf stability: count PRE-EXISTING movable nodes moving >1 px after adding one evidence leaf.

Also record:
- runtime for fixture layout in a coarse test-only measurement if stable enough to be meaningful;
- do not create production telemetry or performance infrastructure.

## 12. Product acceptance target

A promising result must show:

- global geography remains recognizable;
- selected Task/fixed obstacles truly stay fixed;
- movement is local rather than whole-map;
- overlap-stress improves materially;
- the current visual flower remains recognizable;
- edge readability does not materially worsen.

A result that technically removes overlaps but produces a less understandable local shape is a negative result.

Do not select final graph technology automatically.

## 13. Scope exclusions

Do not implement:
- Graphviz retry/install;
- edge routing library;
- islands;
- Areas;
- label regions;
- new semantic zoom;
- 3D/fisheye;
- hierarchy / contains / part_of;
- attention ranking;
- backend/API changes;
- migrations;
- Android packaging work;
- DuckDB fix;
- production deploy.

## Focused proof

Add tests proving at minimum:

1. Current Graph remains default.
2. V1 GraphView remains available unchanged.
3. V2 ELK remains available unchanged.
4. People mode remains unchanged.
5. No selected Task => fCoSE renderer uses current positions unchanged.
6. Local scene = selected Task + loaded direct neighbors + bounded fixed obstacles only.
7. Canonical models/refinement contract do not depend on fCoSE-native types.
8. fCoSE import is adapter-only.
9. Preserve keeps selected/fixed obstacles within <=1 px or explicitly records failure.
10. Relax keeps selected/fixed obstacles within <=1 px or explicitly records failure.
11. Overlap-stress before/after is measured.
12. Edge/node intersections before/after are measured with current straight edges.
13. Determinism is measured.
14. One-leaf stability is measured.
15. fCoSE failure leaves workspace state unchanged.
16. Existing current/V1/V2 tests remain at known baseline.
17. No backend/schema/ontology/product/deploy changes.

Run:
- `flutter pub get`;
- focused current Graph tests;
- V1 Task Map tests;
- V2 ELK tests;
- new fCoSE adapter/refinement/UI tests;
- Task Profile UI tests;
- Flutter analyze touched files;
- `flutter build linux --debug`;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA;
- record exact `fcose` version;
- record Preserve vs Relax settings;
- record all fixture metrics;
- record qualitative note on whether current map/flower remains recognizable;
- state whether fCoSE looks viable for local refinement;
- do not choose final graph technology automatically;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Do not begin another engine spike automatically.
