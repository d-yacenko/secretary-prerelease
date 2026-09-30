# Current task — GFX-B drag-to-create existing part_of relation

Authorized base: `ecd4658e3cad406dcac1ff154f8af02624fffd01`.
GFX-A is Architect-accepted at implementation `0fd1088f53ad9bc384c92ac2f38e0808b1097f86`.
Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`.
PL1 remains human-accepted and closed. GUX1 remains paused.

This is the second bounded Graph fix slice from current real usage.

The goal is a fast diagram-editor-style gesture for the **existing canonical `part_of` relation only**. Do not introduce a new relation type or reinterpret any existing relation.

## Product semantics

Canonical direction is unchanged:

- source/dragged Task = child;
- target/drop Task = parent;
- mutation payload = `type: "part_of"`;
- visual meaning = `child -> parent` / «входит в».

All existing domain invariants remain authoritative: at most one non-rejected parent slot, no self-link, no cycle, and completion-mode constraints. The backend/domain contract remains the source of truth for validation.

Other relation types — `related_to`, `references`, `depends_on` — continue to be created only through the existing «Добавить связь» UI in this slice.

## 1. Task connection handles

In **Tasks mode only**, visible Task nodes on the graph become connectable.

Requirements:

- Add small circular connection handles on Task-card edges.
- Use a compact diagram-editor visual: surface/white-like fill with a contrasting outline so the handle remains visible in both light and dark themes.
- Do not show `part_of` handles on:
  - People mode;
  - Person nodes;
  - Flow/note/evidence/non-Task nodes;
  - offscreen shelf/cues or other viewport UI.
- Avoid permanent visual clutter:
  - handles may be visible on hover/selected Task;
  - while a connection drag is active, expose the valid Task target handles/cues needed to complete the gesture.
- Provide connection points on the card perimeter so the gesture does not depend on one specific graph orientation. Four mid-edge handles (top/right/bottom/left) are preferred if this can be implemented as one reusable wrapper without duplicating Task-card implementations.
- Do not change canonical Task size, persisted center, or world geography merely to make room for handles. Handles may paint/hit-test slightly outside the card bounds.
- Existing Task tap/select and inspector behavior must remain unchanged when the user is not dragging a handle.

## 2. Drag interaction

Starting a pointer drag from a Task connection handle begins a pending `part_of` gesture.

During drag:

- draw one temporary **solid directed line** from the source handle toward the current pointer;
- draw an arrowhead at the destination end so the direction reads as source -> target;
- the temporary line is presentation only and must not enter controller/domain edge state;
- valid target Task under the pointer is visibly highlighted;
- do not select/re-root a target merely because the pointer crosses it;
- panning/zooming the InteractiveViewer outside connection handles must continue to work normally;
- a handle drag must win over canvas-pan gesture only for that active handle drag;
- preview geometry must remain correct under the current zoom and pan transform.

Targeting:

- only another visible Task is a valid drop target;
- source Task itself is never valid;
- non-Task nodes are never valid;
- the user should not need pixel-perfect placement on the tiny target circle: dropping on the target Task card or its exposed connection handle may count as the same valid target;
- if no valid target is under the pointer, the preview remains temporary and release cancels it.

## 3. Commit exactly the existing part_of mutation

On a valid drop:

1. send exactly one existing relation request using:
   - `source_id = dragged Task id`;
   - `target_id = dropped Task id`;
   - `type = "part_of"`;
2. do not optimistically mutate graph/domain state before the request succeeds;
3. on success, feed the returned edge through the same canonical relation-application/topology-refresh path used by the existing relation dialog (`applyCreatedRelation` or the current equivalent);
4. let the existing topology invalidation + canonical Task-layout machinery handle the structural change;
5. clear drag/preview state.

Do not create a parallel relation code path with different topology behavior.

While one drop request is in flight:

- do not submit the same gesture twice;
- ignore/reject another completion attempt cleanly.

On backend/domain rejection (second parent, cycle, self/invalid mode, etc.):

- leave canonical graph state unchanged;
- clear the temporary preview;
- show the backend/user-facing error through the existing non-blocking Graph error pattern (SnackBar is acceptable);
- do not retry automatically;
- do not silently convert the gesture to another relation type.

## 4. Preserve the standard relation UI

The existing «Добавить связь» action/dialog remains available and functionally unchanged.

It continues to be the path for:

- `related_to`;
- `references`;
- `depends_on`;
- also `part_of` when the user prefers the form/search flow.

GFX-A duplicate-title disambiguation in that dialog must remain intact.

## 5. Preserve accepted world behavior

Must remain unchanged except for the legitimate topology mutation after a successful `part_of` creation:

- persisted canonical Task centers;
- shared Tasks/People world origin and camera parity;
- semantic-window behavior;
- Person anchoring/centroids;
- same-anchor People clusters;
- unanchored shelf + edge cue;
- marker readability;
- manual Fit semantics.

A successful `part_of` is a real Task-topology change, so the existing canonical topology invalidation/rebuild behavior is expected. Do not invent a special no-repack exception for drag-created `part_of`.

## Tests

Add focused Flutter/widget tests proving at least:

1. Visibility:
   - Task nodes expose connection handles in Tasks mode under the intended hover/selected/active-drag conditions;
   - People/non-Task nodes do not expose `part_of` handles.

2. Gesture + payload:
   - drag from Task A handle to Task B at scale 1.0 sends exactly one request:
     `{"source_id":"A","target_id":"B","type":"part_of"}`;
   - the same works with a non-1.0 InteractiveViewer zoom/pan transform;
   - temporary preview is a directed solid line and disappears after release.

3. Cancellation:
   - release on empty canvas sends no request;
   - release on source Task sends no request;
   - release on a non-Task sends no request;
   - cancelled gesture leaves graph/controller edges unchanged.

4. Success/error:
   - successful response uses the existing relation/topology refresh path and yields the normal canonical `part_of` edge after refresh;
   - backend 422/validation error shows the message and leaves no local fake edge;
   - an in-flight completion cannot double-submit.

5. Regression:
   - existing `graph_part_of_dialog_test.dart` remains green;
   - GFX-A relation-target disambiguation and rename tests remain green;
   - Graph smoke + large-canvas;
   - task-layout world;
   - Tasks<->People camera parity / People landscape/shelf cue tests remain green if shared rendering code is touched.

Run focused Graph Flutter suites, `flutter analyze` for changed Dart files, and `git diff --check`.

## Explicitly out of scope

- No new relation type.
- No drag creation for `depends_on`, `references`, `related_to`, actor edges, Person links, or Flow/evidence.
- No relation editing/deletion by drag.
- No arbitrary Task repositioning by drag.
- No backend schema/Alembic changes.
- No production deploy/ref move/client install.
- No broad Graph redesign.
- No old GUX1 toolbar/search/Person-creation/banner work.
- No Secretary Agent/Harness audit.

## Completion contract

When complete:

1. record implementation SHA, changed files, exact checks, and any interaction limitation in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus a concise GFX-B completion summary;
3. commit and push to `main`;
4. STOP.

Do not begin any further Graph polish or other roadmap work without a new Architect authorization.
