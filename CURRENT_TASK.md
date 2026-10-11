# CURRENT_TASK

HOLD

## REL1D-HG4E — reliable Person rename and canonical actor-relation presentation

Implementation: `1cb1269b019a7ea829766445268fbea201e5d4b1`

`PATCH /graph/people/{person_id}` renames only the current user's active Person title. The path does not use `get_user_embedding_service` or embedding refresh. Generic `PATCH /objects/{id}` is unchanged. The client rename dialog submits through the Person endpoint, stays open until success, surfaces API/network failure, and applies the returned title immediately for unrooted and rooted selection without re-rooting or reloading the People workspace. Older in-flight People responses cannot restore the previous title. Generic `Связи` skip the four Task actor types from controller edges and off-canvas neighbors. Specialized `Участие в задачах` and non-actor relations remain.

Checks:

- `pytest tests/test_person_graph_workspace.py`: 18 passed
- Flutter `test/graph/person_rename_test.dart` + `test/graph/person_task_bridge_test.dart` + `test/graph/people_overview_window_test.dart`: 46 passed
- Ruff on touched Python: clean
- `dart analyze` on touched Dart: 0 errors; pre-existing infos only in `graph_workspace_controller.dart` and `graph_workspace_screen.dart`
- `dart format` on `client/test/graph/person_rename_test.dart`
- `git diff --check`: clean

No production deploy. Identity-candidate scan depth and People/Task shared topology remain separate.

Production remains:
`a9221699b4b725888213ff38e6673495a512042c`

Alembic remains:
`0054 / 0054`
