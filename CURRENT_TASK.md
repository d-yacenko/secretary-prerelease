# Current task — HOLD

Task Refinement T1R is implemented and awaiting architect review.

Implementation: `e37b7e1a2576855dd903c897ea164027fda97477`

An explicit confirmed write supersedes an active proposal for the same Task relation: the proposal is rejected and a new confirmed edge is created. A confirmed relation stays the current fact when a later proposal repeats it. A repeated proposal stays idempotent. Task Profile items expose `edge_state`, `edge_origin`, and `edge_confidence`. Rejected history stays out of the profile. `get_task_profile` is a bounded READ tool: after its output is committed, visible task, actor, dependency, and evidence ids are same-turn seen object ids, and visible edge ids are same-turn seen edge ids. `create_task` and `update_task` validate the whole relation batch before creating a Task or attaching that request's edges. No migration, auto-detection, proactive behavior, Project entity, or Graph UI redesign.

Checks:

- `tests/test_task_relations.py`: 9 passed.
- `tests/test_tool_gateway.py`: 28 passed.
- `tests/test_domain_tools.py`: 15 passed.
- `tests/test_task_lifecycle.py`: 13 passed. `test_update_task_deleted_task_rejected` and `test_delete_task_idempotent` already fail on the T1 task commit.
- `tests/test_direct_tasks_api.py`: 14 passed. `test_deleted_task_cannot_be_edited` and `test_deleted_task_cannot_change_status` already return 404 on that commit.
- `tests/test_task_materialization.py`: 10 passed. `test_task_taxonomy_documented_in_decisions` already fails because `DECISIONS.md` has no `kind=task`.
- `tests/test_auth_capture.py`: 28 passed.
- `tests/test_graph_workspace.py`: 7 passed. `test_rooted_deleted_task_can_be_inspected` still expects 200 and gets 404.
- `tests/test_graph_workspace_caps.py`: 10 passed.
- `tests/test_graph_workspace_active_seeds.py`: 8 passed.
- `tests/test_person_graph_workspace.py`: 7 passed.
- `tests/test_remove_relation.py` and `tests/test_assistant_evidence_closure.py` passed in the same run.
- Combined focused Python run: 175 passed, 6 pre-existing failures.
- No Dart files changed.
- Ruff and compile of touched Python passed. `git diff --check` clean.

No migration. Production remains exact `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`. Development migrations `0048/0049` remain unapplied. Do not start the next phase.
