# Current task — Harness H2D: Task actor/dependency MCP contract parity

Graph G3A-R3 is human-accepted.
Assistant P1 is live in production.

Production backend/runtime and `origin/production`:
`7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4`

Alembic:
`0050`

This task authorizes ONE bounded BACKEND/HARNESS parity corrective on `main`.

NO production deploy is authorized.
No client product change is authorized.

Do not start Person MCP exposure, Person/Organization ontology work, G3B, S3, or any unrelated cleanup.

## Confirmed parity gap

The canonical shared Task write models and the internal Assistant already support:

- `requested_by_person_id`;
- `delegated_to_person_ids`;
- `waiting_on_person_ids`;
- `involved_person_ids`;
- `depends_on_task_ids`.

`get_task_profile` is already MCP-exposed and returns the corresponding canonical Task relations.

But the hand-written MCP wrappers in `backend/app/mcp/server.py` currently omit those five write parameters from both `create_task` and `update_task`.

Therefore MCP can read the rich Task Profile but cannot even EXPRESS the same typed actor/dependency intent at the MCP contract boundary.

## Important safety boundary

This task is CONTRACT PARITY, not trusted MCP write execution.

Current MCP policy is intentional:

- MCP has no trusted approval transport;
- `create_task` / `update_task` are `INTERNAL_WRITE`;
- `ExecutionContext.MCP` therefore returns `REQUIRE_APPROVAL`;
- `execute_mcp_tool` converts that into a sanitized MCP tool error;
- no write executes.

PRESERVE THIS EXACTLY.

Do NOT:
- allow MCP internal writes;
- change `evaluate_policy`;
- add an approval bypass;
- introduce a fake approval token/boolean;
- execute staged MCP writes;
- change write provenance/state semantics.

After H2D, MCP should be able to describe the same Task relation intent in its public tool schema and have those arguments validated/forwarded into the SAME existing approval path. It still must not mutate data through MCP.

A future trusted MCP approval transport, if desired, is a separate architecture task.

## Canonical field semantics

The MCP parameter names must match the shared `CreateTaskInput` / `UpdateTaskInput` and Assistant contracts EXACTLY:

- `requested_by_person_id: string`;
- `delegated_to_person_ids: array[string]`;
- `waiting_on_person_ids: array[string]`;
- `involved_person_ids: array[string]`;
- `depends_on_task_ids: array[string]`.

Do not invent aliases such as `assignee`, `owner`, `blocker`, `participants`.

Existing meanings remain:

- `requested_by`: source/requester;
- `delegated_to`: assignee/delegate;
- `waiting_on`: Person blocker/wait;
- `involves`: participant;
- `depends_on`: Task dependency/prerequisite.

All are ADDITIVE relation inputs through the existing `DomainToolService` path.
No removal semantics are added.

## Part A — MCP create_task signature parity

Extend MCP `create_task` with all five canonical relation inputs.

Public MCP schema requirements:

- every field is optional;
- when present, it is NON-NULLABLE;
- `requested_by_person_id` is a string;
- the four list fields are arrays of strings;
- list fields preserve the canonical maximum of 8 items;
- explicit JSON `null` must be rejected before `execute_mcp_tool`;
- wrong scalar/list shapes must be rejected before `execute_mcp_tool`.

Omission must remain omission at the forwarding boundary.

Do not silently turn omitted relation fields into semantic values.

It is acceptable to reuse the existing MCP-local omission-sentinel technique used for `completion_mode`, generalized cleanly if needed.

An explicitly provided empty list may remain an explicit additive no-op if accepted by the shared contract.

Forward canonical names unchanged to:

`_run_tool("create_task", "create_task", arguments)`.

Do not call relation services directly from MCP.

## Part B — MCP update_task signature parity

Extend MCP `update_task` with the same five canonical relation inputs.

Requirements are the same:

- optional;
- non-nullable when present;
- max 8 for list fields;
- omitted fields are NOT forwarded;
- explicit null invalid before gateway;
- canonical names unchanged.

Preserve existing field-presence semantics for:
- `title`;
- `body`;
- `due_at`;
- `evidence_object_ids`;
- `completion_mode`.

Do not change `completion_mode` omission/null behavior accepted in H2A-R.

Do not add relation removal/replace semantics. Task relation lists remain additive.

## Part C — single shared domain path

Do not duplicate Task relation validation in MCP.

The authoritative validation/mutation path remains:

MCP wrapper
-> `execute_mcp_tool`
-> `ToolExecutionGateway`
-> registry `CreateTaskInput` / `UpdateTaskInput`
-> `DomainToolService.create_task/update_task`
-> existing `TaskRelationService`.

The shared DomainToolService already:
- prevalidates all explicit relation endpoints before mutation;
- validates Person vs Task kinds;
- rejects self-dependency;
- preserves user isolation;
- creates agent-origin relation edges with canonical proposed/confirmed behavior according to write mode;
- keeps writes additive/idempotent.

Do not change that behavior unless a focused parity test proves an existing shared-contract defect. If such a defect is found, STOP and report it rather than widening scope.

## Part D — Assistant contract must remain unchanged

The internal Assistant already exposes these fields.

Do not edit its semantics or prompt.

Add a focused parity assertion that Assistant and MCP surface the SAME five canonical Task relation parameter names.

Do not require byte-for-byte equality of their whole schemas because the transports differ.

## Part E — real MCP schema regression

Using the in-process MCP Client and `list_tools()`, prove for BOTH `create_task` and `update_task`:

1. all five relation fields exist;
2. none is required;
3. `requested_by_person_id` is non-nullable string;
4. each list field is non-nullable array of string;
5. list `maxItems == 8`;
6. no unsupported Task actor aliases appear;
7. existing `completion_mode` remains optional, non-nullable, enum `finite|ongoing`.

Use recursive null detection where schema wrappers/anyOf may occur.

## Part F — real MCP call / forwarding regression

Spy on or otherwise observe `execute_mcp_tool` at the MCP boundary, following the established H2A-R test style.

For `create_task`:

- call with all five relation fields and valid UUID strings;
- prove the exact canonical arguments reach `execute_mcp_tool`;
- result must reach the EXISTING approval-required path;
- no Object/Edge row is created.

For `update_task`:

- call with all five relation fields;
- prove exact arguments reach `execute_mcp_tool`;
- result must reach approval-required;
- existing Task and edges remain unchanged.

Also prove omission:
- an omitted relation field is not forwarded.

## Part G — invalid MCP input regression

For each shape category at minimum:

- `requested_by_person_id: null`;
- one list field: `null`;
- one list field: scalar string instead of array;
- one list field: >8 ids;
- malformed UUID string that passes transport shape but fails shared validation/gateway.

Expected boundary:

- schema/type/null/size failures do not call `execute_mcp_tool`;
- malformed UUID may reach the shared gateway validation but must not execute domain mutation;
- no traceback/internal implementation detail is exposed.

Do not weaken generic MCP error sanitization.

## Part H — read/write ontology symmetry regression

Create canonical fixture data using existing test/domain helpers, NOT via MCP write execution:

- one Task;
- one requested_by Person;
- one delegated_to Person;
- one waiting_on Person;
- one involves Person;
- one dependency Task.

Read it through MCP `get_task_profile`.

Assert that the profile exposes the same five semantic relation categories that the MCP create/update schema can now express.

This is contract symmetry only; do not invent a single combined DTO.

## Part I — MCP toolset matrix truthfulness

Update `docs/SECRETARY_TOOLSET_MATRIX.md` minimally.

It currently says actor roles/dependencies are supported through `create_task/update_task` without distinguishing surfaces.

Clarify in substance:

- Assistant/shared domain contract: typed actor/dependency writes supported;
- MCP schema: typed actor/dependency parameters supported after H2D;
- MCP execution: INTERNAL_WRITE still requires approval and MCP has no trusted approval transport, therefore direct MCP mutation remains fail-closed.

Do not mark Person-specific Assistant tools as MCP-supported.

Do not broaden the matrix into Person/Organization design.

## Person tools explicitly OUT OF SCOPE

The following remain `mcp_exposed=False`:

- `resolve_person`;
- `find_person_communications`;
- `find_person_identity_candidates`;
- `list_person_routes`;
- `record_person_route_choice`;
- `confirm_person_identity`;
- `reject_person_identity`;
- `retract_person_identity_feedback`.

Do not flip any of these flags.

Their MCP exposure and any organizational-role additions belong to later Person ontology/parity work.

## Policy regressions required

Explicitly prove:

- `evaluate_policy(INTERNAL_WRITE, MCP) == REQUIRE_APPROVAL`;
- MCP create_task with actor/dependency fields is still approval-required;
- MCP update_task with actor/dependency fields is still approval-required;
- no write handler executes in MCP context;
- normal read MCP tools remain allowed.

Do not change `ToolPermission` classifications.

## Required tests

Run at minimum:

- new focused H2D parity tests;
- `backend/tests/test_mcp.py`;
- `backend/tests/test_h2a_completion_mode.py`;
- `backend/tests/test_h2b_link_objects.py`;
- `backend/tests/test_tool_gateway.py`;
- `backend/tests/test_domain_tools.py`;
- `backend/tests/test_task_relations.py`;
- `backend/tests/test_task_operational.py`.

Run Ruff on touched Python.
Run `git diff --check`.

No client tests/build required.
No live OpenAI/provider call.
No production connection.

If unrelated environment/baseline tests fail, reproduce/report without widening scope.

## Expected diff

Expected product/doc changes are narrow:

- `backend/app/mcp/server.py`;
- focused H2D tests;
- minimal `docs/SECRETARY_TOOLSET_MATRIX.md`;
- `PROJECT_STATE.md`;
- `CURRENT_TASK.md`.

Shared schemas / DomainToolService / policy SHOULD NOT need product changes.

If they do, STOP and report the exact reason.

## Explicitly forbidden

Do NOT:

- deploy production;
- move `origin/production`;
- change MCP approval policy;
- add an approval bypass;
- expose Person tools to MCP;
- add Person/Organization relation types;
- modify Assistant prompt;
- change Task relation semantics;
- add migrations;
- change client code;
- start G3B;
- start S3;
- fix unrelated polish.

## Completion

On completion:

1. update `PROJECT_STATE.md` with:
   - exact MCP relation fields added;
   - schema omission/null/list-bound behavior;
   - forwarding behavior;
   - explicit note that MCP writes remain approval-blocked;
   - read/write ontology symmetry result;
   - tests/Ruff/diff-check;
   - implementation SHA;
   - confirmation that policy, shared domain semantics, Person exposure, client, schema DB, and production did not change;
2. return `CURRENT_TASK.md` to HOLD;
3. push implementation/HOLD commits to `main`;
4. do not deploy;
5. STOP.

Final report must state:

- exact five fields;
- MCP public schema semantics;
- create/update forwarding result;
- approval-policy result;
- get_task_profile symmetry result;
- Person MCP exposure unchanged?;
- tests/Ruff/diff-check;
- implementation SHA;
- HOLD/main SHA;
- rollout requirement.

Then STOP. Do not start Person/Organization work yourself.
