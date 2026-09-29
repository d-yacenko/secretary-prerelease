# Current task — PL1-G Task-window geography parity

Authorized base: `36734b8786c3d01f6ec66fabeb3448a59cbbd758`.
Current production/runtime remains `666683134797948871266e84fd105f0ca0c43476`.

The second human gate confirmed that Person identity-to-card mapping and the right-side unanchored strip are now working, but the anchored macro-geography still does not match the Task screen.

Root cause: the Task screen runs `projectTaskMapHierarchy` over one complete semantic Task window, while the People workspace currently returns only the union of anchor constellations. The hierarchy packer is not subset-stable, so the same Task can move to a different packed region when unrelated components from its semantic window are omitted.

## Goal

Make People Landscape derive anchored Person geography from the same Task semantic-window membership that the Task screen uses, without persisting coordinates and without duplicating the Task layout algorithm.

## Scope

This slice may change backend read-model code, additive API schema/client models, and client People landscape projection. Do not deploy, migrate, mutate production data, replace the installed client, or begin later slices.

### Backend/read model

1. Reuse the existing Task semantic-overview window construction in `GraphWorkspaceService`. Do not implement a second window-packing algorithm.
2. For the complete set of confirmed active `landscape_task_ids` exposed for visible People:
   - identify the Task semantic overview window containing each anchor;
   - include each distinct relevant semantic window once;
   - preserve its real `window_index`;
   - return the complete Task membership required to reproduce that window's Task hierarchy projection.
3. The People landscape payload for each relevant window must contain Task objects plus Task<->Task edges only. Do not expose Flow or Person nodes as landscape geography.
4. Window membership must match what `getGraphWorkspace(window_index: ...)` would use for the same repository state. In particular, unrelated Task components that share that semantic window must remain present; do not reduce the payload back to only anchor constellations.
5. Keep the API bounded. If any complete anchor cannot be resolved to a semantic window, or the configured landscape window/task cap would be exceeded, fail closed:
   - return no usable landscape windows;
   - set landscape context completeness false.
6. Make the schema additive/backward-compatible. Keep the existing flat landscape fields until a later cleanup slice; add an explicit windowed landscape representation rather than changing their semantics silently.
7. Coordinates must not be calculated or stored by the backend.

### Client projection

8. Parse/store the new windowed Task geography in `GraphWorkspaceController` on authoritative People workspace replace/reset.
9. For a usable unrooted People overview:
   - run the existing `projectTaskMapHierarchy` separately for each returned Task semantic window;
   - never run it once over a flat union of multiple windows;
   - normalize/tile distinct windows deterministically in ascending `window_index` with a non-semantic gap so their internal geometry remains unchanged;
   - build one Task-id -> top-left map from those per-window projections.
10. For a single relevant semantic window, every anchor Task's relative geometry must be identical to the Task screen's projection for that same window, modulo one global translation. This is the primary acceptance invariant.
11. Person placement continues from that combined Task-id map:
   - one anchor -> that Task position;
   - several distinct anchors -> unweighted centroid;
   - same Task across roles deduplicated;
   - deterministic local Person anti-overlap from PL1-F remains;
   - no role/salience/recency/authority weighting.
12. A Person anchored across multiple Task windows may use the centroid of the deterministic tiled window positions. The tiling itself has no semantic meaning.
13. Complete-empty-anchor People remain in the PL1-F right-edge vertical strip, to the right of all tiled Task-window bounds and anchored Person cards.
14. Any incomplete/missing window geography still falls back to the whole existing `projectPeopleOverview` grid. Never mix partial window geography with fallback coordinates.
15. Keep PL1-F compact 156x56 unrooted cards, Person-id widget keys, Fit behavior, rooted Person view, inspector/details, search, Task mode, and hidden Task-card behavior unchanged except where needed to consume the corrected geography.

## Tests

Add focused coverage that would have failed in PL1-F:

- backend parity: when an anchor Task shares a semantic Task window with unrelated Task components, the People landscape window includes the same Task membership as the Task overview window rather than only the anchor constellation;
- backend: multiple anchors in the same semantic window produce one window entry;
- backend: anchors in distinct semantic windows produce distinct ordered window entries;
- backend: unresolved anchor or cap overflow fails closed;
- client parity: for a single returned semantic window, the Task-id positions used for People equal `projectTaskMapHierarchy` on the actual Task-window nodes/edges up to one translation, including unrelated components;
- regression fixture with at least three distinct anchor Tasks/components verifies that changing the reduced anchor subset would have changed packing, while the new windowed input preserves Task-screen relative geography;
- multiple windows are projected independently and tiled deterministically;
- same-anchor People still spread locally without overlap;
- right-edge unanchored strip remains to the right of all relevant window geography;
- fail-closed fallback remains whole-grid;
- compact cards, Person-id mapping, hidden Task cards, manual/auto Fit, and rooted Person presentation remain unchanged.

Run focused backend tests, focused Flutter PL1 tests, `flutter analyze` for changed Dart files, and `git diff --check`.

## Completion contract

When complete:

- record implementation SHA, changed files, exact test/analyze results, and any known limitations in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-G completion summary;
- commit and push to `main`;
- STOP.

Do not deploy, do not build a human-gate bundle, and do not start PL1-H or any later slice without a new explicit authorization in this file.
