# Current task — PL1-G4 People overlay on the canonical Task world

Authorized base: `97e708c464f8d446c3ca86e64dccb230f2d91103`.
Production/runtime remains `666683134797948871266e84fd105f0ca0c43476`.
Repository Alembic head is `0052`; production Alembic remains `0051 / 0051`.

PL1-G3 is accepted. This slice moves the unrooted People overview onto the same canonical Task-center world and makes unrooted Tasks/People mode switching preserve one world camera. It does not add the future combined Tasks+People mode.

## Architectural invariant

There is one world coordinate system.

- Canonical persisted Task centers are the world anchors.
- Tasks mode draws Task presentation on those anchors.
- People mode hides Task cards and draws Person presentation derived from those same anchors.
- People never persist their own coordinates.
- A healthy Tasks <-> People switch changes the visible layer, not the world geography or camera.

## 1. Canonical Task world availability in People mode

Refactor the PL1-G3 canonical Task-layout resolver so an unrooted People overview can use the same current `task-map-v1` snapshot even when People mode is entered before/without a fresh Tasks overview load.

Requirements:

1. Reuse one resolver/state path; do not create a People-specific Task layout cache.
2. If canonical centers are already active and remain valid for the current session, switching modes must not discard them.
3. If People mode needs centers and none are active, resolve through the same `GET /graph/task-layout` -> optional complete-topology recompute -> `PUT` contract from G3.
4. Keep the one-conflict retry bound from G3.
5. Auth/session reset still clears canonical centers.
6. Do not change backend/API/migrations in this slice.

## 2. People projection from Task centers

Replace the unrooted People geography input based on `landscape_tasks` / `landscape_task_edges` hierarchy reconstruction with direct use of canonical Task centers.

The old backend landscape fields may remain parsed for compatibility but must no longer define unrooted People coordinates when canonical centers are usable.

For each visible Person:

- missing Person presentation -> unresolved;
- `landscape_task_ids_complete == false` -> unresolved;
- complete empty Task anchor set -> genuinely unanchored;
- one distinct anchor -> Person base **center** is that Task center;
- multiple distinct anchors -> Person base center is the unweighted arithmetic centroid of those Task centers;
- same Task id across roles counts once;
- any supposedly complete anchor missing from canonical Task centers -> unresolved.

If any Person is unresolved, fail the **whole** People overview closed to the existing `projectPeopleOverview` grid. Never mix canonical-world People with fallback-grid People.

Keep:
- no role/salience/recency/authority weighting;
- deterministic stable ordering by Person id;
- deterministic local anti-overlap around the base center;
- no persisted Person coordinates.

## 3. Compact Person marker

For the unrooted People world view only, replace the temporary 156x56 overview card with a smaller compact marker.

Target marker size: **140x44**.

Presentation:
- small human/head-and-shoulders glyph or equivalent Person icon;
- primary line: Person display name;
- optional second line: at most one short existing explicit identity cue if useful;
- no Task/message metrics;
- no inferred company/organization;
- click/tap selection must still open the existing Person inspector/details.

Rooted Person presentation and inspector remain unchanged.

The marker's geometric center, not its top-left, is what is anchored/spread around Task centers.

## 4. Local spread and unanchored strip

Anchored People:
- spread only when compact markers overlap or nearly overlap;
- deterministic, stable by Person id;
- preserve the coarse Task/centroid region;
- no randomness and no semantic weighting.

Unanchored People:
- one deterministic vertical strip ordered by Person id;
- strip is to the right of the **full canonical Task world bounds**, not merely the currently visible Task semantic window;
- the strip remains explicitly non-semantic;
- anchored People never enter it.

If there are no canonical Tasks and all People are genuinely unanchored, use the existing neutral origin convention for the strip.

## 5. One shared unrooted world camera

The existing `TransformationController` is one camera, but current canvas normalization may shift world coordinates when visible bounds change. Fix this at the presentation/frame layer.

Healthy unrooted Tasks <-> People mode switch requirements:

1. Do **not** request automatic Fit merely because mode changes.
2. Preserve scale and world focus across the switch.
3. A chosen canonical Task center/world point must map to the same viewport pixel immediately before and after the switch, within a small test epsilon.
4. Do not satisfy this only by asserting the raw Matrix4 is unchanged if changing canvas origin would still move world points.
5. It is acceptable to refactor the world-to-canvas frame or compensate the camera when canvas origin/extents change.
6. Manual `Уместить граф` remains mode-specific:
   - Tasks mode fits the actually rendered Task/hybrid scene;
   - People mode fits compact Person markers including the unanchored strip.
   After manual Fit, the resulting camera remains the same shared camera when switching modes.
7. Initial app/overview load may still auto-fit as before. Rooted views may keep existing fit behavior.
8. Preserve the previously selected Task overview window when temporarily switching to People and back; a layer switch should not silently force Tasks back to semantic window 0.

The shared-camera invariant only applies when canonical Task world resolution is healthy. In explicit degraded fallback mode, preserve safe existing behavior; do not fake parity.

## 6. Rendering boundaries

People-only mode:
- do not render Task cards;
- do not render Task<->Person relation lines yet;
- do not render the future combined layer.

Tasks mode:
- keep G3 canonical Task anchors;
- Task/Flow hybrid presentation remains unchanged except for any world-frame refactor strictly needed for camera parity.

Rooted Task and rooted Person views remain unchanged.

Search, People inspector, promotion/consolidation UI, and Task semantics remain unchanged.

## Explicitly out of scope

- No backend changes.
- No Alembic changes.
- No production deploy/migration.
- No combined Tasks+People mode.
- No Task<->Person lines on the canvas.
- No social/authority ontology.
- No inferred organization/company.
- No installed-client replacement.
- Do not start PL1-G5, rollout, or human-gate bundle work.

## Tests

Add/update focused Flutter tests covering at least:

- People mode can resolve/use the same canonical `task-map-v1` world without a separate People geography calculation;
- one-anchor Person marker center matches that exact Task center before local spread;
- multi-anchor Person base center is the unweighted centroid of distinct canonical Task centers;
- repeated same Task id is deduplicated;
- order permutations/rebuilds do not swap Person ids or positions;
- same-anchor People locally spread without overlap and stay near the Task region;
- incomplete Person anchors, missing Person presentation, or missing expected Task center cause whole-grid fallback;
- complete-empty-anchor People form one right-side vertical strip outside full canonical Task bounds;
- compact unrooted marker is 140x44, shows name + optional explicit short cue, and rooted Person/inspector stay unchanged;
- Task cards remain absent from People-only canvas;
- healthy Tasks -> People -> Tasks switch preserves a canonical world point at the same viewport pixel and preserves scale;
- mode switch itself does not auto-fit;
- Task overview window index is restored after switching to People and back;
- manual Fit in each mode fits its rendered scene and its resulting camera is retained across the next layer switch;
- G3 Task canonical positioning remains unchanged;
- degraded canonical-layout failure still falls back safely without partial People geography.

Run focused People landscape/screen/controller tests, G3 task-layout tests, affected graph workspace/screen regressions, `flutter analyze` for changed Dart files, and `git diff --check`.

## Completion contract

When complete:

- record implementation SHA, changed files, exact test/analyze/diff results, camera-parity behavior, fallback behavior, and any known limitations in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-G4 summary;
- commit and push to `main`;
- STOP.

Do not deploy, migrate production, build a human-gate bundle, modify the installed client, or begin any later slice without a new explicit authorization in this file.
