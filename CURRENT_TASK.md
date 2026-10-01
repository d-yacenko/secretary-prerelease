# Current task — AH2-T planned Task execution interval write parity

AH2-P and AH2-D are SOURCE-ACCEPTED. Neither has been deployed yet.

AH2-T closes the remaining AH1 Task contract gap: the human product can set a planned execution interval on a Task, while the model tools can currently only read it.

This is a backend capability slice with no database migration expected.

## Canonical semantics

The existing domain already defines:

- `due_at` = deadline;
- `planned_start_at` + `planned_end_at` = explicit intended Task execution interval;
- planned interval is not a reminder;
- planned interval is not calendar busy time;
- planned interval is Task-only;
- both boundaries exist together or neither exists;
- `planned_end_at > planned_start_at`.

Reuse the existing `app.domain.planned_execution.validate_planned_execution_interval`.

Do not create a second time model.

## Current write asymmetry

Human Task editing already persists the interval through the existing Object fields.

Backend storage and `ObjectOut` already contain:
- `planned_start_at`;
- `planned_end_at`.

`get_task_profile` already returns them.

But:
- `CreateTaskInput` has no planned interval fields;
- `UpdateTaskInput` has no planned interval fields;
- `TaskMutationService.patch_task_fields` does not support them;
- Assistant create/update schemas do not advertise them.

That is the AH1 `MODEL_GAP`.

## Goal

Allow `create_task` and `update_task` to write the same canonical planned interval without changing lifecycle, reminders, calendar semantics, or Task layout.

Both Assistant and MCP projections must use the same field names and domain behavior.

## A. Tool input schemas

Add optional fields to `CreateTaskInput` and `UpdateTaskInput`:

- `planned_start_at: datetime | None`
- `planned_end_at: datetime | None`

### Pair semantics

Field **presence** matters.

For create:
- both omitted → no planned interval;
- both supplied with non-null datetimes → set interval;
- both explicitly null may be treated as no interval;
- exactly one field supplied → validation error;
- one null and one non-null → validation error;
- end <= start → validation error.

For update:
- both omitted → leave existing interval unchanged;
- both supplied with non-null datetimes → replace the whole interval;
- both explicitly null → clear the whole interval;
- exactly one field supplied → validation error;
- one null and one non-null → validation error;
- end <= start → validation error.

Do not allow independent one-sided interval mutation.

Use Pydantic model validation so malformed pair intent fails before domain mutation.

Normalize non-null datetimes through the existing tool datetime normalization path before persistence.

## B. Canonical Task mutation service

Extend `TaskMutationService.patch_task_fields` to support the interval.

Required behavior:

- add `planned_start_at` and `planned_end_at` to the canonical field patch path;
- validate using the existing planned-execution domain validator;
- both fields are treated as one semantic unit;
- if either boundary changes, pass the complete resulting pair to `ObjectUpdate`, not only the changed boundary;
- both null clears the interval;
- setting the same pair again is a no-op with `changed=false`;
- clearing an already-empty interval is a no-op;
- title/body embedding behavior remains unchanged;
- no Task topology/layout invalidation is introduced by interval-only mutation.

Keep direct REST Task mutation and tool mutation on this same service.

## C. Direct Task PATCH contract

Extend `TaskPatchRequest` with:

- `planned_start_at`
- `planned_end_at`

using the same pair/presence semantics as `UpdateTaskInput`.

Update `PATCH /tasks/{task_id}` to forward them into `TaskMutationService.patch_task_fields`.

This makes the Task-specific backend contract complete; do not require the client to switch from its current generic object patch inside AH2-T.

No client/UI changes in this slice.

## D. create_task domain path

In `DomainToolService.create_task`:

- accept the validated planned pair;
- normalize it;
- pass it into the existing Task `ObjectCreate`;
- preserve current provenance/state/confidence/approval semantics;
- invalid interval input must fail before any Task object or relation artifact is created.

Do not change default Task lifecycle/status.

## E. update_task domain path

In `DomainToolService.update_task`:

- include both planned fields in field-update detection;
- forward the pair through `TaskMutationService.patch_task_fields`;
- preserve relation/evidence additive semantics;
- a pure planned-interval update must count as a legitimate update;
- changed/no-op reporting must remain truthful.

Do not couple planned interval to `due_at`, `status`, `completion_mode`, actor roles, or evidence.

## F. Assistant tool contract descriptions

Update manual Assistant schemas for both `create_task` and `update_task`.

### create_task

Advertise both optional datetime strings and explain:

- they form one planned execution interval;
- both must be supplied together;
- end must be after start;
- this is intended work time, not `due_at`, a reminder, or calendar busy time.

Do not advertise one-sided mutation.

### update_task

Advertise both fields as optional string-or-null and explain:

- both must be supplied together;
- non-null pair replaces the interval;
- both null clear it;
- omission leaves it unchanged;
- this is distinct from `due_at`.

Update the `get_task_profile` wording from “readable only / does not write the planned interval” to accurately say the profile reads it while create/update can write it.

Keep descriptions concise.

## G. MCP parity

`create_task` and `update_task` are the same canonical capabilities under MCP policy.

Verify:
- both planned field names appear in MCP schemas;
- types/nullability reflect create vs update semantics;
- arguments forward unchanged through MCP gateway;
- MCP still requires approval for writes;
- malformed interval input fails before approval/mutation where current gateway validation expects that behavior;
- no Person exposure flags or unrelated registry flags change.

Do not add new tools.

## H. Prompt boundary

Do NOT expand `SYSTEM_INSTRUCTIONS` in AH2-T unless a deterministic existing prompt statement becomes factually false.

AH2-P already establishes Task/reminder distinctions. Field-level routing belongs in tool descriptions for this slice.

Behavior remains `BEHAVIOR_UNVERIFIED` until AH2-M.

## Required tests

Add/update focused deterministic tests.

### Input validation

Cover CreateTaskInput and UpdateTaskInput:

1. omitted pair accepted;
2. valid non-null pair accepted;
3. exactly one boundary rejected;
4. null + non-null rejected;
5. end == start rejected;
6. end < start rejected;
7. update both-null pair accepted as explicit clear.

### Domain create

Prove:
- valid pair persists on the created Task;
- datetimes are normalized consistently;
- invalid pair creates no Task and no relations/evidence.

### Canonical update service

Prove:
- set pair → changed=true and both columns updated;
- replace pair → changed=true;
- same pair → changed=false;
- clear pair with both null → changed=true;
- clear already-empty → changed=false;
- one-sided update rejected;
- due/title/body/completion behavior remains green.

### Tool update

Prove pure interval update works through `update_task` and returns truthful `changed`.

### REST parity

Prove `PATCH /tasks/{id}` can:
- set;
- replace;
- clear;
- reject malformed pair;
- preserve unrelated fields.

### Assistant/MCP schema parity

Prove both create/update expose the two exact field names, with no aliases.

MCP still requires approval and forwards the intended payload.

### Approval/provenance

Use existing bounded tool/action-plan tests where possible to prove:
- planned interval write remains an INTERNAL_WRITE requiring approval;
- approved create/update does not bypass provenance rules;
- no-op finalization remains truthful if the current harness covers it without the known broken local action-plan fixture.

Do not repair the known unrelated `ai_traces.user_id` local DB baseline problem inside AH2-T.

## Documentation reconciliation

AH2-T closes a documented current contract gap.

Update:

- `docs/ontology_harness_parity_audit.md`;
- `docs/SECRETARY_TOOLSET_MATRIX.md`

only where necessary to reflect that planned interval is now model-writable.

Required audit framing:
- the static `MODEL_GAP` is closed at contract/domain level;
- model behavior remains `BEHAVIOR_UNVERIFIED`;
- do not claim real-model success before AH2-M.

If `docs/SECRETARY_AGENT_EVAL_SCENARIOS.md` lacks a planned-interval scenario, add one concise scenario:
- explicit intended work interval → planned fields;
- deadline remains `due_at`;
- reminder/calendar are not substitutes.

## Schema / deploy boundary

No Alembic migration is expected:
- object columns already exist;
- production is already Alembic `0052 / 0052`.

Do not create a migration merely because tool/API schemas change.

Do NOT deploy production automatically.

After source review, Architect will decide whether to:
1. build AH2-E executable eval harness first, then
2. do one schema-neutral rollout containing AH2-P + AH2-D + AH2-T before AH2-M real-model evaluation.

No client build is required.

## Explicitly out of scope

- new Task time concepts;
- recurring schedules;
- reminder changes;
- calendar event changes;
- UI changes;
- Task layout changes;
- relation semantics;
- model confirmation of old proposals;
- Person identity test debt;
- action-plan local DB fixture repair;
- real LLM calls;
- production deploy;
- migrations.

## Completion contract

When complete:

1. record exact field semantics, validation, canonical mutation path, Assistant/MCP parity, tests, and docs reconciliation in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus:
   - implementation SHA;
   - planned interval behavior summary;
   - tests;
   - migration status;
   - production unchanged;
   - rollout/model verification pending;
3. commit/push to `main`;
4. STOP.

Do not begin AH2-E, AH2-M, or AH2-C.
