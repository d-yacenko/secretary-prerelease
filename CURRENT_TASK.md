# CURRENT_TASK

## Status

HOLD

## REL1D-C1.2

Implemented at `693ca6bacf8af089529ff17d7bc3d103c7f940e4`.

Public views of `apply_role_import_batch` expose `arguments: {}` and the already frozen safe presentation. The stored ActionPlan still contains the exact canonical payload, including `promotion_candidate_key`, and approved execution reads that stored payload. Approve and reject responses keep the same presentation. Ordinary ActionPlan arguments stay public except the existing hidden keys.

Files: `backend/app/services/action_plan_service.py`, `backend/app/api/assistant.py`, `backend/tests/test_rel1d_role_import_batch.py`.

Tests: `test_rel1d_role_import_batch.py`, `test_assistant_action_plans.py`, and `test_ah2_ap1_approval_presentation.py` together 96 passed, 0 failed. Ruff passed. `py_compile` passed. `git diff --check` clean. Client fixtures were not changed.

Schema head remains `0054`. Production and the installed client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`, Alembic `0054 / 0054`, health PASS. No deploy, migration, client install, model call, provider call, or production-data change.

REL1D-C2.1 `6eac184a0b45ee4ddb6f1ccee457e622c8283bf3` is Architect source-accepted. REL1D still awaits final Architect review. A rollout is not authorized.
