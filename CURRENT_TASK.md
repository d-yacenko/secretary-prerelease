# CURRENT_TASK

HOLD

## REL1D-HG4E.1 — decouple Person rename stale-read generation from Task-actor reconciliation

Implementation: `80544d6d27cadc76c6fb3a1e450450b97d69098a`

Person rename now increments a Person-presentation generation and does not increment `_personTaskGeneration`. Detail loads and actor reconciliations carry both generations. A response started before a successful rename cannot restore the previous title. An actor reconciliation already in flight is not applied as a whole Person presentation; exactly one follow-up is queued for the same Person with the latest task generation and latest presentation generation. Additional renames while that request is in flight replace the pending target. A rename with no reconciliation in flight does not issue a People-workspace GET. The follow-up can update `openTaskCount` and keeps the renamed title. Actor relation filtering and the Person rename API are unchanged.

Checks:

- Flutter `test/graph/person_rename_test.dart` + `test/graph/person_task_bridge_test.dart` + `test/graph/people_overview_window_test.dart`: 48 passed
- `dart format` on `client/test/graph/person_rename_test.dart`
- `dart analyze` on `graph_workspace_screen.dart` and `person_rename_test.dart`: 0 errors; pre-existing infos only in `graph_workspace_screen.dart`
- `git diff --check`: clean

No production deploy. Identity-candidate scan depth and People/Task shared topology remain separate.

Production remains:
`a9221699b4b725888213ff38e6673495a512042c`

Alembic remains:
`0054 / 0054`
