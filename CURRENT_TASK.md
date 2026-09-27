# Current task — Graph G3A-R3: reversible local relation context

Graph G3A/G3A-R1/G3A-R2 are human-accepted.
Assistant P1 is deployed.

Production backend/runtime and `origin/production`:
`7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4`

Alembic:
`0050`

This task authorizes ONE bounded CLIENT Graph UX corrective on `main`.

NO production deploy is authorized.
No backend/schema/API change is expected.

Do not start G3B, Task MCP parity/H2D, Person/Organization ontology work, S3, or any unrelated cleanup.

## Human problem

Current Graph detail action is one-way:

`Показать связи` -> `expandSelected()` -> rooted workspace fetch -> `_mergeWorkspace(...)`.

This is useful: a completed Task omitted from default overview can be revealed through its Direction, then its own local Flow/evidence can be revealed.

But there is no inverse. Once local context is merged into the canvas, the user cannot remove it without reloading/re-rooting the broader view.

Desired interaction:

`Показать связи` <-> `Скрыть связи`

Local expansion is a VIEW operation only. It must never create/delete/reject relations or objects.

## Product invariant

The current semantic overview/rooted workspace is the authoritative BASE.

Each explicit `Показать связи` adds one local-context overlay identified by the selected object's id.

`Скрыть связи` for that object removes only that explicit overlay, then reconstructs the visible graph from authoritative server truth:

1. refetch the current BASE;
2. replay every other still-active local-context overlay;
3. replace the displayed state atomically.

Do NOT infer which nodes "belong" to an overlay by subtracting ids from the current graph.

Two overlays may share nodes/edges. Shared context must remain if another active overlay still returns it.

## Part A — explicit expansion state

Add controller state for active local-context expansion anchors.

Minimum public/read API:

- `bool isLocalContextExpanded(String objectId)`;
- enough observable state for focused tests.

Rules:

- successful `expandSelected()` records the selected object id once;
- repeated Show on the same active anchor must not duplicate the anchor or grow state;
- a failed expansion must not mark it active;
- ordinary selection/focus/camera changes do not clear active expansion state.

Do not persist this state to backend, SharedPreferences, or DB.

## Part B — Show / Hide button

For the currently selected object:

- when its id is NOT an active expansion anchor:
  - tooltip and label: `Показать связи`;
  - action: existing expand path;
- when its id IS an active expansion anchor:
  - tooltip and label: `Скрыть связи`;
  - action: new hide method.

Use a sensible inverse icon; do not redesign the detail toolbar.

The state is per explicitly expanded anchor, not "any extra node happens to be visible".

A node already present in the base may still be an active expansion anchor if the human pressed Show on it.

## Part C — authoritative Hide algorithm

Implement a controller method in substance:

`Future<void> hideLocalContext(String objectId)`

Do NOT simply delete current nodes/edges.

Determine the remaining active anchors after removing `objectId`.

### Overview base

If `rootId == null`:

- refetch the current `windowIndex`;
- preserve the G3A semantic-window contract;
- if that index has become invalid, recover once to window 0 using the existing deterministic out-of-range behavior;
- do not merge another semantic window.

### Rooted base

If `rootId != null`:

- refetch that exact rooted workspace as base;
- preserve existing missing/deleted-root fallback semantics.

### Replay

After obtaining the base response:

- fetch rooted workspace for each remaining active expansion anchor;
- replay in deterministic activation order;
- merge each response using the existing incremental local-context layout behavior;
- do not convert replay into a permanent re-root.

Important: perform network reads before committing destructive replacement where practical. A failed Hide must not leave a half-rebuilt graph.

## Part D — atomic failure behavior

Hide is read-only.

If the authoritative base/replay refresh fails:

- keep the currently visible graph usable rather than partially stripping it;
- keep the prior active-expansion bookkeeping unchanged;
- expose a recoverable error in substance:
  `Не удалось скрыть связи. Обновите обзор и повторите.`
- no automatic retry loop;
- no writes.

Authentication handling remains canonical.

If one replay anchor is genuinely no longer available because the object is gone/inactive, it may be dropped deterministically during rebuild; do not invent a placeholder.

## Part E — selection and camera

After successful Hide:

- if the currently selected object still exists in the rebuilt graph, keep it selected;
- otherwise clear selection;
- clear a selected edge if that edge is no longer present;
- request one fit after the authoritative rebuild.

When hiding the selected anchor itself, keep it selected if it belongs to the base or remains through another active overlay.

Preserve Preserve/Relax mode.

## Part F — reset/invalidation rules

Active local-context overlays are presentation state tied to one base workspace.

Clear them when the base identity is replaced by ordinary navigation, including:

- switching Tasks <-> People;
- `loadOverview()`;
- loading another overview window;
- previous/next semantic window;
- explicit `reRoot(...)`;
- fallback from missing root to overview;
- any authoritative fresh replacement caused by G3A-R1 Task<->Task topology mutation.

A normal `refreshCurrentWorkspace()` may clear overlays rather than silently replay them unless the refresh is the internal Hide rebuild described above.

This task must NOT weaken G3A-R1 topology invalidation.

Ordinary Task<->Flow relation writes may occur while local context is visible. A later Hide must refetch authoritative base/replays so persisted writes remain visible wherever the server says they belong.

## Part G — do not corrupt G3A metadata

Local Show/Hide must not redefine semantic-window membership.

After successful Hide/rebuild in Tasks overview:

- `window_index`;
- `window_count`;
- previous/next flags;
- `constellation_root_ids`;
- `semantic_window_complete`

must come from the authoritative base overview response, not a rooted replay.

Do not change G3A packing/window rules.

## Part H — People mode

The detail action currently exists for Graph objects generally and `expandSelected()` already uses mode-aware workspace fetches.

Make the reversible behavior mode-safe:

- if existing Show works in People mode, Hide must also safely restore the People base and replay remaining People-mode contexts;
- do not introduce organization relations or new People semantics;
- no Person identity/evidence mutation is part of Show/Hide.

If a genuine existing People-mode contract prevents a correct generic implementation, STOP and report the exact blocker rather than inventing semantics.

## Required client regressions

Add focused controller/widget tests covering at least:

1. **single overview toggle**
   - base has Direction/Task A;
   - Show A admits local object X;
   - A becomes expanded;
   - button becomes `Скрыть связи`;
   - Hide A refetches base;
   - X disappears when not part of base;
   - A remains selected;
   - button returns to `Показать связи`.

2. **completed historical Task scenario**
   - completed child omitted from default overview;
   - expanding its visible parent admits it;
   - hiding parent returns to default overview without deleting the completed Task or any relation.

3. **nested / multiple expansions**
   - Show A;
   - select B and Show B;
   - Hide B keeps A's expansion;
   - Hide A then returns to base.

4. **shared context**
   - A and B rooted responses both contain X;
   - hiding A while B remains active keeps X.

5. **hide earlier anchor**
   - with A and B active, hide A;
   - authoritative base + B replay remains;
   - B is still marked expanded.

6. **no duplicate active anchor**
   - repeated programmatic expansion of A does not duplicate bookkeeping.

7. **failed Show**
   - graph remains;
   - A is not marked expanded.

8. **failed Hide**
   - current graph remains intact;
   - expansion bookkeeping remains intact;
   - recoverable error is shown;
   - no partial rebuild.

9. **overview metadata**
   - rooted replay has different/default metadata;
   - after Hide the controller keeps authoritative base `windowIndex/windowCount/flags/constellationRootIds/semanticWindowComplete`.

10. **invalid prior window**
    - Hide base fetch sees out-of-range current window;
    - recovers once to window 0;
    - no retry loop.

11. **rooted base**
    - Show/Hide inside an already rooted workspace restores that rooted base rather than overview.

12. **selection**
    - selection persists if node survives;
    - selection clears if it disappears after Hide.

13. **navigation invalidation**
    - reRoot, mode switch, and overview-window navigation clear local expansion state.

14. **topology mutation invalidation**
    - G3A-R1 fresh Task<->Task refresh clears local expansion state and keeps its fresh-layout/fit behavior.

15. **Task<->Flow control**
    - ordinary persisted evidence added while an overlay is visible is not rolled back/lost by later Hide; authoritative refetch decides visibility.

16. **People-mode safety**
    - if current existing People Show path is supported, one focused Show/Hide test restores People base without changing Person evidence.

Use fake API responses. No live backend/provider dependency.

## Existing regressions to run

Run relevant client suites at minimum:

- `client/test/graph/graph_workspace_controller_test.dart`;
- `client/test/graph/graph_workspace_screen_test.dart`;
- G3A semantic-window tests;
- G3A-R1 topology refresh tests;
- G3A-R2 hierarchy packing tests;
- direct relation inventory;
- proposed relations;
- People workspace;
- hybrid/focus LOD.

Run Flutter analyze on touched client files.
Run `git diff --check`.
Run `flutter build linux --debug`.

The known legacy object-detail finder failures for `Удалить` / `Спросить секретаря` are not authorization for unrelated fixes.

## Backend

No backend product change is expected.
No API/schema/migration change.

If the client cannot implement this correctly with existing workspace endpoints, STOP and report the exact missing backend contract. Do not widen scope yourself.

## Explicitly forbidden

Do NOT:

- deploy production;
- move `origin/production`;
- mutate production data;
- change relation persistence/state;
- add relation types;
- implement G3B pan/lens loading;
- implement Task MCP parity/H2D;
- design or implement Person/Organization ontology;
- change Secretary prompt;
- change raw Graph node limits;
- change G3A semantic-window packing;
- fix unrelated tests.

## Completion

On completion:

1. update `PROJECT_STATE.md` with:
   - reversible-context model;
   - exact active-anchor semantics;
   - Hide authoritative base + replay behavior;
   - invalidation rules;
   - failure behavior;
   - test/analyze/build results;
   - implementation SHA;
   - confirmation that backend/schema/persistence semantics are unchanged;
2. return `CURRENT_TASK.md` to HOLD;
3. push implementation/HOLD commits to `main`;
4. do not deploy;
5. STOP.

Final report must state:

- how Show/Hide state is represented;
- exact Hide reconstruction algorithm;
- behavior with multiple/shared expansions;
- navigation/topology invalidation behavior;
- failure behavior;
- People-mode result;
- tests/analyze/build;
- backend/schema changed? expected NO;
- implementation SHA;
- HOLD/main SHA;
- absolute Linux debug bundle path for human gate.

Then STOP. Do not start Task MCP parity or any next phase.
