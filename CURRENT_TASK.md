# Current task — HOLD

Task Refinement T1 is implemented and awaiting architect review.

Implementation: `2f6f1954e0414657a6eb5892cc5f2b8682493d26`

Canonical Tasks stay `Object(kind="task")`. Directed Task→Person roles are `requested_by`, `delegated_to`, `waiting_on`, and `involves`. `depends_on` stays Task→Task. New evidence writes are `references` to an active same-user non-Task. Duplicate active same-direction edges are idempotent. Removal sets `state=rejected` and keeps the row. First-party writes are `origin=user`, `state=confirmed`. Assistant create/update stays one internal write and uses the existing proposed/approved state. `get_task_profile` is a read-only tool for UI and Assistant/MCP. Relation ids must already be exposed in the same Assistant turn. Roles are not inferred. Lifecycle status is not changed by relation writes. `related_to` is not treated as an actor role. Graph labels are `Запросил`, `Поручено`, `Ждём`, and `Участвует`. No migration, auto-detection, proactive reminder, Project entity, or Graph UI redesign.

Checks:

- `tests/test_task_relations.py`: 6 passed.
- `tests/test_task_lifecycle.py`: 13 passed. `test_update_task_deleted_task_rejected` and `test_delete_task_idempotent` already fail on the task commit `da7573792e3eb99ee0b71dd83d529bbda6e809c5`.
- `tests/test_direct_tasks_api.py`: 14 passed. `test_deleted_task_cannot_be_edited` and `test_deleted_task_cannot_change_status` already return 404 on that task commit.
- `tests/test_task_materialization.py`: 10 passed. `test_task_taxonomy_documented_in_decisions` already fails because `DECISIONS.md` has no `kind=task`.
- `tests/test_tool_gateway.py`: 28 passed.
- `tests/test_domain_tools.py`: 15 passed.
- `tests/test_graph_workspace.py`: 7 passed. `test_rooted_deleted_task_can_be_inspected` still expects 200 and gets 404.
- `tests/test_graph_workspace_caps.py`: 10 passed.
- `tests/test_graph_workspace_active_seeds.py`: 8 passed.
- `tests/test_person_graph_workspace.py`: 7 passed.
- `tests/test_auth_capture.py`: 28 passed.
- Combined focused Python run: 146 passed, 6 pre-existing failures.
- Flutter `test/ui/domain_labels_test.dart`: 5 passed.
- Ruff and compile of touched Python passed. `git diff --check` clean.

No migration. Production remains exact `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`. Development migrations `0048/0049` remain unapplied. Do not start the next phase.
