# CURRENT_TASK

## Status

HOLD

## Completed

REL1D-B.1 extraction completeness through grounding and stale-retry fence.

Implementation: `baf1362493eaab5b81680c0f747664d1c432699d`

Changed files:

- `backend/app/services/person_role_import_grounding_service.py`
- `backend/tests/test_rel1d_role_import_grounding.py`
- `client/lib/api/role_import_models.dart`
- `client/lib/api/secretary_api_client.dart`
- `client/lib/assistant/assistant_controller.dart`
- `client/lib/assistant/role_import_preview.dart`
- `client/test/assistant/role_import_preview_test.dart`

Grounding requires `items_truncated` and keeps that flag in the response and in `grounding_revision`. The client model keeps source kind, source truncation, and items truncation. A stale source hides `Сопоставить` and blocks another grounding request until re-extraction.

Tests: grounding 22, source 23, extraction 14, together 59 passed, 0 failed. Flutter `role_import_preview_test.dart` 5 passed, 0 failed.

Schema head remains Alembic `0054`.

Production backend/source and the installed Linux client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`. Alembic `0054 / 0054`. No deploy, migration, client install, real model call, provider call, or production data mutation.

REL1D-C was not started.

## Next

No Executor work is authorized from this HOLD.
