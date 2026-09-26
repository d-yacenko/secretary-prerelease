# Current task — Visual Task Map V2R: resume ELK geometry spike on Flutter 3.47 baseline

Task Refinement T1-T6, Visual Task Map V1, and the Flutter 3.47 / Dart 3.13 client baseline migration are architect-accepted.

Resume the previously blocked ELK geometry spike now that `elk: 0.2.0` resolves on the accepted client SDK.

Implement only the reversible visualization experiment that separates Secretary semantic scene construction from graph geometry and evaluates pure-Dart ELK for local Task-map geometry.

Do not change Task semantics, ontology, backend APIs, database schema, proactive behavior, Task lifecycle, Task Profile, Areas, Project semantics, or production deployment.

## 1. Add ELK dependency

Add exactly:

`elk: 0.2.0`

as the only new layout-engine dependency for this stage.

Do not add:
- WebView;
- Cytoscape;
- Graphviz/native FFI;
- yFiles;
- GoJS;
- Sigma;
- another graph/layout package.

If `elk: 0.2.0` does not resolve on the accepted Flutter 3.47 / Dart 3.13 baseline, STOP and report.

## 2. Introduce an engine-neutral visualization boundary

Add a small client-side abstraction independent of GraphView and independent of ELK-native types.

Use names equivalent to:

- `TaskMapScene`
  - semantic nodes;
  - semantic edges;
  - node sizes;
  - optional prior/fixed coordinates if needed later;
- `TaskMapLayoutEngine`
  - accepts a scene;
  - returns a normalized layout result or typed failure;
- `TaskMapLayoutResult`
  - node rectangles/positions;
  - routed edge geometry where available.

Exact names may differ.

Canonical Graph/Task models must not depend on ELK package types.

The renderer outside the ELK adapter must not consume ELK-native objects.

## 3. Preserve all existing renderers

Keep:

- current Graph renderer as startup/default;
- V1 GraphView experiment as-is;
- People mode unchanged.

Add V2 as a third clearly experimental Task renderer, e.g. `ELK`.

Switching renderers must not reload or mutate canonical workspace data.

## 4. V2 scene semantics: local Task-centered flower

Unlike V1 Task-only skeleton, preserve the useful local structure seen in the current graph.

For a selected/root Task, build a bounded local scene from already-loaded workspace data containing:

- selected/root Task;
- directly connected Task neighbors already loaded;
- directly connected non-Task evidence/context already loaded;
- only existing edges whose endpoints are in the visible scene.

Do not infer:
- new edges;
- hierarchy;
- Areas;
- grouping;
- semantic clusters.

For an overview with no selected/root Task, a bounded Task-only overview is acceptable, but the primary V2 evaluation target is the local Task-centered flower.

## 5. Flutter owns rendering

ELK computes geometry only.

Continue to render Task/evidence cards as Flutter widgets.

Do not render as:
- image;
- HTML;
- Canvas snapshot;
- package-owned card widgets.

Use normalized layout output to position Flutter widgets.

Existing Task selection must continue to reuse the canonical detail panel and Task Profile.

## 6. Routed edges are the primary proof

Use ELK-provided routed edge sections/bend points when exposed by the package.

The visual edge layer must support multi-segment routes.

Prefer:
- edge endpoints at or near node boundaries;
- orthogonal/bent routing when produced by ELK;
- avoidance of unrelated node rectangles where supported.

Do not implement a competing routing algorithm yourself.

If the Dart ELK wrapper does not expose usable routed geometry, record that explicitly as a major finding rather than hiding it with custom routing.

## 7. Deterministic comparison scenes

Add deterministic client-side fixtures for at least:

### A. Task flower
Approximately:
- 1 central Task;
- 2-4 nearby Tasks;
- 10-20 evidence/context nodes.

### B. Small activity cluster
Approximately:
- 6-12 Tasks;
- several Task-to-Task links;
- 15-30 evidence/context nodes.

These are visualization fixtures only and must not imply new ontology.

## 8. Required geometry probes

For both fixtures record:

- layout success or typed failure;
- node rectangle overlap count;
- routed edges with non-trivial segments/bends;
- simple edge-vs-unrelated-node intersection count;
- deterministic repeatability of normalized result;
- movement of common nodes after adding one evidence leaf.

Keep the intersection probe simple/test-oriented.

Do not build a general computational-geometry subsystem.

## 9. Stability experiment

Compare:
- base scene;
- same scene plus one evidence node.

Count pre-existing nodes moving more than a small epsilon.

If ELK supports prior positions/fixed nodes cleanly through its public API, add one small experiment using that.

Do not persist coordinates.

Do not create a custom force simulation.

## 10. Failure behavior

On ELK failure:

- workspace data remains unchanged;
- V2 renderer shows a concise safe fallback/error;
- current and V1 renderers remain immediately available.

Do not silently switch engines inside the V2 adapter.

## 11. Semantic zoom

Reuse existing V1 presentation-only zoom primitives where practical.

Do not expand semantic zoom scope in V2.

This stage is about geometry/routing, not final multilevel-island UX.

## 12. Prepare for later islands without implementing them

The scene/layout boundary should not assume the graph will always remain globally flat.

Avoid an API that makes future presentation-only grouping impossible.

But do NOT implement now:

- Areas;
- label-derived islands;
- connected-component islands;
- compound groups in product UI;
- contains/part_of;
- hierarchy;
- LLM clustering.

## 13. Android known blocker

Do not attempt to fix `dart_duckdb`.

The V2 acceptance proof is Linux/test-based.

You may run Android build only if useful, but the known `dart_duckdb` 1.4.4 release-asset HTTP 404 is not part of V2.

Do not:
- vendor DuckDB binaries;
- fork/patch `dart_duckdb`;
- raise minSdk;
- change Android compatibility pins.

## Focused proof

Add tests proving at minimum:

1. Current Graph remains default.
2. V1 GraphView remains available unchanged.
3. People mode remains unchanged.
4. V2 consumes existing controller/workspace data only.
5. Canonical models do not depend on ELK-native types.
6. ELK is isolated behind the layout-engine adapter.
7. Task flower includes only center Task + loaded direct neighbors + existing edges.
8. Unrelated loaded objects are excluded.
9. Flutter node widgets are positioned from normalized layout output.
10. Selecting V2 Task reuses existing detail/Task Profile UI.
11. Flower layout succeeds or typed-fails safely.
12. Cluster layout succeeds or typed-fails safely.
13. Node overlap counts are recorded.
14. Routed-edge/bend support is recorded.
15. Edge-vs-node intersection counts are recorded.
16. Repeatability is measured.
17. One-leaf movement is measured.
18. ELK failure does not mutate workspace and switching back works.
19. Existing V1 tests remain green at their known baseline.
20. No backend/schema/ontology/proactive/product/deploy change.

Run:

- `flutter pub get`;
- existing Graph workspace/controller/screen/layout tests;
- existing V1 Task Map tests;
- new V2 ELK adapter/renderer/probe tests;
- Task Profile UI tests;
- Flutter analyze touched files;
- `flutter build linux --debug`;
- `git diff --check`.

## Completion

When complete:

- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- record `elk` version;
- record flower + cluster geometry observations:
  - overlaps;
  - routed bends;
  - edge/node intersections;
  - repeatability;
  - one-leaf movement;
- state whether ELK looks viable as a geometry engine for the next visual experiment;
- do NOT choose final graph technology automatically;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Do not start islands/Areas/compound semantic grouping until Architect + user review this V2 result.
