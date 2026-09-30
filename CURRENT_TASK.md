# Current task — GFX-B.1 re-enable part_of drag after async completion

Authorized base: `ca82c2bf7f352f2fa953b3189ca644ac83e0bd29`.
GFX-B implementation under review: `cf812130c59c45eee25a3a96720c0f0fe99b3c29`.
Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`.

This is a **narrow corrective slice only**. Do not add features or broaden GFX-B.

## Defect

GFX-B correctly prevents duplicate completion with `_partOfSubmitting`, but the async completion path currently resets that field in `finally` without scheduling a rebuild.

With a real non-immediate network request, the Graph can render Task connection handles with `enabled: false` while the request is in flight. If the request then fails (for example backend `422` for a second parent/cycle/completion-mode rule), the field becomes `false` internally but the Task handle widgets may remain rendered disabled until some unrelated later rebuild.

The current immediate mock rejection does not prove recovery from this timing.

## Required fix

- After any completed drag relation request — success, backend validation failure, or other handled API completion — the Graph interaction state must visibly return to idle when the widget is still mounted.
- Task connection handles must be usable again immediately after a rejected request; no selection change, pan, tab switch, or unrelated rebuild may be required.
- Preserve the existing single-submit guarantee while a request is actually in flight.
- Preserve the current GFX-B semantics:
  - only existing `part_of`;
  - dragged Task = child/source;
  - dropped Task = parent/target;
  - no optimistic edge;
  - success uses `applyCreatedRelation` / existing topology refresh;
  - validation error shows the backend message and leaves no fake edge.
- Keep the fix local to GFX-B interaction state. No backend/schema/layout/ontology changes.

Implementation may use a mounted `setState` (or an equivalently explicit state transition) when clearing the submitting flag. Avoid setState-after-dispose.

## Required regression test

Add/adjust a widget test that reproduces the real async ordering:

1. start a valid Task A -> Task B drag;
2. hold the POST response behind a `Completer` long enough to pump/render the in-flight disabled state;
3. complete that request with a backend validation error (for example 422);
4. verify the error is shown and no local `part_of` edge exists;
5. without causing an unrelated controller/navigation rebuild, immediately perform another handle drag;
6. verify a second POST is actually sent (and may succeed in the test);
7. preserve the existing test that a second completion **during** the first in-flight request does not submit.

Run:
- `client/test/graph/graph_part_of_drag_test.dart`;
- existing `graph_part_of_dialog_test.dart`;
- GFX-A relation target/rename regressions if shared screen code changes;
- Graph smoke/large-canvas and task-layout world regressions appropriate to the touched screen;
- `flutter analyze` for changed Dart files;
- `git diff --check`.

## Explicitly out of scope

- No visual redesign of handles or arrow.
- No new relation type or relation behavior.
- No backend/API/schema/Alembic changes.
- No production deploy/client install.
- No old GUX1 work.
- No further Graph polish.

## Completion contract

When complete:

1. record implementation SHA, changed files, exact checks, and result in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus a concise GFX-B.1 summary;
3. commit/push to `main`;
4. STOP.

Do not start any later Graph work without new Architect authorization.
