# Current task — GFX-C human-regression fixes: rename + relation picker scroll

Authorized base: `976286b38b6e17c1a492c5ce0ba58dc84e353a8a`.
Human-tested client source: `09b19d689462d3c0c49889620a7695707313cb3a`.
Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`.

The user manually verified the GFX-HG1 build.

Human result:
- GFX-A duplicate-title disambiguation: PASS.
- GFX-B drag-to-create existing `part_of`: PASS.
- Task rename from the Graph edit UI: FAIL in the real app; after «Редактировать» -> change title -> «Сохранить», the visible Graph node remains on the old title.
- Add-relation search with a common query: FAIL layout; a long result set grows below the dialog viewport and produces a Flutter bottom overflow instead of a bounded scrollable result list.

This is a narrow corrective slice for those two confirmed bugs only. Do not start Task Layout v2 or semantic-window work in this task.

## 1. Fix real Graph rename after Save

Human reproduction:

1. Open Tasks Graph.
2. Select a visible Task.
3. Use «Редактировать».
4. Change only the title.
5. Press «Сохранить».
6. The save reports success, but the node shown on the Graph keeps the old title.

Required postcondition:

- After a successful save, the same visible Task node must show the accepted new title immediately.
- The old title must not remain in the Graph presentation and must not reappear on the next ordinary Graph rebuild/navigation caused by this edit flow.
- Cover the real `TaskManagementActions._editTask` path used from the Graph panel, not only a direct controller unit call.
- Also preserve the already-covered «Подробнее» edit path.
- Keep the same Task id.
- Title-only edit must not be treated as a topology mutation:
  - no Task-layout regeneration;
  - no canonical-center change;
  - no root/window change;
  - no selection loss;
  - no camera/zoom change except existing viewport compensation semantics.

### Diagnose the actual contract

The current client calls `PATCH /tasks/{id}`, receives `TaskMutationResponse.object`, then passes it to `onTaskUpdated`. Human testing proves that this path is not sufficient in the real build.

Before fixing:

- instrument/reproduce with a mock that reflects the actual API contract/path, and inspect whether the successful PATCH response contains the requested new title or a stale object;
- inspect any immediate authoritative read path already available to the client;
- distinguish:
  1. stale client/view-model state;
  2. stale mutation response;
  3. authoritative backend read that itself remains stale.

Fix the minimum correct layer.

Allowed client-side approaches include:
- reconciling the successful confirmed mutation into the local Task representation when the mutation response is stale;
- or one immediate existing authoritative re-read after the successful mutation if that endpoint returns the accepted state.

Do **not** use polling, arbitrary delays, timers, app restart, tab hopping, or background-sync waiting as the fix.

Do not fabricate success if the server rejected the rename. If the production API cannot expose/confirm the accepted title at all after a 2xx mutation and the correct fix necessarily requires a backend contract change, **STOP and report that blocker instead of silently broadening this task into backend work**.

### Required rename tests

Add a regression that reproduces the failure mode the human build exposed, not merely the previous happy-path synthetic response.

At minimum prove:

- real Graph «Редактировать» -> «Сохранить» changes the visible node immediately;
- a stale-success mutation response, if that is the observed cause, cannot leave/revert the old visible title;
- subsequent ordinary Graph rebuild/navigation in the same accepted edit flow does not restore the stale title;
- rooted and unrooted Task views preserve the new title where applicable;
- id/root/selection/window/canonical center/camera scale remain stable for title-only mutation;
- no Task topology/layout invalidation occurs solely because of rename.

## 2. Make Add-relation search results bounded and scrollable

Human reproduction:

- open «Добавить связь»;
- search a common term such as `Обучение`;
- enough results are returned to exceed available dialog height;
- the current `Column` expands the `...options.map(ListTile)` list below the screen and Flutter shows a bottom overflow.

Required behavior:

- The dialog header/type chooser, optional `part_of` explanation, search field, and action buttons must remain visible and usable.
- Search results must occupy a **bounded-height scrollable region** inside the dialog.
- No vertical Flutter overflow on ordinary desktop sizes and on a constrained/smaller test viewport.
- A long result set must be scrollable to the last item.
- Selection remains exact by underlying object id.
- GFX-A duplicate-title labels remain unchanged:
  - duplicate Task title gets confirmed-parent context;
  - unique title remains undecorated;
  - missing confirmed parent remains `(без родителя)`.
- Changing relation type and crossing into/out of `part_of` must keep the current reset semantics.
- «Создать» remains disabled until a valid target is selected.
- Do not redesign the dialog or search system.

Prefer a normal Flutter bounded-scroll composition (`ConstrainedBox` / `Flexible` / `ListView` or equivalent) rather than clipping content.

### Required picker tests

At minimum:

- 20+ search results in a constrained viewport produce no overflow exception;
- results area is scrollable;
- the last result can be brought into view, selected, and used;
- dialog actions remain visible;
- short result lists still render normally;
- GFX-A duplicate disambiguation tests remain green;
- existing `part_of` dialog tests remain green.

## Preserve

- GFX-B Task connection handles and drag-created `part_of`.
- Existing relation types and semantics.
- Canonical `part_of` direction child/source -> parent/target.
- PL1 single shared Task/People world and canonical persisted Task centers.
- Existing People shelf/cue behavior.
- No new relation type.
- No topology algorithm change in this slice.

## Verification

Run focused Flutter tests for:
- Task management/edit flow;
- Graph rename regressions;
- relation target disambiguation;
- long relation-picker scrolling;
- existing `graph_part_of_dialog_test.dart`;
- GFX-B drag suite;
- Graph smoke/large-canvas;
- task-layout world;
- shared Tasks/People camera regressions if shared Graph screen code is touched.

Run `flutter analyze` for changed Dart files and `git diff --check`.

## Human-check build is part of this task

If the fixes and required checks pass, produce a fresh self-contained **Linux debug bundle from the exact final implementation commit** for the user's manual re-test.

Requirements:

- build from a clean detached checkout of the exact implementation SHA;
- do not build from an uncommitted/mutable working tree;
- record exact source SHA, UTC timestamp, executable path, launcher SHA-256, kernel SHA-256 if present, and adjacent `BUILD_INFO.txt`;
- include a short manual checklist:
  1. rename a visible Task and confirm the node changes immediately;
  2. leave/return to Graph and confirm the old title does not reappear;
  3. search a common term in «Добавить связь», scroll the result list to the bottom, select an item, and confirm no overflow;
  4. spot-check duplicate-title suffixes and drag `part_of`.

Do not install the bundle over the user's client automatically.

## Explicitly out of scope

- Task Layout v2 / recursive local subtrees.
- Semantic-window/page partition redesign.
- Continuation anchors between areas.
- New relation types.
- Backend/API/schema/Alembic changes unless separately authorized after a reported blocker.
- Production deploy/ref move.
- Old GUX1 work.
- Any other Graph polish.

## Completion contract

When complete:

1. record root cause, implementation SHA, changed files, exact checks, bundle path/provenance/hashes, and limitations in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus a concise GFX-C summary and human-check bundle path;
3. commit/push ledger changes to `main`;
4. STOP.

Do not begin Task Layout v2 or semantic-window work without a new Architect authorization.
