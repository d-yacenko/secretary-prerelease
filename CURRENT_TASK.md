# Current task — Harness H2A-R: repair MCP completion_mode null semantics

Harness H2A implementation `108f4e9764caeebbb70367bc53f15c4e979a1e60` is NOT yet accepted.

The domain and Assistant portions are otherwise correct.

One MCP boundary bug remains.

## Defect

Current MCP wrappers declare:

`completion_mode: Literal["finite", "ongoing"] | None = None`

for both `create_task` and `update_task`.

They then forward the field only when:

`completion_mode is not None`

This conflates:

- field omitted;
- explicit JSON `null`.

Because the MCP input annotation itself admits `None`, the generated MCP schema can expose a null branch. An explicit `completion_mode: null` can therefore become silent omission.

That violates H2A.

The existing H2A helper `_enum_values()` is insufficient because it only discovers `finite` / `ongoing` enums and does not prove that `null` is absent from the same schema.

## Required contract

For both MCP `create_task` and `update_task`:

- field omitted => allowed;
- `"finite"` => allowed;
- `"ongoing"` => allowed;
- explicit JSON `null` => rejected as invalid tool input;
- every other value => rejected.

The generated MCP schema property must expose only the two semantic string values. It must not advertise `null` as an accepted type/value.

Assistant definitions remain as implemented in H2A.

Shared Domain Tool input models remain as implemented in H2A.

## Implementation

Repair the MCP function signature/binding in the smallest supported way that distinguishes optional omission from an explicit null value.

A non-nullable `Literal["finite", "ongoing"]` annotation with an omission-capable default/sentinel is acceptable if the MCP library generates the required optional-but-non-null schema and runtime behavior.

Another small MCP-local adapter is acceptable if necessary.

Do NOT:
- turn completion_mode into a required MCP field;
- invent a sentinel visible in the public schema;
- pass a sentinel into DomainToolService;
- relax CreateTaskInput / UpdateTaskInput validation;
- special-case finite in the Domain service.

The final MCP call must still reach the same shared registered tool/domain behavior.

## Tests

Strengthen `backend/tests/test_h2a_completion_mode.py` or add one focused repair test.

At minimum prove through the real MCP `Client`:

1. `list_tools()` shows create_task completion_mode as optional but non-nullable;
2. `list_tools()` shows update_task completion_mode as optional but non-nullable;
3. schema admits exactly `finite` and `ongoing`, with no null type/const/enum branch;
4. MCP create_task with completion_mode omitted reaches normal behavior;
5. MCP create_task with `finite` validates;
6. MCP create_task with `ongoing` validates;
7. MCP create_task with explicit `null` is rejected before becoming an omission;
8. MCP update_task with completion_mode omitted preserves no-mode-update behavior;
9. MCP update_task with `finite` validates;
10. MCP update_task with `ongoing` validates;
11. MCP update_task with explicit `null` is rejected;
12. an invalid string remains rejected.

Do not rely only on direct Pydantic model construction for the null cases.

Make the schema assertion detect nullable branches recursively, not merely collect enum members.

## Regression

Re-run at minimum:

- `backend/tests/test_h2a_completion_mode.py`;
- relevant MCP tests for create_task/update_task;
- `backend/tests/test_tool_gateway.py`;
- `backend/tests/test_domain_tools.py`;
- relevant completion/lifecycle/composition tests from H2A;
- Ruff check/format on touched Python;
- `git diff --check`.

The two previously reported unrelated Task lifecycle failures may remain only if they are the exact same tests and behavior.

## Explicit non-scope

Do NOT fix the pre-existing MCP tool-list mismatch for `get_task_profile` in H2A-R.

Record it as a separate open Harness parity finding if not already recorded.

Do NOT:
- start H2B;
- touch `link_objects.relation_type`;
- change Assistant completion-mode semantics;
- change domain completion-mode semantics;
- change Task UI/client;
- change schema/migrations;
- access/deploy production.

## Completion

Record in `PROJECT_STATE.md`:

- repair implementation SHA;
- exact MCP optional-but-non-null contract;
- generated schema verdict;
- real MCP explicit-null call verdict for create and update;
- regression results;
- explicit confirmation that `get_task_profile` MCP-list mismatch remains separate/unfixed;
- schema/client/production unchanged.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start H2B.
Do not start Task stabilization.
Do not deploy production.
