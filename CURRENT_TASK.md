# Current task — PL1-E People Landscape screen wiring

Authorized base: `9351f2b36bd7c4a014985890f1fe9a19f95f4ca6`.

People PL1-D is accepted and implemented at `fdf66ca033e50f2348b1c9f1bb197351e45cd2ab`. The next bounded slice is authorized now.

## Goal

Wire the already implemented `projectPeopleLandscapeOverview` projection into the real People overview screen, while preserving the existing People grid as a full fail-closed fallback.

## Scope

1. Client only. Do not change backend, API contracts, migrations, production, or deployment code.
2. In `GraphWorkspaceScreen`, only when:
   - `mode == GraphWorkspaceMode.people`
   - `rootId == null`

   build `PeopleLandscapeOverview` from:
   - visible Person ids;
   - the corresponding `PersonPresentation` values;
   - `controller.landscapeTasks`;
   - `controller.landscapeTaskEdges`;
   - `controller.landscapeTaskContextComplete`.
3. When `projection.usable == true`, use `projection.positions` for the People overview instead of the current ranked-grid `projectPeopleOverview`.
4. When `projection.usable == false`, fail closed in the UI by using the existing `projectPeopleOverview` for the whole People overview. Do not mix partial landscape geometry with the old grid.
5. A complete empty anchor set is a valid unanchored state. Such People must remain visible on the deterministic non-semantic shelf already implemented by PL1-D.
6. The PL1-C Task context is geography input only. Task nodes and Task edges must not be rendered on the People canvas.
7. Rooted Person presentation (`rootId != null`) is out of scope and must remain unchanged.
8. Do not change People inspector behavior, candidate queue, Person detail, selection semantics, search, Task mode, Task graph layout, or social/organization ontology.
9. Manual Fit and automatic post-load fit must use the same effective positions that are actually rendered on the People canvas. Do not leave Fit calculating from stale `controller.visiblePositions` while landscape coordinates are drawn.

## Tests

Add focused widget/regression coverage for at least:

- complete usable landscape -> the screen uses landscape positions rather than the old People grid;
- a genuinely unanchored Person remains visible on the shelf;
- incomplete Task context, incomplete Person anchor set, or missing expected anchor -> whole overview falls back to the existing People grid with no partial landscape;
- Task geography context never renders Task cards on the People canvas;
- manual Fit and automatic fit use the effective landscape positions;
- rooted Person presentation remains unchanged.

Reuse the existing PL1-A/PL1-D helpers. Do not create a second layout algorithm.

Run the focused Flutter tests plus the affected People workspace/screen regressions, `flutter analyze` for changed Dart files, and `git diff --check`.

## Completion contract

When the slice is complete:

- record the exact implementation SHA, changed files, test/analyze results, and any known limitations in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-E completion summary;
- commit and push to `main`;
- STOP.

Do not deploy to production and do not start PL1-F or any later slice without a new explicit authorization in this file.
