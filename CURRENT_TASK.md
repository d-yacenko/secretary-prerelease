# Current task

HOLD

Person Graph G1 is implemented at `221deca7a69a283e9c48bebb0cc0ef54d12614a4`.

The Graph screen has a compact `Задачи | Люди` switch. Tasks keeps the existing graph workspace. People is a bounded read of already-known canonical Person Objects through `GET /graph/people-workspace`. Salience orders the overview and does not hide a Person from search or a rooted view. Rooted view shows that Person, existing non-organizational edges, and linked open Tasks. Identity correction uses the existing Person evidence ledger: reject, retract, and confirm only an exposed candidate that is not owned by another Person. No new migration, no organizational edges, and no production deploy.

Checks: `tests/test_person_graph_workspace.py` 3 passed. `tests/test_graph_workspace.py` 7 passed; `test_rooted_deleted_task_can_be_inspected` still returns 404 and fails the same way on the G1 task commit. `tests/test_graph_workspace_caps.py` 10 passed. `tests/test_graph_workspace_active_seeds.py` 8 passed. `tests/test_person_routes.py` 14 passed. `tests/test_person_assistant.py` 36 passed. `tests/test_person_enrichment.py` 20 passed. `tests/test_person_salience.py` 9 passed. `tests/test_person_evidence_ledger.py` 6 passed. `tests/test_person_identity.py` 12 passed. `tests/test_tool_gateway.py` 28 passed. Combined 153 passed, 1 pre-existing failure. Flutter: `test/graph/people_workspace_screen_test.dart` 1 passed; `test/graph/graph_workspace_controller_test.dart` 17 passed; `test/graph/graph_workspace_screen_test.dart` 12 passed. Three screen tests (`Details delete refreshes overview without deleted task`, `Details delete current root falls back to overview`, `Details Ask Secretary does not refresh disposed Graph screen`) fail on the unmodified G1 task commit because the object-detail screen has no text `Удалить` or `Спросить секретаря` after `Подробнее`. Analyzer on touched Dart reported only existing infos. Ruff and compile of touched Python passed. `git diff --check` clean.

Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.

Do not begin organizational relation inference, Task Refinement, Mattermost/Teams media-download adapters, or deploy.
