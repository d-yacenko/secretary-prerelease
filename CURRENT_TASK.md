# Current task — Task Stabilization S1: deleted Task mutation/delete convergence

Harness H2C is accepted.

The only remaining failures in the current focused Task/Harness regression are:

- `test_update_task_deleted_task_rejected`;
- `test_delete_task_idempotent`.

They share one root cause.

## Canonical deletion semantics

Secretary currently recognizes two deleted Task representations:

1. canonical tombstone:
   - `deleted_at != NULL`;
   - Task status is normally `deleted`;

2. legacy deletion marker:
   - `status == "deleted"`;
   - `deleted_at` may still be NULL.

Both are intentionally hidden from active reads.

That existing read contract is already accepted and must remain unchanged:
- normal `GraphService.get_object` treats either form as not found;
- workspace/search/overview active reads exclude either form;
- a deleted Task must not reappear merely because mutation/delete code can inspect it internally.

S1 aligns only Task mutation/delete behavior.

## Required Task mutation lookup

Task mutation code needs a same-user raw lookup that can inspect a hidden/deleted Task before deciding whether mutation is allowed.

Implement this inside the Task mutation layer, not by weakening active Graph reads.

Preferred shape:
- one canonical helper in `TaskMutationService` that loads by `Object.id + user_id` without active-read filtering;
- validates `kind == "task"`;
- when `allow_deleted=False`, rejects either:
  - canonical tombstone; or
  - legacy `status="deleted"`
  with exactly:
  `deleted task cannot be modified`;
- missing/cross-user remains NotFound;
- non-Task remains the existing Task-only validation error.

Use that same Task-mutation lookup for:
- field patch;
- status mutation;
- soft delete preflight;
- the model-facing `update_task` prevalidation path.

Do not add a public “include deleted” Graph read API.
Do not weaken `GraphService.get_object`.

If `DomainToolService._get_task_for_mutation` becomes redundant, delegate it to the Task mutation helper or remove the duplicate narrowly. Do not maintain two divergent deleted-Task lookup implementations.

## Update/status behavior

For a same-user deleted Task, regardless of deletion representation:

- direct Task PATCH returns 422 with `deleted task cannot be modified`;
- direct status mutation returns 422 with the same message;
- tool `update_task` raises sanitized `ToolError("deleted task cannot be modified")`;
- tool `set_task_status` does the same;
- no field/status/edge/evidence/actor/dependency mutation occurs;
- no embedding job is enqueued.

Missing/cross-user ids must remain not-found and must not reveal that an object exists.

Do not permit restoring a deleted Task via ordinary patch/status operations.

Explicit restoration flows elsewhere remain unchanged.

## Delete idempotency

Task delete is semantic soft deletion.

### First delete of an active Task

Preserve current behavior:
- `changed=true`;
- canonical tombstone is written;
- Task status becomes `deleted`;
- row remains;
- incident edges remain;
- first delete may enqueue the existing embedding/update side effect exactly as before if that is the current contract.

### Repeated delete of canonical tombstone

Must return:
- `changed=false`;
- no timestamp rewrite;
- no additional mutation;
- no embedding enqueue.

### Delete of legacy `status="deleted", deleted_at=NULL`

Treat it as already semantically deleted:
- `changed=false`;
- do NOT silently add `deleted_at` in S1;
- do NOT rewrite timestamps/status;
- do NOT enqueue embedding;
- row and incident edges remain unchanged.

Reason: a no-op response must not hide a normalization write. If legacy-row normalization is ever needed, that is a separate migration/audit task.

Do not change generic `ObjectDeletionService` semantics for non-Task objects merely to make these Task tests pass.

## Read visibility regression

Explicitly preserve the accepted visibility contract:

- legacy `status="deleted"` Task remains hidden from Graph active reads;
- canonical tombstoned Task remains hidden;
- done Task remains visible;
- workspace root behavior remains consistent with the accepted V8E1R tests.

Do not change `object_is_active`, `is_object_hidden_from_active_reads`, or search/workspace filters unless a failing regression proves a truly necessary no-semantic-change refactor.

## Restoration boundary

Do not change:
- `restore_object_from_explicit_intake`;
- source re-import restoration behavior;
- passive sync skip behavior.

Ordinary Task mutation is not a restoration path.

## Tests — required

Add/update focused coverage proving at minimum:

1. tool update on legacy `status=deleted, deleted_at=NULL` returns `deleted task cannot be modified`;
2. tool update on canonical tombstone returns the same;
3. tool status mutation on both forms returns the same;
4. direct Task PATCH on both forms is HTTP 422, not 404;
5. direct Task status mutation on both forms is HTTP 422, not 404;
6. first soft delete of active Task returns `changed=true`, sets `deleted_at`, status `deleted`, preserves row/edges;
7. repeated delete of canonical tombstone returns `changed=false` and preserves the original `deleted_at`;
8. delete of legacy `status=deleted, deleted_at=NULL` returns `changed=false` and leaves `deleted_at=NULL`;
9. tool delete and direct REST delete agree on both deletion forms;
10. repeated/no-op delete does not enqueue embedding;
11. missing Task id remains not-found;
12. cross-user Task remains not-found;
13. non-Task id preserves Task-only error semantics;
14. active read `GraphService.get_object` still hides both deleted forms;
15. Graph workspace/root tests still hide both deleted forms and keep done visible;
16. generic note/object delete idempotency tests remain unchanged;
17. explicit source re-add restoration tests remain green.

## Regression

Run at minimum:

- `backend/tests/test_task_lifecycle.py`;
- `backend/tests/test_direct_tasks_api.py`;
- `backend/tests/test_universal_object_delete.py`;
- `backend/tests/test_graph_workspace.py`;
- `backend/tests/test_graph_workspace_part_of_closure.py`;
- `backend/tests/test_h2a_completion_mode.py`;
- `backend/tests/test_h2b_link_objects.py`;
- `backend/tests/test_mcp.py`;
- `backend/tests/test_domain_tools.py`;
- `backend/tests/test_tool_gateway.py`;
- Ruff check/format touched Python;
- `git diff --check`.

Expected stabilization result:
- the two historical lifecycle failures become green;
- no new failures are introduced.

No Flutter analyze/build unless Dart is unexpectedly changed; Dart should not change.

## Scope guard

Do NOT:

- weaken active read filtering;
- expose deleted Tasks in Graph/workspace/search;
- add restore-through-update behavior;
- normalize legacy deleted rows by writing tombstones;
- change generic non-Task delete semantics;
- change lifecycle statuses;
- change completion_mode semantics;
- change relation semantics;
- add H2D/planned interval tool fields;
- change People;
- change schema/migrations/client;
- access/deploy production.

## Completion

Record in `PROJECT_STATE.md`:

- implementation SHA;
- exact raw Task mutation lookup contract;
- update/status behavior for canonical and legacy deleted Tasks;
- delete idempotency behavior for both forms;
- confirmation whether legacy no-op delete leaves `deleted_at=NULL`;
- embedding enqueue behavior on no-op delete;
- exact regression counts;
- confirmation that active reads/workspace visibility stayed unchanged;
- schema/client/production unchanged.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start S2.
Do not start H2D.
Do not deploy production.
