# Current task — GUX1 graph high-frequency UI/UX polish

Authorized base: `d0f672b9dd6c2c40f4cbeb7e0f98461db31ffd57`.
Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`.
PL1 is human-accepted and closed. Do not reopen its geography/ontology in this slice.

This is the first small Graph polish round before the next major Secretary-agent audit. It targets high-frequency desktop use while the user creates and maintains many Tasks and People.

## 1. Clean up the Graph toolbar

For normal desktop widths (the existing wide layout breakpoint is acceptable), make the top Graph toolbar read as one stable work surface rather than a developer/debug row.

Requirements:

- Keep the `Задачи / Люди` mode switch in a stable leading position.
- Task search and People search should use the same practical width, target about **220 px** on wide layout. Do not leave the Task placeholder clipped to `Поиск по гр...`.
- When a search query is non-empty and the field is not actively showing the progress indicator, expose a small clear action inside the field. Clearing removes current search chips/results without changing Graph mode/root/camera.
- Replace the English fCoSE labels `Preserve / Relax` with user-facing Russian labels reflecting their actual behavior:
  - `Плотно` for the default/50 edge-length mode;
  - `Свободнее` for the 90 edge-length mode.
- Add concise tooltips explaining that this changes spacing of movable neighboring/satellite presentation while fixed Task anchors stay fixed. Do not imply it changes canonical Task geography.
- Keep `К обзору` and `Уместить граф` available and tooltiped.
- Preserve responsive behavior: no overflow at the currently supported wide desktop size; narrow layouts may still wrap.

Do not redesign the whole application chrome or left navigation.

## 2. Make repeated Person creation cheap

Current `_openAddPerson` always reroots to the newly created Person. That is inconvenient when adding many People from the unrooted People overview.

Change only this path:

- If the user invokes `Добавить человека` from **unrooted People overview**:
  - create the Person through the existing API;
  - stay in unrooted People overview;
  - refresh the current People workspace so the new Person appears in the real unanchored shelf;
  - preserve the current shared camera/zoom;
  - do not automatically open the inspector;
  - do not automatically select/re-root the new Person;
  - show a small non-blocking confirmation such as `Добавлен: <title>`.
- If the same action is invoked while already in a rooted Person view, keep the existing behavior of opening/rerooting to the newly created Person.
- Existing dialog autofocus and Enter-to-submit behavior remain.
- Repeated additions must not duplicate an already successful request if the dialog/result refresh is slow.

Do not add heuristic Person/organization typing.

## 3. Compact the Task-window banner

The current long banner consumes a lot of vertical space in the Graph work surface.

For the unrooted Tasks overview when semantic windows are active:

- shorten the message to one compact line conveying only the durable fact: the user is seeing one region of the graph and the directions/branches in that region are complete;
- keep the existing area navigation controls;
- do not hide the fact that the view is partial;
- do not alter semantic-window membership or loading behavior.

The exact wording may be concise Russian UI copy, but avoid implementation terms.

## Preserve accepted PL1 behavior

Must remain unchanged:

- persisted canonical Task centers;
- shared Tasks/People world origin and camera parity;
- Task semantic-window index restoration across mode switch;
- Person anchoring/centroids;
- same-anchor 6 px compact clusters;
- 128x56 Person markers;
- unanchored shelf + edge cue;
- manual Fit semantics;
- rooted Person inspector behavior except the explicit creation rule above.

## Tests

Add/update focused Flutter tests proving at least:

- wide Tasks toolbar search no longer uses the old 140 px width / clipped-placeholder behavior;
- search clear removes query/results without changing mode/root;
- `Плотно` and `Свободнее` select the existing preserve/relax enum values and have explanatory tooltips;
- unrooted People add creates exactly once, remains unrooted, does not select/open inspector, refreshes People workspace, and leaves the transformation scale/camera unchanged;
- a second consecutive add works without returning to overview manually;
- rooted People add retains the existing reroot behavior;
- compact partial-graph banner remains visible and area navigation still works;
- Tasks<->People camera parity, task-layout world, People landscape/cluster/shelf cue, marker readability, graph smoke, and large-canvas tests remain green.

Run focused Graph/People/task-layout Flutter suites, smoke/large-canvas tests, `flutter analyze` for changed Dart files, and `git diff --check`.

## Explicitly out of scope

- No backend/API/schema changes.
- No production ref/deploy/client install.
- No Graph geography/layout algorithm changes.
- No new Task creation workflow.
- No keyboard-shortcut system.
- No combined Tasks+People mode.
- No organization/person entity type.
- No broad design-system rewrite.
- Do not begin the Secretary-agent audit in this slice.

## Completion contract

When complete:

- record implementation SHA, changed files, exact checks, and any UX limitation in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise GUX1 summary;
- commit/push to `main`;
- STOP.

Do not deploy or start later work without a new authorization.
