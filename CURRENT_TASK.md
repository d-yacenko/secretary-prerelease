# Current task — Harness H2A: Task completion_mode write parity

People C3 is accepted.

Resume the blocking Task semantic parity gap recorded by Ontology/Harness H1.

Human UI, canonical Task domain, ObjectOut, Task Profile, and TaskMutationService already support:

- `completion_mode="finite"`;
- `completion_mode="ongoing"`.

Model-facing `create_task` and `update_task` still cannot express that distinction.

H2A closes only this write-parity gap.

Do NOT change relation vocabulary or `link_objects` in H2A.
That is a separate later H2B.

No schema migration.
No client change.
No production deploy.

## Canonical semantics

Task remains canonical `kind="task"`.

`completion_mode` is a Task property, not a new Object kind:

- `finite`: ordinary completable Task;
- `ongoing`: continuing Direction/Activity; it must not be completed with lifecycle status `done`.

Omitting `completion_mode` on create preserves existing default behavior: finite.

Omitting `completion_mode` on update means no change.

Do not infer ongoing from `due_at`, wording, recurrence, age, or any other field.

The existing domain validations remain authoritative, including:
- ongoing Task cannot be `done`;
- a completion-mode change that invalidates adjacent confirmed/proposed `part_of` composition must fail;
- non-Task Objects cannot receive `completion_mode`.

## Tool input schemas

Update `CreateTaskInput` with an optional field:

`completion_mode`

Accepted explicit values only:
- `finite`
- `ongoing`

Update `UpdateTaskInput` with the same optional field.

For update, preserve field-presence semantics:
- omitted => no mutation;
- `finite` => explicitly set finite;
- `ongoing` => explicitly set ongoing;
- explicit JSON null should fail validation rather than silently mean finite/no-op.

Use the canonical constants/types where practical rather than duplicating loose strings.

Do not add any third mode.

## Assistant function contract

Update the Assistant definitions for both:

- `create_task`;
- `update_task`.

Expose `completion_mode` as a string enum:
- `finite`
- `ongoing`.

Tool text must state concisely:
- finite is a completable Task;
- ongoing is a continuing Direction/Activity;
- ongoing cannot be marked `done`;
- omit the field when the user has not expressed the distinction;
- do not infer ongoing merely from a due date or long duration.

Do not tell the model to create another kind for ongoing work.

Do not redesign the global prompt in H2A unless a tiny shared sentence is necessary to keep the live tool contract consistent.

## MCP / shared registry parity

The same `CreateTaskInput` / `UpdateTaskInput` models must expose the field through MCP.

Verify the MCP/generated schema contains the same finite/ongoing enum and no extra semantic value.

Assistant and MCP must reach the same `DomainToolService` behavior.

Do not add a separate MCP-only field or adapter.

## Domain create_task

Pass `input.completion_mode` into the canonical `ObjectCreate`.

Requirements:

1. omitted create => stored/read effective finite, preserving current behavior;
2. explicit finite => finite;
3. explicit ongoing => ongoing;
4. new Task still starts `status=open`;
5. origin/proposal/approval behavior is unchanged;
6. evidence/actor/dependency attachment behavior is unchanged.

Do not special-case storage outside existing GraphService/task-completion helpers.

## Domain update_task

Include `completion_mode` in the editable field set.

Pass it to the existing:

`TaskMutationService.patch_task_fields(...)`

with exact field-presence semantics.

Do not implement a second completion-mode validator in DomainToolService.

The existing mutation path must continue to enforce:
- ongoing + done invalid;
- composition/part_of constraints;
- idempotent same-value update;
- deleted Task cannot be modified.

`UpdateTaskOutput.changed` must reflect a real mode change.

An unchanged explicit mode should return `changed=false` when no other mutation is made, consistent with existing field behavior.

## Lifecycle interaction

Do not change `set_task_status` semantics.

Add regression coverage that:

- setting an ongoing Task to `done` remains rejected by the existing lifecycle/domain guards;
- changing a done finite Task to ongoing is rejected;
- changing an ongoing Task back to finite allows the ordinary finite lifecycle behavior afterward.

Do not auto-change status when mode changes.

## Composition interaction

Add focused coverage for `part_of` adjacency.

At minimum prove through the model-facing update path that:

- a completion-mode change that would create forbidden ongoing-child -> finite-parent composition is rejected;
- a valid finite -> ongoing parent relationship remains allowed;
- a failed change leaves both the Task mode and existing relation unchanged.

Do not alter the composition matrix.

## Same-turn / authorization semantics

No new authorization class is introduced.

Preserve current Tool Gateway / approval behavior:
- proposed writes stay proposed;
- approved-confirmed mode stays confirmed;
- object-id exposure requirements for update remain unchanged;
- create requires no object id;
- update still requires the Task id to be eligible under the existing gateway context.

Do not weaken tool-call policy.

## Tests — schemas and gateway

Add/update tests proving at minimum:

1. `CreateTaskInput` accepts omitted / finite / ongoing;
2. rejects any other string;
3. `UpdateTaskInput` accepts omitted / finite / ongoing;
4. rejects explicit null;
5. title-only update still excludes completion_mode from `model_fields_set`;
6. completion-mode-only update preserves field presence through gateway validation/staging;
7. Assistant create_task JSON schema exposes exactly finite/ongoing;
8. Assistant update_task JSON schema exposes exactly finite/ongoing;
9. MCP/shared registry schema exposes the same field and enum;
10. no existing tool gains a completion_mode field accidentally.

## Tests — domain behavior

Add/update tests proving at minimum:

1. create omitted => finite effective result;
2. create explicit finite => finite;
3. create ongoing => ongoing + status open;
4. update finite -> ongoing;
5. update ongoing -> finite;
6. same-value update is idempotent / changed false;
7. invalid mode fails before mutation;
8. ongoing cannot become done through existing status tool;
9. done finite cannot be changed to ongoing;
10. invalidating `part_of` change is rejected atomically;
11. valid composition mode change works;
12. evidence/actor/dependency behavior remains unchanged when completion_mode is supplied;
13. proposed vs approved-confirmed state/origin behavior is unchanged;
14. ObjectOut / Task Profile read back the updated mode.

## Documentation

Update:

`docs/SECRETARY_TOOLSET_MATRIX.md`

so completion_mode is no longer marked PARTIAL/tool-unwritable.

Append a concise closure note to:

`docs/ontology_harness_parity_audit.md`

Do not rewrite the original audit history; record that H2A closes only the completion_mode write gap and leaves the free-form `link_objects.relation_type` finding open for H2B.

## Validation

Run at minimum:

- focused new H2A tests;
- `backend/tests/test_domain_tools.py`;
- `backend/tests/test_tool_gateway.py`;
- relevant Task lifecycle/composition tests;
- direct Task API/mutation tests that exercise completion mode;
- tool registry/schema parity tests for Assistant + MCP;
- Ruff check/format on touched Python;
- `git diff --check`.

No Flutter analyze/build unless Dart is unexpectedly changed; Dart should not change.

## Scope guard

Do NOT:

- change `link_objects.relation_type`;
- add/restrict relation types;
- change `part_of` direction or matrix;
- add planned_start/planned_end tool fields;
- add Person tool changes;
- change Task UI;
- add a new Task kind;
- infer ongoing automatically;
- change production schema;
- migrate/deploy/access production.

## Completion

Record in `PROJECT_STATE.md`:

- implementation SHA;
- exact create/update completion_mode contract;
- Assistant/MCP parity result;
- lifecycle/composition guard results;
- exact test counts;
- confirmation that relation allowlist remains unchanged/open for H2B;
- schema/client/production unchanged.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start H2B.
Do not start Task stabilization.
Do not deploy production.
