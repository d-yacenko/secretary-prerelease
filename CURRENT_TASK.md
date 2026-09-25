# Current task

HOLD

Person Graph G1R is implemented at `5bf01d80d6cafd561cea2f9fdfa57d56a0cae846`.

People search uses the Person title on its own and only effective identities for identity text. An active `user_rejected` identity does not find the Person until retract or confirm. First-party People detail can show a stored Telegram identity, an exact private Telegram route, and a stored private-chat candidate while `TELEGRAM_MTPROTO_AI_ENABLED` is false. Assistant routes and candidates keep the Telegram AI gate. A Telegram group is not a Person route. Graph confirm and reject write `user_confirmed` / `user_rejected` with `graph_ui:` provenance. Repeating a correction does not add another active row. Retract undoes active user feedback and keeps the history row. An ungrounded tuple fails closed. Overview, search, and rooted neighbor reads are capped, and open-task counts use SQL. No migration.

Checks: `tests/test_person_graph_workspace.py` 7 passed. `tests/test_graph_workspace.py` 7 passed; `test_rooted_deleted_task_can_be_inspected` still returns 404. `tests/test_graph_workspace_caps.py` 10 passed. `tests/test_graph_workspace_active_seeds.py` 8 passed. `tests/test_person_routes.py` 14 passed. `tests/test_person_assistant.py` 36 passed. `tests/test_person_enrichment.py` 20 passed. `tests/test_person_salience.py` 9 passed. `tests/test_person_evidence_ledger.py` 6 passed. `tests/test_person_identity.py` 12 passed. `tests/test_tool_gateway.py` 28 passed. `tests/test_telegram_mtproto_self_authored_policy.py` 10 passed. Combined 167 passed, 1 pre-existing failure. Flutter: `test/graph/people_workspace_screen_test.dart` 1 passed; `test/graph/graph_workspace_controller_test.dart` 17 passed; `test/graph/graph_workspace_screen_test.dart` 12 passed. The three screen tests that look for `Удалить` or `Спросить секретаря` after `Подробнее` still fail. No Dart files changed. Ruff and compile of touched Python passed. `git diff --check` clean.

Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.

Do not begin organizational relation inference, Task Refinement, Mattermost/Teams media-download adapters, or deploy.
