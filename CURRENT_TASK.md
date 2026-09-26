# Current task — Task Map V8E1R: reconcile rooted deleted-task test contract

Task Map V8E1 confirmed `part_of` workspace closure is accepted at `f9c074be21f08af4a80381325215f9c4b83a68f8`.

This is a very small contract-cleanup task. Prefer tests/docs only. Do not change Graph workspace production behavior unless the investigation contradicts the canonical visibility policy below.

## Canonical policy

Secretary active reads hide an Object when either:
- `deleted_at != null`; or
- legacy `status == "deleted"`.

This is centralized in `app.domain.object_visibility.is_object_hidden_from_active_reads`.

Therefore:

- explicit rooted Graph access to a non-deleted terminal Task such as `done` remains allowed;
- explicit rooted Graph access to a deleted/tombstoned Task must return 404;
- ordinary overview/neighbors must continue to exclude deleted/tombstoned Objects.

Do NOT weaken `GraphWorkspaceService`, `GraphService.get_object`, or the shared object-visibility policy to make a deleted root visible.

## Required change

Reconcile the stale backend test:

`backend/tests/test_graph_workspace.py::test_rooted_deleted_task_can_be_inspected`

with the canonical policy.

Prefer replacing/renaming it to assert 404 for a legacy `status="deleted"` root.

Also add or reuse one focused test proving a truly tombstoned Task root is 404. Use the canonical deletion path/helper if practical; do not hand-roll implementation details merely to satisfy the assertion.

Keep the existing test proving a non-deleted terminal Task root (currently `done`) returns 200.

## Scope guard

No product feature.
No hierarchy behavior change.
No API/schema change.
No client change.
No migration.
No relation repair.
No production deploy.

Do not fix unrelated historical failing tests in this phase.

## Validation

Run at minimum:

- `backend/tests/test_graph_workspace.py`;
- V8E1 closure tests;
- `backend/tests/test_graph_workspace_active_seeds.py`;
- `backend/tests/test_graph_workspace_caps.py`;
- `backend/tests/test_task_composition.py`.

Expected outcome: the V8E1 workspace/composition target set has no rooted-deleted baseline failure.

Run the repository's normal Ruff/format check for touched Python and `git diff --check`.

No Flutter build/analyze is needed unless client code is unexpectedly touched; client production code should not be touched.

## Completion

Record in `PROJECT_STATE.md`:
- implementation SHA;
- exact deleted-root contract now asserted;
- whether production code changed;
- exact test counts.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start V8E2.
Do not repair relation rows.
Do not deploy production.
