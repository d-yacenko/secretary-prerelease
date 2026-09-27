# Current task — Task Stabilization S2: manual create finite/ongoing parity

Task Stabilization S1 is accepted.

The remaining concrete human-facing Task gap is manual creation.

Existing behavior:
- canonical Task domain supports `completion_mode=finite|ongoing`;
- Task editor already shows `Задача` / `Направление` and patches `completion_mode`;
- model-facing create/update parity is already closed by H2A;
- manual capture `POST /capture/task` has no completion-mode field;
- Capture UI therefore always creates an effective finite Task.

S2 closes only that human manual-create gap.

No inference.
No new kind.
No relation redesign.
No production deploy.

## Canonical UX

On the existing manual Task creation screen, expose the same two-way selector used by Task edit:

- `Задача` => `finite`
- `Направление` => `ongoing`

Default selection: `Задача` / finite.

The selector is an explicit human choice. Do not infer mode from:
- task text;
- title;
- due date;
- dependencies;
- attached context;
- duration;
- recurrence-like wording.

Keep the screen title and submit action unchanged:
- `Создание задачи`
- `Создать задачу`

Do not create a separate “create direction” flow.

## Backend capture API

Extend the existing authenticated manual capture request with:

`completion_mode`

Contract:
- omitted => finite;
- explicit `finite` => finite;
- explicit `ongoing` => ongoing;
- null => reject;
- any other value => reject.

Use canonical completion-mode constants/types where practical.

Do not make the field mandatory for old clients.

Pass the selected mode through:
`capture.py -> CaptureService.capture_task -> ObjectCreate`

Do not implement another completion-mode validator in CaptureService if the request/domain layers already provide it.

Created Task remains:
- `kind=task`;
- `origin=user`;
- `state=confirmed`;
- `status=open`.

Existing pinned-context `references`, `depends_on`, title derivation, exact body preservation, embedding enqueue, and cross-user validation are unchanged.

## Client model/draft

Extend client `CaptureTaskRequest` with canonical completion mode.

Extend `CaptureDraft` with mode state:
- default `finite`;
- `copyWith` preserves it unless explicitly changed;
- `toRequest()` carries it;
- `CaptureDraft.empty` resets to finite.

Add one controller mutation method for the screen to change mode.

Changing mode should:
- update draft;
- reset a prior non-submitting error state the same way text/title edits do;
- not disturb text/title/context/dependencies.

`mergeDraft`, context attachment, failed submit, and voice transcript edits must preserve the selected mode.

After successful submit/session reset, mode returns to finite because the draft resets.

## Capture UI

Add a `SegmentedButton<String>` or equivalent using the same wording as Task edit:
- `Задача`
- `Направление`

Use a stable key, for example:
`capture_task_completion_mode`

Place it near the top of the task form before or immediately around the main text/title fields; do not redesign the screen.

Disable it while capture inputs are disabled/submitting.

The screen must continue to work on the existing Android/Linux responsive layout.

No salience, graph, or renderer change.

## Existing edit path regression

Do not redesign `TaskManagementActions`.

Add/fix focused tests so the already-existing editor behavior is actually covered with realistic API JSON that includes `completion_mode`.

Prove:
- finite Task can be changed to ongoing and PATCH sends `completion_mode: ongoing`;
- ongoing Task can be changed to finite and PATCH sends `completion_mode: finite`;
- unchanged mode is omitted;
- ongoing Task status menu still omits `done`;
- finite status menu behavior is unchanged.

If production editor code is already correct, test-only changes there are preferred.

Update the test JSON helper to include `completion_mode` so parsing matches real `ObjectOut`.

## Backend tests

Add focused coverage proving at minimum:

1. capture request omitted mode creates effective/stored finite Task;
2. explicit finite creates finite;
3. explicit ongoing creates ongoing with status open;
4. null is rejected;
5. invalid string is rejected;
6. exact body whitespace remains preserved for ongoing;
7. optional title behavior remains unchanged;
8. context references are created for ongoing exactly as finite;
9. depends_on edges are created for ongoing exactly as finite;
10. cross-user context/dependency rejection remains fail-closed;
11. embedding enqueue behavior is unchanged;
12. capture does not infer ongoing from text that sounds recurring/continuous.

No `part_of` behavior is added to Capture in S2.

## Client tests

Update/add focused tests proving at minimum:

1. Capture draft defaults finite;
2. request JSON carries finite by default or in the agreed backward-compatible representation;
3. selecting `Направление` sends `completion_mode: ongoing`;
4. selecting back to `Задача` sends finite;
5. selector is disabled during submit;
6. failed submit preserves selected ongoing mode;
7. context/dependency attachment preserves selected mode;
8. successful submit resets next draft to finite;
9. session reset returns mode to finite;
10. voice text edits do not change selected mode;
11. existing exact-text/context URL capture tests remain green;
12. Task edit finite↔ongoing PATCH tests are green with realistic `completion_mode` response JSON.

## Validation

Run at minimum:

Backend:
- new focused S2 capture tests;
- `backend/tests/test_auth_capture.py`;
- `backend/tests/test_task_completion_mode.py`;
- `backend/tests/test_direct_tasks_api.py`;
- relevant graph/task relation tests if capture fixtures touch them;
- Ruff check/format touched Python.

Client:
- `client/test/capture/capture_test.dart`;
- `client/test/tasks/task_management_actions_test.dart`;
- relevant API model/client tests;
- Flutter analyze for touched files;
- Linux debug build;
- `git diff --check`.

No historical client failure is authorized as newly acceptable. Investigate any new failure.

## Documentation/state

No architecture rewrite is required.

Record in `PROJECT_STATE.md`:
- implementation SHA;
- exact backend capture completion-mode contract;
- exact UI wording/default;
- draft/reset/preservation behavior;
- edit regression result;
- backend/client test counts;
- analyze/build result;
- schema migration status;
- production untouched.

## Scope guard

Do NOT:

- infer ongoing automatically;
- create a new Object kind;
- change H2A Assistant/MCP tool semantics;
- add planned_start/planned_end tool fields (H2D);
- change `part_of`;
- change Task card renderer/layout;
- change People;
- change status lifecycle;
- add a migration;
- access/deploy production.

## Completion

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start S3.
Do not start H2D.
Do not deploy production.
