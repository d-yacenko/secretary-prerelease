# Current task — Flutter Inbox safe delete + compact pinned action row

## Authorization

Implement GitHub issue #9 as one narrow Flutter-only UX fix.

No backend/API/DB/schema work.
No production deploy.
No live provider or LLM calls.

Current server production baseline:
- runtime/ref: `42db393be50a4c3f20ce86dadc280d77bada3959`
- Alembic: `0046 / 0046`

Task parent must be exactly:
`3f69219a876529e4be4e1f702ce0232b3f30356d`

## 1. Desktop inline delete must always confirm

Current bug:
- desktop Inbox delete reuses `objectSupportsDeliberateSwipeDeleteWithoutDialog()`;
- provider-backed objects therefore bypass confirmation;
- this shortcut was intended for deliberate mobile full-swipe, not for an adjacent desktop action button.

Required:
- desktop inline `Удалить` always goes through existing `confirmAndDeleteObject()`;
- no DELETE request before explicit confirmation;
- `Отмена` leaves the card and local Inbox state unchanged;
- `Удалить` performs the existing Secretary-only delete and removes the card after API success;
- provider-backed source remains untouched, using the existing provider-specific explanatory text;
- deliberate mobile full-swipe behavior stays unchanged.

Do not add undo/recovery in this task.

If easy without scope spread, avoid duplicate wording in the dialog:
- title: `Удалить из Секретаря?`
- body: only the provider/source-survival explanation where applicable
- actions: `Отмена`, `Удалить`

Do not block the task solely on that wording cleanup if it would require broad shared-message changes.

## 2. Restore labels as the far-right anchor on wide Inbox cards

Current bug:
- Inbox passes `wrapActions: true` to `ObjectMetaActionRow`;
- the wide branch then uses one shared Wrap for actions + labels;
- after adding the third action, label chips moved left next to actions.

Required wide behavior:
- action cluster is on the left;
- label strip remains independently pinned/aligned to the far right of the card row;
- actions may wrap internally when width is constrained;
- labels must NOT join the action Wrap;
- maintain compact vertical behavior and no overflow at realistic/narrow desktop widths.

Mobile/non-wide layout can remain wrap-based.

Shared component requirement:
- Today/Search default wide layout must not regress;
- if changing `ObjectMetaActionRow`, preserve its existing default behavior and make the Inbox-specific wrapped-actions mode still use a separate right label anchor on wide layout.

## 3. Compact action labels

Change the shared visible labels:
- `Спросить секретаря` -> `Секретарь`
- `Открыть в графе` -> `Граф`
- `Удалить` unchanged

Keep the existing icons and tooltips/accessibility semantics coherent.

Because these actions are shared widgets, use the same compact labels consistently wherever those widgets render; do not create Inbox-only duplicate action widgets solely for wording.

## Focused tests

Add/extend Flutter tests proving at minimum:

1. desktop inline delete click opens a confirmation dialog;
2. no delete API call occurs before confirmation;
3. Cancel keeps the object/card and does not call delete;
4. Confirm triggers exactly one delete and removes the card after success;
5. deliberate mobile full-swipe retains the current direct-delete/no-dialog behavior for supported provider-backed objects;
6. wide Inbox with three actions + labels keeps labels right-aligned to the card edge;
7. one/two labels and label overflow behavior remain correct;
8. narrow desktop width has no RenderFlex/layout overflow;
9. visible action labels are exactly `Секретарь`, `Граф`, `Удалить` on wide layout;
10. Today/Search shared action-row tests remain green or receive equivalent regression coverage.

Run:
- focused Inbox delete/action-row tests;
- relevant object delete tests;
- relevant Today/Search shared-row tests;
- Flutter analyze for touched Dart files;
- `git diff --check`.

## Boundaries

Do not:
- touch backend/API/DB;
- change delete semantics on the server;
- add restore/undo;
- change mobile swipe policy;
- alter Conversation Stack bookmark behavior;
- implement group labels from backlog;
- deploy production or distribute/install Flutter binaries.

## Completion

Record in `PROJECT_STATE.md`:
- exact implementation SHA;
- files changed;
- focused test/analyze results;
- confirmation backend/API/DB unchanged;
- confirmation server production remains `42db393be50a4c3f20ce86dadc280d77bada3959`;
- confirmation no client installation/distribution was performed.

Return `CURRENT_TASK.md` to HOLD, push, and STOP.
