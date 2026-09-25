# Current task — Visual Task Map V2: layout-engine boundary + ELK geometry spike

Task Refinement T1-T6 and Visual Task Map V1 are architect-accepted.

Implement only a reversible visualization spike that separates Secretary semantic scene construction from graph geometry and evaluates a pure-Dart ELK layout engine for local Task-map geometry.

This is not a Task-ontology phase and not a final graph migration.

Do not change Task semantics, database schema, backend APIs, proactive behavior, lifecycle, Task Profile, Areas, project semantics, or production deployment.

## Product intent

V1 showed that changing the global graph layout alone does not make the user's activity map clearer.

The useful part of the current Graph is local structure:
- a Task as a meaningful center;
- nearby Tasks;
- evidence/materials around it;
- readable spatial relationships.

The expensive part we should not hand-code if a mature engine can do it:
- node placement;
- collision avoidance;
- edge routing;
- bend points;
- port/side selection;
- incremental geometry.

V2 must test a clean architectural split:

Secretary decides **what the scene means**.
The layout engine decides **where visible things go and how visible edges route**.
Flutter still renders the actual cards and owns interaction.

## 1. New internal visualization boundary

Introduce a small client-side abstraction independent of GraphView and independent of any specific layout package.

Use names equivalent to:

- `TaskMapScene`
  - visible semantic nodes;
  - visible semantic edges;
  - node sizes;
  - optional fixed/pinned coordinates if needed by the adapter;
- `TaskMapLayoutEngine`
  - accepts a `TaskMapScene`;
  - returns a deterministic layout result or a typed failure;
- `TaskMapLayoutResult`
  - node rectangles/positions;
  - routed edge paths/sections/bend points where supplied by the engine.

Exact class names may differ, but keep the boundary explicit.

Canonical Task/Graph models must not depend on the ELK package.

The UI must not read ELK-native objects directly outside the adapter.

## 2. ELK dependency

Evaluate the pure-Dart package named `elk` as the only new layout-engine dependency in V2.

Pin one concrete version compatible with the repository's current Dart/Flutter SDKs.

If the currently available package cannot support this repository's Android + Linux Flutter targets, required node sizing, or usable routed-edge geometry through its public API:

- do not substitute Cytoscape, Graphviz, yFiles, GoJS, another WebView engine, or another Dart package;
- record the exact compatibility/API blocker in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.

Do not add WebView/native FFI infrastructure in V2.

## 3. Keep all existing renderers

Do not replace or delete:

- the current Graph renderer;
- the V1 GraphView experiment.

Add V2 as another clearly experimental option in Graph -> Tasks, e.g. `ELK` / `Геометрия ELK`.

People mode stays unchanged.

The existing current renderer remains startup/default.

Switching renderers must not reload or mutate canonical workspace data.

## 4. V2 scene semantics: preserve the useful local "flower"

Unlike V1 Task-only skeleton, V2 should intentionally preserve the local structure that was readable in the current Graph.

For the currently selected/root Task, build a bounded local scene from already-loaded workspace data containing:

- the selected/root Task;
- directly connected Task neighbors already present in the workspace;
- directly connected non-Task evidence/context already present in the workspace;
- only existing edges between visible scene nodes.

Do not infer new edges.

Do not create a hierarchy.

Do not add Areas.

Do not run semantic clustering.

For an overview with no selected/root Task, it is acceptable to show a bounded set of loaded Task nodes only, but V2's primary evaluation target is the local Task-centered scene.

## 5. Flutter owns node rendering

ELK computes geometry only.

Continue rendering Task/evidence cards as Flutter widgets.

Do not render the graph as an image, canvas snapshot, HTML document, or package-owned card UI.

Use the returned node rectangles/positions to place Flutter widgets.

Existing Task selection must continue to open/reuse the canonical detail panel and Task Profile.

## 6. Routed edges are the main V2 proof

Use routed edge geometry returned by the ELK adapter when available.

The visual edge layer should support multi-segment paths/bend points rather than always drawing a single straight center-to-center line.

The experiment should aim for:

- edges terminating at/near card boundaries rather than card centers where the engine provides that geometry;
- bends/orthogonal sections when produced by the engine;
- no edge segment intentionally passing through an unrelated node rectangle when the engine can avoid it.

Do not implement a second general-purpose routing algorithm yourself.

A tiny adapter-level normalization of package output is fine.

## 7. Geometry-focused comparison scenes

Add deterministic client-side fixtures representing at least:

### A. Task flower
Approximately:
- 1 central Task;
- 2-4 nearby Tasks;
- 10-20 evidence/context nodes;
- mixed edge directions/types using existing relation semantics.

This models the user's current readable "romashka" case.

### B. Small activity cluster
Approximately:
- 6-12 Tasks;
- several Task-to-Task links;
- 15-30 context/evidence nodes around a subset of Tasks.

No synthetic new ontology is implied by these fixtures.

## 8. Required measurable probes

For both fixtures record, for the ELK result:

- layout completes or typed failure;
- visible node rectangle overlap count;
- number of routed edges returned with at least one non-trivial segment/bend when supported;
- number of obvious edge-vs-unrelated-node rectangle intersections detectable by the simple test harness;
- deterministic repeatability for the same scene;
- movement of common nodes after adding one evidence leaf to the selected Task.

The intersection probe may be conservative and test-oriented. Do not build a full computational-geometry subsystem.

If the ELK package does not expose routed sections/bends, record that as a major V2 finding instead of hand-building routing to hide the limitation.

## 9. Incremental/stability probe

We are not persisting coordinates yet.

But compare one base scene and the same scene after adding one evidence node.

Record how many pre-existing nodes move more than a small epsilon.

If the ELK API supports supplying prior positions/fixed nodes cleanly, add one narrowly scoped experiment using that feature.

Do not add DB/local-storage persistence of coordinates.

Do not create a custom force simulation.

## 10. Failure behavior

If ELK layout fails for a scene:

- canonical workspace data stays untouched;
- experimental renderer shows a concise error/fallback;
- user can switch immediately back to current/V1 renderers.

Do not silently fall back to a different geometry engine inside the V2 adapter.

## 11. Semantic zoom

Reuse the existing presentation-only semantic zoom primitives where practical.

Do not expand semantic zoom scope in V2.

The purpose of this stage is geometry/routing, not designing the final multilevel islands model.

## 12. Architectural preparation for later islands — no implementation yet

The new `TaskMapScene` / layout-engine boundary should not assume that every visible semantic item is a flat global node forever.

Avoid an API shape that would make later presentation-only grouping impossible.

However, V2 must NOT implement:

- Area entities;
- label-derived islands;
- connected-component islands;
- compound groups in the product UI;
- hierarchy/contains/part_of;
- automatic clustering.

Those belong to a later visual stage if this geometry spike succeeds.

## 13. Scope exclusions

Do not implement:

- ontology changes;
- backend changes;
- migrations;
- new Task relation types;
- Areas;
- Project entity;
- LLM clustering;
- attention ranking/scoring;
- automatic Task discovery;
- persisted coordinates;
- WebView;
- JavaScript graph engine;
- Graphviz/native FFI;
- yFiles/GoJS/Cytoscape/Sigma;
- production deploy.

## Focused proof

Add tests proving at minimum:

1. Existing current Graph renderer remains default.
2. V1 GraphView experiment remains available.
3. People mode is unchanged.
4. V2 consumes only existing controller/workspace data.
5. Canonical models do not depend on ELK package types.
6. The ELK-specific adapter is behind the layout-engine boundary.
7. Task-flower scene includes the center Task, loaded direct Task neighbors, loaded direct evidence/context, and only existing edges.
8. Unrelated loaded objects are not pulled into the local flower scene.
9. Flutter node widgets are positioned from layout output.
10. Selecting a V2 Task still reuses existing canonical detail/Task Profile UI.
11. ELK task-flower layout completes or returns a typed safe failure.
12. ELK small-cluster layout completes or returns a typed safe failure.
13. Node-overlap probe is recorded for both scenes.
14. Routed-edge/bend availability is recorded.
15. Simple edge-vs-unrelated-node intersection probe is recorded.
16. Same input scene produces deterministic normalized layout output within a reasonable epsilon, or nondeterminism is explicitly recorded as a finding.
17. Adding one evidence leaf records common-node movement.
18. ELK failure does not mutate workspace state and allows switching back.
19. No backend/schema/ontology/proactive changes.
20. No production deploy.

Run:

- existing Graph workspace/controller/screen/layout tests;
- V1 Task Map tests;
- new V2 ELK adapter/renderer/probe tests;
- Task Profile UI tests;
- `flutter pub get`;
- Flutter analyze touched files;
- `git diff --check`.

## Completion

When complete:

- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- record the pinned `elk` version;
- record the flower and cluster geometry observations:
  - overlaps;
  - routed-edge/bend support;
  - edge/node intersections;
  - repeatability;
  - one-leaf stability;
- state clearly whether ELK looks viable as a geometry engine for the next visual experiment;
- do NOT select a final graph technology automatically;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Do not begin islands/Areas/compound semantic grouping until Architect + user review V2.
