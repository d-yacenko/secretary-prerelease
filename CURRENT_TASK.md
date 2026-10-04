# CURRENT_TASK

## Status

HOLD

## REL1D-C1.1

Implemented at `5cb4fd7400c8e095b6949e25eac0d1afc7b9fa51`.

`apply_role_import_batch` no longer has a generic prepare path. `TOOL_REGISTRY["apply_role_import_batch"].prepare_method is None`. `DomainToolService.prepare_apply_role_import_batch` is gone. The tool stays `INTERNAL_WRITE`, `assistant_exposed=false`, `mcp_exposed=false`, with no Assistant definition. Approved execution still uses `ApplyRoleImportBatchCanonicalInput`. The only prepare path is `POST /people/role-import/action-plan`.

Representation mutations that can change role-import source text now lock the owning Object row first: `RepresentationService._replace_representations`, `ClientRepresentationPersistence.replace_for_object`, `ClientRepresentationPersistence.delete_all_for_object`, and mechanical full/chunk replace/clear. While an approved batch holds a body-fallback source, a first full/chunk insert, text ingest, and representation delete wait on that lock and do not commit. After the batch transaction releases, a normal representation write succeeds. Reads stay unlocked.

Files: `backend/app/tools/registry.py`, `backend/app/services/domain_tool_service.py`, `backend/app/services/representation_service.py`, `backend/app/services/client_representation_service.py`, `backend/app/content_extraction/mechanical_persistence.py`, `backend/app/content_extraction/extract_service.py`, `backend/app/content_extraction/content_invalidation.py`, `backend/app/services/web_content_invalidation.py`, `backend/app/services/web_explicit_link_intake_service.py`, `backend/tests/test_rel1d_role_import_batch.py`.

Tests: `test_rel1d_role_import_batch.py` 37 passed, 0 failed. Grounding, source, representations, client intake, tool gateway, ActionPlan, REL1C writes, REL1B personalization concurrency, and mechanical xlsx persistence together 258 passed and 1 failed. The failure is `test_deleting_object_cascades_representations`: it expects zero Representation rows in the shared database and found 3 pre-existing committed rows for `race-*.txt`. Those rows were not created or deleted by this slice. Ruff passed. `py_compile` passed. `git diff --check` clean.

Schema head remains `0054`. Production and the installed client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`, Alembic `0054 / 0054`, health PASS. No deploy, migration, client install, model call, or provider call.

REL1D-C1 remains pending Architect acceptance until this corrective is reviewed. REL1D-C2 was not started.
