# CURRENT_TASK

## Status

HOLD

## Completed

REL1D-B deterministic grounding-only batch proposal.

Implementation: `c0599932a9c917e0efde51d237d8cb3df79c5a88`

Changed files:

- `backend/app/services/person_role_import_grounding_service.py`
- `backend/app/services/person_promotion_service.py`
- `backend/app/domain/person_promotion.py`
- `backend/app/api/routes/role_import.py`
- `backend/tests/test_rel1d_role_import_grounding.py`
- `client/lib/api/role_import_models.dart`
- `client/lib/api/secretary_api_client.dart`
- `client/lib/assistant/assistant_controller.dart`
- `client/lib/assistant/assistant_screen.dart`
- `client/lib/assistant/role_import_preview.dart`
- `client/test/assistant/role_import_preview_test.dart`

`POST /people/role-import/ground` revalidates the source revision, reuses Person resolution, offers exact-display promotion candidates only when the resolver returns none, and reuses an exact RoleTerm or proposes a new one. `grounding_revision` tracks those facts. Nothing is stored and no model is called. The client grounds only from an explicit `Сопоставить` action and still says `Ничего не сохранено`.

Tests: grounding 21; source 23; extraction 14; PER1 13; promotion 25; REL1A 18; REL1C reads 12; REL1C writes 9. Together 135 passed, 0 failed. Flutter `role_import_preview_test.dart` 5 passed, 0 failed.

Schema head remains Alembic `0054`.

Production backend/source and the installed Linux client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`. Alembic `0054 / 0054`. No deploy, migration, client install, real model call, provider call, or production data mutation.

REL1D-C was not started.

## Next

No Executor work is authorized from this HOLD.
