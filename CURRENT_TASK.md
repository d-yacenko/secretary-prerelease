# Current task — Visual Task Map V3A: Graphviz local-refinement spike

The current Graph renderer is the leading product-map candidate after human comparison of the current renderer, V1 GraphView, and V2 ELK.

Do NOT replace the current graph layout.

Evaluate Graphviz only as a LOCAL geometry post-processor over the existing stable `GraphLayout` positions.

Secretary keeps:
- semantic scene selection;
- the current global map/geography;
- focus semantics;
- Flutter card rendering;
- canonical detail/Task Profile behavior.

Graphviz may only help with:
- local collision/overlap reduction;
- small local node displacement;
- routed focus edges / spline control points.

No ontology/backend/Task semantic/Area/hierarchy/proactive/deploy changes.

## 1. Linux-only Graphviz spike

Use the system Graphviz `neato` executable on Linux.

At start run:
- `neato -V`

If unavailable:
- do not substitute another engine;
- do not download/vendor Graphviz into the repository;
- record blocker in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- push documentation-only result;
- STOP.

Do not add Android NDK/native packaging in V3A.

Invoke Graphviz safely via `Process.run` / `Process.start` executable + argument list. Do not construct a shell command string from graph/user data.

## 2. Reusable local-refinement contract

Introduce a small engine-neutral client-side contract for geometry refinement, separate from the V2 full-layout contract.

Use names equivalent to:

- `GraphGeometryScene`
  - node id;
  - node width/height;
  - current/global top-left position from existing `GraphLayout`;
  - fixed/movable flag;
  - visible edges;
- `GraphGeometryRefiner`
  - scene -> normalized result or typed failure;
- `GraphGeometryResult`
  - refined node positions;
  - routed edge paths/control points;
  - diagnostics needed by the spike.

Graphviz/DOT/process parsing stays behind one adapter.

Canonical Graph/API/Task models must not depend on Graphviz types, DOT, or process details.

Shape this interface so a later V3B fCoSE adapter can implement the SAME contract.

## 3. Preserve current global geography

Input positions MUST come from the existing current renderer:
- `GraphLayout` / controller visible positions.

Do not run Graphviz as a new global layout.

Current renderer remains startup/default.
V1 GraphView remains unchanged.
V2 ELK remains unchanged.
People mode remains unchanged.

## 4. Local focus scene

For a selected Task build a bounded refinement scene from already-loaded workspace data.

Semantic focus:
- selected Task;
- its directly connected loaded neighbors;
- only existing edges between those visible semantic nodes.

Mobility:
- selected Task is fixed;
- direct semantic neighbors may move;
- all other global nodes retain original coordinates.

To avoid moving a local node into an already occupied area, include nearby already-loaded nodes as FIXED geometric obstacles when their current rectangles intersect a deterministic bounded guard band around the focus neighborhood.

The guard band is geometry-only:
- no new semantic relation;
- no new fetch;
- no Area/group;
- no LLM clustering.

## 5. Three Graphviz modes on SAME starting positions

Implement and measure exactly these modes.

### A. Routes

Use positioned-node Graphviz mode equivalent to `neato -n2` with spline routing.

Goal:
- node positions preserved;
- routed edge geometry obtained.

Normalize coordinates/units/origin back to Flutter logical coordinates.

Prove round-trip position drift is within a small epsilon.

### B. Overlap

Use positioned-node mode equivalent to `neato -n` with one conservative overlap-removal configuration and spline routing.

Suggested family:
- `overlap=prism`;
- small bounded `sep`;
- `splines=true`.

Goal:
- measure whether collisions/routes improve while map remains visually close to the current positions.

Do not perform broad parameter tuning.

### C. Local

Use normal `neato` from existing `pos` values:
- selected Task pinned;
- obstacle nodes pinned;
- direct semantic neighbors movable;
- conservative overlap removal;
- spline routing;
- `notranslate=true` where applicable.

Goal:
- test whether only the local flower can relax while the global geography stays fixed.

If Graphviz still moves pinned nodes, measure and report the drift. Do not hide it with per-node custom compensation.

Uniform coordinate-origin/unit normalization is allowed.

## 6. DOT input and geometry output

Use synthetic safe Graphviz node ids and an in-memory map to Secretary object ids.

Do not embed user titles in executable arguments.

Pass real node width/height so Graphviz sees Flutter card rectangles.

Use `plain` / `plain-ext` geometry output if sufficient. If a different documented geometry-only format is strictly required, explain why.

Normalize:
- node positions/rectangles;
- edge paths/control points;
- coordinate origin/direction;
- Graphviz units.

Do not use Graphviz-rendered SVG/PNG as the app UI.

Flutter keeps drawing all cards.

## 7. Experimental UI

Add a fourth Task renderer labelled `Graphviz`.

It must look like the CURRENT graph, not like a new graph product:
- same global map;
- same current cards;
- same current focus dimming;
- same detail panel;
- same selection behavior.

When a Task is selected, apply the selected local refinement mode only to the bounded local scene.

Add a compact Graphviz submode selector:
- `Маршруты`;
- `Overlap`;
- `Local`.

No selected Task:
- show the unmodified current map.

If Graphviz is unavailable/fails:
- show concise experimental warning;
- keep canonical workspace state unchanged;
- user can immediately switch back to `Текущий`.

## 8. Edge rendering

For refined focus edges with a Graphviz route:
- draw the returned multi-point route;
- preserve current relation/proposed styling where practical;
- arrow direction must follow the final routed segment if the current edge is directional.

For all non-refined/global edges:
- keep current renderer behavior.

Do NOT route the entire global graph through Graphviz.

## 9. Shared comparison fixtures and metrics

Reuse the existing V2 flower and cluster fixtures where practical, but START from current `GraphLayout` positions.

Add one deterministic overlap-stress fixture where current positions intentionally produce at least one card overlap or near-overlap in the local neighborhood.

For every Graphviz mode record at minimum:

- layout/refinement success or typed failure;
- count of nodes whose position changed > 1 px;
- max displacement of any fixed node;
- max displacement of any movable node;
- node overlap count before / after;
- routed focus-edge count;
- edges with non-trivial bends;
- routed-edge vs unrelated-node intersection count;
- deterministic repeatability;
- one-leaf stability: add one evidence leaf and count how many PRE-EXISTING nodes move > 1 px.

These are spike diagnostics, not production telemetry.

## 10. Product acceptance target

The spike is successful only if at least one mode demonstrates the direction:

- current map/geography remains recognizable;
- selected Task stays effectively fixed;
- unrelated/global nodes stay effectively fixed;
- local overlaps are reduced/eliminated where present;
- routed local edges improve or at least do not reduce readability.

A technically prettier result that destroys recognizable geography is a negative result.

Do not declare a final winner between Graphviz/fCoSE/ELK/GraphView.

## 11. Scope exclusions

Do not implement:
- islands;
- Areas;
- label regions;
- semantic zoom expansion;
- 3D/fisheye;
- hierarchy / contains / part_of;
- attention ranking;
- backend/API changes;
- migrations;
- Android Graphviz packaging;
- DuckDB fix;
- fCoSE yet;
- production deploy.

## Focused proof

Add tests proving at minimum:

1. Current Graph remains default.
2. V1 and V2 remain available unchanged.
3. People mode remains unchanged.
4. No selected Task => Graphviz mode uses current global positions unchanged.
5. Local scene is selected Task + loaded direct neighbors + bounded fixed obstacles only.
6. Secretary canonical models do not depend on Graphviz/DOT/process types.
7. Routes mode round-trips node positions within epsilon.
8. Overlap mode metrics are recorded.
9. Local mode keeps selected Task/fixed obstacles within epsilon OR records actual Graphviz drift.
10. Graphviz returned routes are rendered only for refined focus edges.
11. Non-refined edges keep current rendering behavior.
12. Failure/unavailable Graphviz leaves workspace state untouched.
13. Same scene/mode is deterministic or nondeterminism is explicitly recorded.
14. One-leaf movement is measured.
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
- record implementation SHA and exact Graphviz version in `PROJECT_STATE.md`;
- record mode A/B/C metrics on flower, cluster, and overlap-stress fixtures;
- record qualitative notes on whether current geography stayed recognizable;
- do not choose final graph technology;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Do not begin V3B fCoSE automatically. Architect + user will review V3A first.
