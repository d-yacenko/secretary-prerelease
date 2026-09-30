# Current task — GFX-HG1 exact-source Linux client bundle for human verification

Authorized base: `de4fc4a8113a3091de1bbda5f481c54ddbb4f6fc`.
Exact accepted client candidate source: `09b19d689462d3c0c49889620a7695707313cb3a`.
Accepted GFX-A source: `0fd1088f53ad9bc384c92ac2f38e0808b1097f86`.
Accepted GFX-B source: `cf812130c59c45eee25a3a96720c0f0fe99b3c29`.
GFX-B.1 correction included in candidate: `09b19d689462d3c0c49889620a7695707313cb3a`.
Current production/runtime backend source: `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.
Production Alembic: `0052 / 0052`.

GFX-A and GFX-B (including GFX-B.1) are Architect-accepted. This task prepares a new **Linux application build for the user's manual verification**. It is release preparation only: no product development, no production deployment, and no automatic replacement of the user's currently installed client.

## Goal

Produce one clean, self-contained Linux debug client bundle containing the accepted Graph fixes so the user can manually verify all three requested behaviors:

1. duplicate Task titles in relation-target search are disambiguated by confirmed immediate `part_of` parent;
2. Task rename is reflected immediately on the Graph;
3. existing `part_of` can be created by dragging from a Task connection handle to another Task.

## Exact source and provenance

1. Build from a clean detached checkout of exactly:
   `09b19d689462d3c0c49889620a7695707313cb3a`.
2. Do not build from a mutable working-tree tip and do not synthesize/cherry-pick a client-only commit.
3. Verify the candidate descends from production `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.
4. Compare production -> candidate and fail closed on unexpected server/runtime/schema/config changes.
   - `backend/app/**` must be unchanged for these fixes.
   - `backend/alembic/**` must be unchanged.
   - production dependency/runtime configuration must be unchanged.
   - reviewed ledger/test/ops-only deltas do not by themselves block the client bundle.
5. Record:
   - exact source SHA;
   - production backend SHA;
   - build mode;
   - UTC timestamp;
   - executable path;
   - launcher/executable SHA-256;
   - Flutter kernel SHA-256 if present;
   - adjacent plain-text `BUILD_INFO.txt`.
6. Confirm the detached source checkout remains clean after building.

## Verification before bundle

Run the focused accepted regression suites covering at least:

- GFX-A duplicate relation-target labels and exact target selection;
- GFX-A Task rename in unrooted, rooted, and «Подробнее» paths;
- existing `part_of` dialog;
- GFX-B drag:
  - handles/visibility;
  - source child -> target parent payload;
  - zoom/pan transformed camera;
  - cancel/self/non-Task cases;
  - backend validation failure;
  - in-flight double-submit blocking;
  - GFX-B.1 delayed rejection followed immediately by another usable drag;
- task-layout world;
- Graph smoke and large-canvas;
- Tasks<->People shared-world/camera and shelf cue regressions touched by shared Graph rendering.

Run `flutter analyze` for the changed Graph Dart files and `git diff --check`.

Do not change product source to make tests/build pass. If exact-source build or required checks fail, record the blocker, return to HOLD, and STOP.

## Bundle

Produce one self-contained Linux debug application bundle under a clearly named temporary directory, for example:

`/tmp/gfx-hg1-09b19d6-artifact/`

The bundle must be directly usable for the normal manual client spot-check workflow and must include an adjacent `BUILD_INFO.txt`.

Do **not**:

- install it over the user's current client;
- deploy backend or frontend production;
- move `refs/heads/production`;
- run Alembic;
- mutate production Task/Person/relation/layout data;
- perform the human acceptance yourself.

## Human verification checklist to include in BUILD_INFO.txt / ledger

### 1. Duplicate titles

Use two Tasks with the same title but different confirmed immediate `part_of` parents. In «Добавить связь» search, verify they appear distinctly, e.g.:

- `Обучение (Основная работа)`;
- `Обучение (Академическая деятельность)`.

Verify a unique Task title remains undecorated and selecting either duplicate targets the intended Task.

Known accepted limitation: two duplicates with the same confirmed parent, or two with no confirmed parent, can still have the same suffix.

### 2. Rename propagation

From Graph Task management, rename a visible Task and verify the node title changes immediately without waiting/restart.

Also spot-check the «Подробнее» edit path. The old title must not reappear after returning.

A title-only rename must not semantically repack Task geography.

### 3. Drag-to-create part_of

In Tasks mode:

- hover/select a Task and observe the small perimeter connection handles;
- drag from a child Task handle toward another Task;
- verify a temporary solid line with arrow follows the drag;
- drop on the intended parent Task;
- verify the resulting relation is the existing `part_of` / «входит в» and direction is child -> parent;
- drop on empty canvas/self/non-Task and verify nothing is created;
- verify normal canvas pan/zoom still works outside handles;
- if practical, trigger a backend validation rejection and verify handles are immediately usable for another drag afterward.

Other relation types must still use «Добавить связь».

## Explicitly out of scope

- No product source changes.
- No new relation type.
- No backend/API/schema/Alembic changes.
- No production ref movement/deploy.
- No installed-client replacement.
- No old GUX1 work.
- No further Graph polish.
- No Secretary Agent/Harness audit.

## Completion contract

When complete:

1. record artifact path, provenance, hashes, exact checks, and confirmation of no production/installed-client mutation in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus the exact bundle path/hash summary and human checklist status «not performed»;
3. commit/push ledger changes to `main`;
4. STOP.

Do not perform the human gate and do not begin later work.
