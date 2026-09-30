# Current task — GFX-A Graph target disambiguation + immediate rename consistency

Authorized base: `2a2a033747956413487e733035a01d458cdcb7f2`.
Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`.
PL1 is human-accepted and closed. Preserve its canonical Task world, People overlay, shared camera, clusters, shelf, and shelf cue.

This task **supersedes/pauses the previously authorized GUX1 polish task**. Do not implement the old toolbar/search/Person-creation/banner scope in this cycle.

This is the first bounded fix slice from current real Graph usage. Do only the two items below, then return to HOLD and STOP.

## 1. Disambiguate duplicate Task titles in relation-target search

Observed problem:

When creating a relation from a Task, the existing target picker can return two Tasks with the same title (for example two different `Обучение` directions). Today both rows display the same title, so the user cannot tell which target is intended.

Required behavior:

- Keep the canonical/stored Task `title` unchanged.
- In the **Add relation** target search UI, detect result groups whose displayed Task titles are identical.
- For duplicated Task titles, add UI-only structural context from the Task's immediate **confirmed/current `part_of` parent** when available.
- Expected presentation example:
  - `Обучение (Основная работа)`
  - `Обучение (Академическая деятельность)`
- Do not add the parent suffix to a title that is unique within the current result set.
- The suffix is presentation only. It must not mutate the Task title, search query, relation payload, IDs, or ontology.
- The selected relation target must remain the exact underlying Task ID represented by that row.
- Never infer parent context from screen position, title strings, graph proximity, metadata heuristics, or another relation type.
- Rejected/proposed `part_of` state must not be presented as an established parent.
- If a duplicate result has no confirmed/current parent available, fail honestly in the UI (for example `(без родителя)`) rather than inventing context.
- Do not introduce any new relation type.

Implementation boundary:

- Prefer reusing existing Task/profile/`part_of` read data if the client can obtain it cleanly.
- If the current `/search` payload cannot supply enough grounded parent context, a **minimal read-only API/client contract extension is authorized** for this purpose.
- No schema or migration.
- Do not broaden this into a search redesign or hierarchy feature.
- Keep normal unique-title search behavior unchanged.

## 2. Fix Task rename propagation in the current Graph

Observed problem:

A Task rename can report success but the Graph may continue showing the old title until much later/restart/reload. A successful title edit must be reflected immediately in the current Graph.

Required behavior:

- Reproduce/trace the actual edit path reachable from Graph Task details/management; do not fix only a synthetic controller path.
- After the backend has successfully accepted a Task title change, the current Graph must show the new title immediately.
- The old title must disappear from the current rendered node/presentation without waiting for background sync, app restart, next-day refresh, or an unrelated navigation cycle.
- Cover both:
  - unrooted Tasks overview;
  - rooted Task Graph view, where applicable to the same edit flow.
- Preserve:
  - current Graph mode;
  - root;
  - selection when still valid;
  - semantic-window index;
  - current camera/zoom;
  - canonical persisted Task center.
- A title-only edit is **not** a topology change. Do not invalidate/repack canonical Task geography because of rename.
- Do not add polling or arbitrary delays as the fix.
- Do not change Task identity or create replacement objects.
- If the stale title is caused by more than one local cache/view-model representation, reconcile the minimum necessary representations after a successful mutation.

## Preserve accepted semantics

- `part_of` remains exactly child/source -> parent/target.
- Forest invariants remain enforced by the existing backend/domain contract.
- No new relation types.
- No fuzzy or heuristic hierarchy inference.
- No Graph geography/layout algorithm changes.
- No People/PL1 behavior changes.

## Tests

Add/update focused tests proving at least:

1. Relation target search:
   - two Task results named `Обучение` with different confirmed parents render as distinct labels using those parent titles;
   - selecting either row creates the relation against the correct exact Task ID;
   - a unique title is not decorated unnecessarily;
   - rejected/proposed `part_of` is not shown as established parent context;
   - duplicate result with no confirmed parent does not fabricate a parent.

2. Rename consistency:
   - rename from the real Graph edit/details path updates the visible Task node immediately in unrooted overview;
   - rooted view updates immediately as well where that path is applicable;
   - old title disappears;
   - camera scale/translation, root/window, and canonical position remain unchanged by title-only mutation;
   - no topology/layout invalidation is triggered solely by rename.

3. Regression:
   - existing relation creation including `part_of` remains green;
   - Graph smoke/large-canvas and task-layout world tests remain green;
   - PL1 People/world-camera tests remain green if touched/shared code could affect them.

Run the focused Flutter suites for changed Graph code, any focused backend tests if the read contract changes, `flutter analyze` for changed Dart files, backend lint/test checks appropriate to changed Python files, and `git diff --check`.

## Explicitly out of scope

- Drag-to-create relation handles/lines. That is the **next separate slice**, not authorized here.
- Any new relation type.
- Old GUX1 toolbar/search-width/fCoSE-label/Person-creation/banner polish.
- Backend schema or Alembic changes.
- Production deploy/ref move/client install.
- Graph layout/geography redesign.
- Combined Tasks+People mode.
- Secretary Agent/Harness audit.

## Completion contract

When complete:

1. record implementation SHA, changed files, exact checks, and any remaining limitation in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus a concise GFX-A completion summary;
3. commit and push to `main`;
4. STOP.

Do not start drag-to-create `part_of` or any later work without a new Architect authorization.
