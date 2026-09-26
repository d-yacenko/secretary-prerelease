# Current task — Graph Shell V8C2: selection-driven desktop detail pane

Visual Task Map V8C1 is accepted after human real-data review.

Client shell/presentation only. No backend/API/schema changes. No graph-layout or relation-semantic changes. No production deploy. Do not start relation-direction cleanup or backend hierarchy closure.

## Product behavior

The wide Graph workspace currently reserves a fixed 360 px right pane even when nothing is selected. Remove that dead reservation.

For wide layouts (the existing desktop breakpoint, currently `>= 900` px):

1. When `selectedObject == null`:
   - do not render/reserve the 360 px detail pane;
   - do not show the `Выберите объект для просмотра.` placeholder;
   - the graph canvas receives the full available workspace width.

2. When `selectedObject != null`:
   - show the existing right detail pane at the existing 360 px width;
   - keep all current detail contents, actions, relation audit rows, confirm/reject controls, Task Profile, Person detail content, delete/open/Ask Secretary behavior, and close button semantics;
   - the graph canvas uses the remaining width.

3. When selection is cleared:
   - the detail pane disappears;
   - the graph immediately regains the full available width.

4. Changing selection from one object to another while the pane is already open must reuse the same pane shell and simply show the new selected object.

Animation is optional. A simple deterministic conditional pane is sufficient. Do not add a dependency just for animation.

## Preserve graph state

Pane visibility is shell state derived from the existing selection. It must not become graph-layout state.

Opening/closing the pane must NOT:
- mutate `GraphWorkspaceController.positions`;
- persist positions;
- change root/re-root state;
- change filters;
- change Preserve/Relax mode;
- trigger a new graph-layout/refinement pass merely because the pane appeared/disappeared;
- request an automatic fit merely because the viewport width changed;
- change V8B2 Task geography.

The viewport may naturally become narrower/wider because the pane is present/absent; preserve the existing transform/view unless another existing user action explicitly requests fit.

## Narrow/mobile behavior

Keep the current narrow-layout behavior unchanged:
- canvas remains full-screen underneath;
- detail content appears only for a selected object in the existing bottom overlay;
- no new desktop pane logic should alter that path.

## Tasks and People

This is Graph workspace shell behavior, so the same wide-layout selection rule applies in both Tasks and People modes.

Do not change People graph semantics or rendering.

## Relation direction is OUT OF SCOPE

Human real-data review still shows semantically confusing arrows around some existing objects.

Do not reverse, normalize, migrate, reinterpret, or otherwise modify relation directions in V8C2.

The current renderer must continue to show canonical stored relation semantics. Direction/data cleanup will be a separate audited phase after we distinguish bad legacy data from presentation defects.

## Implementation guidance

Prefer the smallest change around the existing wide `Row` in `GraphWorkspaceScreen.build`.

It is acceptable to add stable `ValueKey`/semantics hooks for:
- the graph canvas region;
- the desktop detail pane;

if that makes viewport-width tests deterministic.

Do not redesign `_buildDetailPanel`. Removing or leaving its null-placeholder branch is implementation-local; the product requirement is that the null placeholder is not rendered/reserved on wide layout.

## Tests

Prove at minimum:

1. wide Tasks mode + no selection: desktop detail pane is absent;
2. wide Tasks mode + no selection: `Выберите объект для просмотра.` is absent;
3. wide Tasks mode + no selection: canvas occupies the width previously consumed by the 360 px pane;
4. selecting an object on wide layout opens the existing 360 px right pane;
5. pane content corresponds to the selected object;
6. closing/clearing selection removes the pane and restores canvas width;
7. switching selected object while open keeps one pane and updates content;
8. pane open/close does not change controller positions/root/filters/Preserve-Relax state;
9. pane open/close does not create a fit request solely from visibility change;
10. narrow/mobile selected-object bottom overlay behavior is unchanged;
11. narrow/mobile no-selection behavior is unchanged;
12. People mode gets the same wide shell behavior and otherwise remains unchanged;
13. V8B2 hierarchy/packing tests remain unchanged;
14. V8C1 proposed-relation presentation tests remain unchanged;
15. existing relation direction tests remain unchanged.

Run:
- `client/test/graph/graph_workspace_screen_test.dart`;
- People workspace screen tests;
- V8B2 hierarchy/packing tests;
- V8C1 relation/proposal tests;
- relevant Graph workspace/controller tests;
- Flutter analyze on touched files;
- `flutter build linux --debug`;
- `git diff --check`.

The three already-known detail-screen failures may remain if and only if they are the exact same pre-existing failures. Do not expand scope to repair them in V8C2; report them precisely.

## Completion

Record the implementation SHA and exact desktop/narrow behavior in `PROJECT_STATE.md`.

Return `CURRENT_TASK.md` to HOLD.

Do not start the relation-direction audit.
Do not start backend hierarchy closure.
Do not deploy production.

Push to `origin/main` and STOP.
