# Current task — ACTIVE

## UX-CAP1 — eliminate stale capture-context leakage between manual task-creation sessions

Architect authorization base before this ledger commit:

- `main = aeb7e7b60533cd0976ae659f78ad7412785ec081`
- `production = aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`

This is a **client-side state-boundary bugfix** discovered during the Architect's manual AH2 behavior acceptance. It is not an ML/prompt/tool-contract slice.

### Observed bug

A user can:

1. open an object in Graph/Object Detail;
2. choose the current manual-task action labelled `Использовать как контекст` / `Использовать как контекст задачи`;
3. enter the task-capture screen;
4. leave/abandon that capture without submitting;
5. later open the ordinary global `+ Задача` capture flow and create an unrelated Task.

Because the shared `CaptureController` keeps its previous `CaptureDraft`, stale `contextObjectIds/contextRefs` can survive across those capture sessions.

The later unrelated task request then silently includes the old context id. The backend correctly interprets **explicit** capture context by creating a confirmed user-origin `references` edge from the new Task to that context object. In the observed production UI, a manually created `TestTask` unexpectedly received:

- `TestTask --references--> Экспериментальная рубрика октября`
- provenance: `Пользователь · Подтверждено`

The backend capture semantics are not the defect. The defect is that a new manual capture can inherit old hidden client draft state.

Relevant current source includes:

- `client/lib/capture/capture_controller.dart`
- `client/lib/capture/capture_draft.dart`
- `client/lib/capture/capture_screen.dart`
- `client/lib/navigation/secretary_navigation.dart`
- `client/lib/shell/app_shell.dart`
- Graph/Object Detail capture entry points
- backend `CaptureService.capture_task()`, which must keep explicit-context => confirmed `references` behavior unchanged.

## Goal

Make manual Task capture have explicit, isolated **capture-session boundaries** so an unrelated new task can never inherit context/dependencies/draft data from an abandoned previous capture.

A semantic relation may be created only from context that belongs to the **current visible capture session**.

## Required behavior

### A. Fresh ordinary capture

Opening the ordinary global/new-task capture entry point must start a fresh capture session.

At minimum, the new session must not inherit from any previous abandoned capture:

- `text`;
- `title`;
- `contextObjectIds`;
- `contextRefs`;
- `dependsOnIds`;
- due/planned temporal fields;
- completion mode overrides;
- transient validation/submission state.

Default completion mode remains the existing ordinary Task default.

Do not preserve an abandoned draft invisibly across a later independent capture.

### B. Contextual capture

Opening Task capture explicitly from an object-context action must start a fresh capture session whose initial semantic context is **exactly the object the user just chose**.

It must not union that object with stale context from a previous capture.

If the product already supports attaching additional context/files **inside the same active capture session**, that explicit same-session behavior may remain. Do not remove legitimate same-session context attachment.

### C. Abandon/cancel/back semantics

Leaving a capture route without submission must not allow that route's draft/context to leak into the next independently opened capture.

It is acceptable for an abandoned unsaved draft to be discarded. Silent cross-session persistence is not acceptable.

### D. Successful submission

Keep the existing successful-submit behavior:

- task creation still resets capture state;
- explicit context in the current session is still sent in `CaptureTaskRequest`;
- backend still creates the canonical user-origin confirmed `references` edge for that explicit context;
- explicit `depends_on`, due date, planned interval, and completion mode behavior must not regress.

### E. Visibility / consent

Do not solve this by merely hiding stale context.

A contextual capture must continue to make its attached context visible in the capture UI before submit.

No confirmed semantic edge may result from context that was not part of the current capture session.

## Preferred implementation shape

Use an explicit capture-session API rather than ad-hoc clearing at random callers.

For example, the controller may expose concepts equivalent to:

- begin fresh task capture;
- begin task capture with one selected context object.

Exact names are implementation choice.

The important invariant is atomic session initialization: contextual entry should not depend on "maybe reset, then maybe attach" state left over from another route.

Audit all current `openCapture`/capture entry points so global creation and context-based creation choose the correct session initialization intentionally.

## Scope

Allowed:

- `client/lib/capture/**`
- `client/lib/navigation/secretary_navigation.dart`
- directly required client callers in Shell / Graph / Object Detail / Today / Search / Inbox if they open capture
- focused client tests
- compact ledger updates in `PROJECT_STATE.md` and `CURRENT_TASK.md`

Do **not** change unless a deterministic regression proves it is strictly required:

- backend `CaptureService` semantics;
- Graph relation ontology;
- Assistant prompt/tool contracts;
- AH2 eval harness;
- ActionPlan behavior;
- Task layout/geography;
- DB schema or migrations.

Do not touch production data.

## Explicit non-goals

Do not:

- redesign the whole create-task screen;
- add a general multi-context editor;
- change `references` semantics;
- infer context from currently selected Graph nodes;
- make the Assistant participate in manual task creation;
- work on T3, Person aliases, finalization language/time, approval-card UX, Scheduled Activity visibility, or other manual-acceptance findings in this slice;
- start AH2-M paid/model execution;
- start AH2-C;
- deploy backend/client or install/replace the user's client.

## Regression tests — required

Add deterministic coverage for the actual bug, not only helper-unit tests.

At minimum prove:

1. **context -> abandon -> fresh global capture**
   - start a contextual capture with object A;
   - abandon/close it without submit;
   - start ordinary new-task capture;
   - its draft/request has no A context id/ref and no stale dependency.

2. **context A -> context B**
   - after an abandoned contextual session for A, starting a new contextual session for B contains B only, not A+B.

3. **fresh capture request**
   - fill title/body in an ordinary fresh session and submit/inspect request;
   - `context_object_ids` is empty unless context was explicitly attached in this current session.

4. **explicit context still works**
   - a current contextual session visibly shows the selected context;
   - its request includes exactly that context id.

5. **same-session behavior preserved**
   - relevant current due/planned/completion-mode fields are not accidentally reset while the user remains in one active capture session.

Prefer one widget/navigation regression that reproduces the real shared-controller path in addition to controller-level tests.

Keep existing backend explicit-context behavior covered; do not change the backend to make the failing client request harmless.

## Required checks

Run the focused tests for every changed client area, including at least the relevant existing suites under:

- `client/test/capture/capture_test.dart`
- `client/test/objects/object_detail_test.dart`
- `client/test/graph/graph_workspace_screen_test.dart`
- `client/test/shell/app_shell_test.dart`

Run any additional tests for other touched entry points.

Also run:

- focused `flutter analyze` on changed client files;
- existing backend capture tests sufficient to prove explicit context semantics remain unchanged, including `backend/tests/test_auth_capture.py` and `backend/tests/test_capture_s2_completion_mode.py`;
- `git diff --check`.

Record exact pass counts/results.

## Acceptance criteria

The slice is complete only when all are true:

- the observed stale-context reproduction is covered by an automated regression;
- ordinary new-task capture starts clean after an abandoned contextual capture;
- contextual capture begins with only the newly selected object;
- explicit current-session context still creates the same request payload semantics;
- no backend semantic workaround was introduced;
- no schema/Alembic change;
- no model call;
- no production mutation/deploy;
- focused tests/analyze are green.

## Completion protocol

After implementation:

1. append a compact factual UX-CAP1 result to `PROJECT_STATE.md`;
2. replace this file with **HOLD** containing:
   - implementation SHA;
   - exact changed files;
   - exact regression behavior;
   - test/analyze results;
   - confirmation that backend capture semantics/schema/production were unchanged;
3. commit and push to `main`;
4. STOP.

Do not start the next remediation item from HOLD.
