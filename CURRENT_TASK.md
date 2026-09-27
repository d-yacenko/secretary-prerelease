# Current task — Harness H2C: expose registered get_task_profile through MCP

Harness H2B is accepted.

One small Harness consistency bug remains before Task stabilization:

- `TOOL_REGISTRY["get_task_profile"]` already has `mcp_exposed=True`;
- `MCP_TOOL_NAMES` therefore includes `get_task_profile`;
- `GetTaskProfileInput` and `GetTaskProfileOutput` already exist;
- `DomainToolService.get_task_profile` already exists;
- Assistant already exposes `get_task_profile`;
- the manual MCP server does not register a `get_task_profile` wrapper.

This causes the existing MCP list and streamable HTTP smoke tests to fail because the actual MCP tool set is missing one tool that the registry says is exposed.

H2C fixes only that mismatch.

No new Task semantics.
No new tool.
No schema migration.
No client change.
No production access/deploy.

## Required implementation

In `backend/app/mcp/server.py`:

1. import the existing `GetTaskProfileOutput`;
2. register one read-only MCP tool named exactly:
   `get_task_profile`;
3. signature:
   `task_id: str`;
4. call the existing shared path through:
   `_run_tool("get_task_profile", "get_task_profile", {"task_id": task_id})`;
5. return `GetTaskProfileOutput`.

Do not call `TaskProfileService` directly from MCP.
Do not duplicate domain logic.
Do not add an MCP-specific Task profile shape.

The wrapper should be structurally parallel to `get_object`.

## Contract

MCP `get_task_profile` must be:

- read-only;
- required `task_id`, non-nullable string;
- same-user isolated through the existing tool/domain stack;
- same output semantics as Assistant/shared DomainToolService.

It should return the existing Task profile, including whatever the shared profile already returns today:
- Task object;
- lifecycle / operational projection;
- `completion_mode`;
- parent/children;
- actors;
- dependencies/evidence;
- truncation fields where applicable.

Do not alter those fields in H2C.

## Error behavior

Preserve existing DomainToolService behavior.

At minimum:
- valid same-user Task returns profile;
- missing Task returns the normal sanitized tool error;
- non-Task id follows the existing TaskProfileService/DomainToolService error semantics;
- cross-user object is not exposed.

Do not invent MCP-specific error text.

## Registry parity

After the fix:

`set(tool.name for tool in await client.list_tools()) == MCP_TOOL_NAMES`

must hold again.

Do not change `mcp_exposed` flags to make the test pass.
The fix is to expose the already-declared tool.

Do not expose any currently Assistant-only Person tool through MCP.

## Tests

Add or update focused tests proving at minimum:

1. `get_task_profile` appears in in-process MCP `list_tools()`;
2. its input schema requires exactly `task_id` as the Task-profile argument and does not accept null;
3. a real MCP `Client.call_tool("get_task_profile", ...)` returns the expected Task id/title;
4. returned profile includes `completion_mode`;
5. parent/child or one existing relation/profile field survives the MCP serialization path;
6. missing id returns an error;
7. cross-user Task is not exposed;
8. the complete actual MCP tool-name set equals `MCP_TOOL_NAMES`;
9. streamable HTTP MCP `list_tools()` also equals `MCP_TOOL_NAMES`;
10. streamable HTTP can call `get_task_profile` successfully, if practical within the existing smoke fixture.

Prefer extending `backend/tests/test_mcp.py` rather than creating broad new infrastructure.

## Regression

Run at minimum:

- focused H2C tests;
- full `backend/tests/test_mcp.py`;
- `backend/tests/test_h2a_completion_mode.py`;
- `backend/tests/test_h2b_link_objects.py`;
- `backend/tests/test_tool_gateway.py`;
- `backend/tests/test_domain_tools.py`;
- relevant Task Profile tests;
- Ruff check/format touched Python;
- `git diff --check`.

Expected outcome:
- the two previously failing MCP list/smoke tests should become green;
- the two previously known Task lifecycle failures may remain unchanged:
  - `test_update_task_deleted_task_rejected`;
  - `test_delete_task_idempotent`.

If any other test fails, investigate before HOLD.

## Documentation

Append a concise closure note to:
- `docs/SECRETARY_TOOLSET_MATRIX.md` if it currently implies incomplete MCP Task-profile exposure;
- `docs/ontology_harness_parity_audit.md` noting that the registry/server mismatch is closed.

Do not rewrite historical audit entries.

Do not expand the Task Profile Assistant description in H2C; that is a separate nonblocking documentation/contract refinement.

## Scope guard

Do NOT:

- change `get_task_profile` domain semantics;
- change Task Profile payload shape;
- change Assistant schema/description except only if a test proves an accidental mismatch caused directly by the MCP wrapper (unlikely);
- change lifecycle/delete behavior;
- fix the two Task lifecycle failures;
- expose Person Assistant-only tools through MCP;
- change `link_objects`;
- add planned interval tool fields;
- change client/schema migrations;
- access/deploy production.

## Completion

Record in `PROJECT_STATE.md`:

- implementation SHA;
- exact wrapper added;
- in-process tool-set parity result;
- streamable HTTP parity result;
- successful Task profile MCP call result;
- error/isolation tests;
- exact regression counts;
- whether the two known lifecycle failures remain unchanged;
- schema/client/production unchanged.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start Task stabilization.
Do not start H2D.
Do not deploy production.
