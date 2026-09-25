# Current task — Visual Task Map V1: GraphView layout spike

Task Refinement T1-T6 is architect-accepted. Do not continue Task Refinement in this stage.

Implement only an experimental, reversible visual Task Map spike over the existing canonical Graph workspace data.

This task is a product/visualization experiment. It must not change ontology, backend Task semantics, database schema, proactive behavior, Task lifecycle, Task Profile, or production deployment.

## Product intent

The current Graph UI is useful when focused on one Task and its evidence, but the all-task overview becomes visually unreadable as the workspace grows.

We need to evaluate whether a mature Flutter graph library can give us a better spatial model before investing in more custom layout code.

V1 is not the final Task UX. It is an instrument for comparing layouts on real data.

## Library choice for V1

Use the maintained Flutter package `graphview` as the only new visualization dependency in this spike.

Do not add a JavaScript/WebView graph engine, Cytoscape, Sigma, yFiles, GoJS, Plough, or another competing graph package in V1.

Pin a concrete compatible package version in `client/pubspec.yaml` and update `pubspec.lock`.

## 1. Preserve the existing Graph UI

The current graph renderer/layout remains the default and must continue to work unchanged.

Do not rewrite `GraphLayout`, remove the current `CustomPainter`, or migrate existing interactions to GraphView.

Add the experimental renderer behind an explicit UI switch available only in Graph -> Tasks mode, for example:

- `Текущий`
- `Эксперимент`

People mode must remain on the existing renderer.

A user must be able to switch back immediately without data reload or loss of selected root where practical.

## 2. Reuse exactly the same canonical workspace data

The experiment must consume the existing `GraphWorkspaceController` / `GraphWorkspaceOut` nodes and edges.

No new backend endpoint.
No alternate task database query.
No migration.
No duplicate Task model.
No synthetic production data.

The point is to compare visualization, not data semantics.

## 3. Task-first experimental projection

In experimental mode, default to a Task-first skeleton:

- Task nodes are always eligible for rendering.
- Evidence/context objects (email, file, event, message, etc.) are hidden by default.
- Existing Task-to-Task edges are rendered when both endpoints are visible.
- Existing non-Task context can be revealed for the currently selected Task with one explicit `Контекст` toggle/action.
- Context reveal uses only objects already present in the bounded workspace; do not fetch an unbounded graph.
- Turning context off returns to the Task skeleton.

Do not infer new hierarchy, Areas, parent/child semantics, or relation types.

If the existing workspace has no Task-to-Task edge between two Tasks, do not invent one merely for layout.

## 4. Compare three GraphView layouts

Provide a compact layout selector in experimental mode for exactly these V1 variants:

1. Mind map / mind-map-like layout provided by GraphView where supported.
2. Radial tree / radial layout.
3. Fruchterman-Reingold force-directed layout.

If the package API names differ, use the closest documented algorithms from the pinned GraphView version.

The selected layout is presentation state only.

No backend persistence is required.

## 5. Semantic zoom V1 — presentation only

Implement a small first semantic-zoom experiment driven only by viewport scale.

At minimum use three visual density levels:

### Near
Task node shows:
- title;
- concise lifecycle/operational cue if already available in current client state;
- due date if available.

### Middle
Task node shows:
- title;
- at most one compact attention/time cue.

### Far
Task node becomes a compact labeled marker:
- short title or ellipsized title;
- no body/evidence details.

Context/evidence nodes should simplify more aggressively than Tasks.

Important:
- semantic zoom changes only node presentation, never data membership or Task semantics;
- do not compute new priority scores;
- do not persist zoom-derived state.

If GraphView does not expose a convenient scale callback, use the enclosing Flutter transformation/viewport controller rather than forking the package.

## 6. Focus behavior

Selecting a Task in experimental mode should:

- keep the selected Task visually prominent;
- dim unrelated visible nodes/edges where practical;
- preserve the existing detail panel / Task Profile interaction;
- allow context reveal for that Task;
- allow re-root / existing navigation behavior where technically compatible without rewriting controller semantics.

Do not create a separate Task detail implementation.

## 7. Spatial stability observation

Do not build persistence of coordinates yet.

But structure the experimental renderer so a later stable-position strategy is possible.

For V1, record in code comments / PROJECT_STATE observations whether each layout visibly repositions most nodes when:
- one node is added;
- context is toggled;
- root changes.

Do not add DB fields or local persistence for coordinates.

## 8. Bounded performance probe

Add a deterministic client-side fixture/test or benchmark-style harness that can render or lay out representative graphs at approximately:

- 20 visible nodes;
- 50 visible nodes;
- 100 visible nodes.

This is not a formal performance certification.

Record:
- whether layout completes without exception;
- whether widget tests remain tractable;
- any obvious layout limitation encountered.

Do not increase backend workspace caps merely to satisfy the probe.

## 9. Experimental status must be obvious

Label the renderer clearly as experimental, e.g. `Экспериментальная карта`.

Do not make it the startup default.

Do not remove the current graph warning/truncation semantics.

If GraphView cannot faithfully render a current edge or node, fail visually conservatively rather than changing canonical data.

## 10. Scope exclusions

Do not implement in V1:

- ontology changes;
- Areas;
- parent/child Task hierarchy;
- `contains` / `part_of` relation;
- automatic grouping or clustering by LLM;
- attention scoring/ranking;
- new backend API;
- persisted coordinates;
- 3D sphere;
- true fisheye distortion;
- new Task discovery;
- production deploy;
- People visualization rewrite.

## Focused proof

Add tests proving at minimum:

1. Existing Graph Tasks renderer remains the default.
2. People mode still uses the existing renderer.
3. Experimental mode consumes existing controller workspace nodes/edges.
4. Task skeleton hides non-Task context by default.
5. Context toggle reveals only already-loaded neighbors for the selected Task.
6. Turning context off restores the Task-first skeleton.
7. Layout selector exposes the three V1 algorithms.
8. Switching layouts does not mutate workspace data.
9. Near semantic zoom shows the richer Task node.
10. Middle semantic zoom simplifies it.
11. Far semantic zoom uses compact Task presentation.
12. Evidence/context nodes simplify more aggressively than Task nodes.
13. Task selection still opens/reuses the canonical existing detail/Task Profile surface.
14. Current renderer behavior remains green.
15. 20-node fixture renders/layouts without exception.
16. 50-node fixture renders/layouts without exception.
17. 100-node fixture renders/layouts without exception or, if the package has a deterministic practical limitation, the limitation is documented and the UI fails safely.
18. No backend/schema/ontology/proactive changes.
19. No production deploy.

Run:
- existing Graph workspace/controller/screen tests;
- existing Task Profile UI tests;
- new experimental Task Map tests;
- Flutter analyze touched files;
- `flutter pub get` / lockfile consistency;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- explicitly record qualitative observations for Mind map vs Radial vs Force-directed on the 20/50/100-node fixtures;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Do not select a winning layout or begin V2 automatically. Architect + user will inspect the experiment before the next task.
