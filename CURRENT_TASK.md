# Current task — Visual Task Map V3A-R: Graphviz local-refinement spike with temporary host install

The previous V3A stopped only because `neato` was absent. Graphviz is not rejected.

Retry the SAME Graphviz local-refinement experiment with explicit authorization to install Graphviz temporarily in the Executor Linux host environment for this work cycle.

The current Graph renderer remains the leading product-map candidate.

Do NOT replace the current graph layout.

Secretary keeps:
- semantic scene selection;
- current global map/geography from `GraphLayout`;
- focus semantics;
- Flutter card rendering;
- canonical detail/Task Profile behavior.

Graphviz may only help with:
- local collision/overlap reduction;
- small local node displacement;
- routed focus edges / spline control points.

No ontology/backend/Task semantic/Area/hierarchy/proactive/deploy changes.

## 1. Temporary host-only Graphviz setup

At start:
- run `neato -V`.

If unavailable, identify the host distro/package manager.

You are explicitly authorized to install the distro Graphviz package ONLY as temporary host tooling for this work cycle, provided:
- installation is non-interactive;
- no user password/credential/passphrase is requested;
- no private repository credential is involved;
- no Graphviz binary/library/package file is committed or vendored;
- no production/runtime configuration is changed.

Use the host's normal package manager and official distro package repositories only.

Examples of acceptable package names are typically `graphviz`; discover the exact host package normally rather than guessing alternate binaries.

Do NOT:
- curl arbitrary third-party binaries into the repository;
- build Graphviz from source;
- add Graphviz to Flutter/pub dependencies;
- modify Docker/production images;
- add Android NDK packaging.

After install, run:
- `neato -V`
and record exact Graphviz version.

If installation is unavailable because of privileges, missing package manager, interactive sudo/password, or network/package-repository restrictions:
- record exact sanitized blocker in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- push documentation-only result;
- STOP.

Do not substitute another engine in that case.

## 2. Reusable local-refinement contract

Introduce an engine-neutral client-side geometry-refinement boundary, separate from the V2 full-layout contract.

Use names equivalent to:

- `GraphGeometryScene`
  - node id;
  - width/height;
  - current/global top-left from existing `GraphLayout`;
  - fixed/movable flag;
  - visible edges;
- `GraphGeometryRefiner`
  - scene -> normalized result or typed failure;
- `GraphGeometryResult`
  - refined positions;
  - routed edge paths/control points;
  - diagnostics.

Graphviz/DOT/process parsing stays behind one adapter.

Canonical Graph/API/Task models must not depend on Graphviz/DOT/process types.

Shape the interface so V3B fCoSE can later implement the SAME contract.

## 3. Preserve current global geography

Input positions MUST come from the existing current renderer / `GraphLayout`.

Do not run Graphviz as the product's new global layout.

Current renderer remains startup/default.
V1 GraphView remains unchanged.
V2 ELK remains unchanged.
People mode remains unchanged.

## 4. Local focus scene

For a selected Task build a bounded refinement scene from already-loaded workspace data:

Semantic focus:
- selected Task;
- directly connected loaded neighbors;
- only existing edges between visible semantic nodes.

Mobility:
- selected Task fixed;
- direct semantic neighbors movable;
- all other global nodes retain original coordinates.

Include nearby already-loaded nodes as FIXED geometric obstacles when their current rectangles intersect a deterministic bounded guard band around the focus neighborhood.

The guard band is geometry-only:
- no new semantic relation;
- no new fetch;
- no Area/group;
- no LLM clustering.

## 5. Three Graphviz modes on the SAME starting positions

### A. Routes

Use positioned-node Graphviz mode equivalent to:
- `neato -n2`;
- spline routing.

Goal:
- preserve node positions;
- obtain routed edge geometry.

Normalize Graphviz coordinates/units/origin to Flutter logical coordinates.

Measure round-trip position drift.

### B. Overlap

Use positioned-node mode equivalent to:
- `neato -n`;
- one conservative overlap-removal configuration;
- spline routing.

Suggested family:
- `overlap=prism`;
- small bounded `sep`;
- `splines=true`.

Goal:
- reduce collisions while staying visually close to current positions.

Do not broadly tune parameters.

### C. Local

Use normal `neato` from existing `pos`:
- selected Task pinned;
- obstacle nodes pinned;
- direct semantic neighbors movable;
- conservative overlap removal;
- spline routing;
- `notranslate=true` where applicable.

Goal:
- relax only the local flower while global geography remains fixed.

If pinned nodes drift, measure/report it.
Do not hide drift with a custom post-hoc compensation algorithm.

Uniform origin/unit normalization is allowed.

## 6. Safe DOT/process adapter

Use synthetic safe Graphviz node ids and an in-memory map to Secretary ids.

Do not pass user titles as executable arguments.

Invoke via `Process.run` / `Process.start` executable + argument list.
Do not construct a shell command string from graph/user data.

Pass real node width/height.

Use `plain` / `plain-ext` geometry output if sufficient. If another documented geometry-only output is strictly needed, record why.

Normalize:
- node positions/rectangles;
- edge control points/routes;
- coordinate origin/direction;
- Graphviz units.

Do not use Graphviz-rendered SVG/PNG as UI.
Flutter keeps drawing cards.

## 7. Experimental UI

Add a fourth Task renderer labelled `Graphviz`.

It should visually be the CURRENT graph plus local refinement:
- same global map;
- same cards;
- same focus dimming;
- same detail panel;
- same selection behavior.

When Task selected, apply Graphviz only to bounded local scene.

Add compact submode selector:
- `Маршруты`;
- `Overlap`;
- `Local`.

No selected Task:
- unmodified current map.

Graphviz unavailable/failure:
- concise experimental warning;
- canonical workspace unchanged;
- user can immediately return to `Текущий`.

## 8. Edge rendering

For refined focus edges with Graphviz routes:
- draw returned multi-point route;
- preserve relation/proposed styling where practical;
- arrow direction follows final routed segment.

All non-refined/global edges:
- keep current renderer behavior.

Do NOT route the whole global graph through Graphviz.

## 9. Shared fixtures and metrics

Reuse V2 flower and cluster fixtures where practical, STARTING from current `GraphLayout` positions.

Add deterministic overlap-stress fixture with at least one local card overlap or near-overlap.

For every mode record:

- success / typed failure;
- nodes changed >1 px;
- max fixed-node displacement;
- max movable-node displacement;
- overlaps before / after;
- routed focus-edge count;
- bent/non-trivial route count;
- routed-edge vs unrelated-node intersection count;
- deterministic repeatability;
- one-leaf stability: add one evidence leaf and count PRE-EXISTING nodes moved >1 px.

Spike diagnostics only; no production telemetry.

## 10. Product acceptance target

A useful result must demonstrate at least one mode where:
- current map/geography stays recognizable;
- selected Task remains effectively fixed;
- unrelated/global nodes remain effectively fixed;
- local overlaps reduce/eliminate where present;
- routed local edges improve or at least do not harm readability.

A prettier result that destroys recognizable geography is a negative result.

Do not select a final winner yet.

## 11. Scope exclusions

Do not implement:
- islands;
- Areas;
- label regions;
- new semantic zoom;
- 3D/fisheye;
- hierarchy / contains / part_of;
- attention ranking;
- backend/API changes;
- migrations;
- Android Graphviz packaging;
- DuckDB fix;
- fCoSE;
- production deploy.

## Focused proof

At minimum prove:

1. Current Graph remains default.
2. V1 and V2 remain available unchanged.
3. People mode unchanged.
4. No selected Task => Graphviz mode uses current positions unchanged.
5. Local scene includes selected Task + loaded direct neighbors + bounded fixed obstacles only.
6. Canonical models are independent of Graphviz/DOT/process types.
7. Routes mode round-trips positions within epsilon.
8. Overlap mode metrics recorded.
9. Local mode keeps fixed nodes within epsilon OR records actual drift.
10. Graphviz routes render only for refined focus edges.
11. Non-refined edges retain current behavior.
12. Graphviz failure leaves workspace state untouched.
13. Determinism measured.
14. One-leaf movement measured.
15. No backend/schema/ontology/product/deploy changes.

Run:
- `neato -V`;
- focused existing Graph tests;
- V1 Task Map tests;
- V2 ELK tests;
- new Graphviz adapter/refinement/UI tests;
- Task Profile UI tests;
- Flutter analyze touched files;
- `flutter build linux --debug`;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA;
- record exact Graphviz version and how host tooling was installed;
- record A/B/C metrics for flower, cluster, overlap-stress;
- record qualitative note on recognizability of current geography;
- do not choose final graph technology;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Do not begin V3B fCoSE automatically.
