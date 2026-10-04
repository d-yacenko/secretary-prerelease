# CURRENT_TASK

## Status

HOLD

## REL1D-C2

Implemented at `dc07dfce13bcaef08b51765ca5930266fa7c188b`.

The client selects grounded role-import rows only after an explicit Person or promotion choice, then prepares one frozen ActionPlan through `POST /people/role-import/action-plan`. Approve and reject reuse `POST /assistant/action-plans/{id}/approve` and `POST /assistant/action-plans/{id}/reject`. The result card is the backend presentation and the ActionPlan response. Role-import confirmation does not call `/assistant/action-plans/{id}/resume`, does not append a chat message, and does not call a model. A pending ordinary chat ActionPlan blocks role-import prepare, approve, and reject. Voice approval stays on the chat plan.

Files: `client/lib/api/role_import_models.dart`, `client/lib/api/secretary_api_client.dart`, `client/lib/assistant/assistant_controller.dart`, `client/lib/assistant/assistant_screen.dart`, `client/lib/assistant/role_import_preview.dart`, `client/test/assistant/role_import_preview_test.dart`, `client/test/assistant/role_import_plan_test.dart`, `client/test/api/role_import_plan_api_test.dart`.

Tests: `role_import_plan_test.dart` 8 passed; `role_import_preview_test.dart` 5 passed; `role_import_plan_api_test.dart` 3 passed; `assistant_action_plan_test.dart` 26 passed; 0 failed. `flutter analyze` of the five changed Dart files reports one pre-existing warning at `assistant_screen.dart:662` and no new issue. `test_rel1d_role_import_batch.py` 37 passed, 0 failed. Backend code was not changed. `git diff --check` clean.

Schema head remains `0054`. Production and the installed client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`, Alembic `0054 / 0054`, health PASS. No deploy, migration, client install, model call, provider call, or production-data change.

REL1D-C1 `3d3bead03271bad5dfc5713eaf78a4d1062cb11e` and REL1D-C1.1 `5cb4fd7400c8e095b6949e25eac0d1afc7b9fa51` are Architect source-accepted. With this client confirmation path, REL1D is source-complete. A rollout is not authorized from this HOLD.
