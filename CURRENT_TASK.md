# CURRENT_TASK

## Status

HOLD

## Completed

REL1D-A source intake and proposal-only role extraction.

Implementation: `d1d4708d7e491131d81ced19de4495bef0c0ddc5`

Changed files:

- `backend/app/resources/constants.py`
- `backend/app/resources/raster_signatures.py`
- `backend/app/resources/upload_staging.py`
- `backend/app/services/resource_registration_service.py`
- `backend/app/services/person_role_import_source_service.py`
- `backend/app/services/person_role_import_extraction_service.py`
- `backend/app/llm/openai_role_import_provider.py`
- `backend/app/api/routes/role_import.py`
- `backend/app/main.py`
- `backend/app/ai_audit/constants.py`
- `backend/tests/test_rel1d_role_import_source.py`
- `backend/tests/test_rel1d_role_import_extraction.py`
- `client/lib/api/secretary_api_client.dart`
- `client/lib/api/role_import_models.dart`
- `client/lib/assistant/assistant_controller.dart`
- `client/lib/assistant/assistant_screen.dart`
- `client/lib/assistant/role_import_preview.dart`
- `client/lib/local/extraction/extraction_constants.dart`
- `client/lib/local/local_intake_actions.dart`
- `client/test/assistant/role_import_preview_test.dart`

Schema head remains Alembic `0054`. No migration was added.

Tests: REL1D-A backend 33 passed, 0 failed. Flutter preview 4 passed. Local intake and privacy 12 passed, 0 failed. Ruff passed. `py_compile` passed. `git diff --check` clean. Focused Dart analyze added no new issue.

The combined resource, client-intake format parity, REL1A, REL1C-A, REL1C-B, and AI-audit run was 115 passed and 4 failed. Those 4 also fail with the pre-REL1D-A registration service: `test_register_same_revision_already_ingested_skips_content`, `test_register_long_text_chunks_embedded_by_worker_and_ranked_in_context`, `test_metadata_only_upload_persisted_for_later_ingest`, and `test_mixed_workload_summary_metrics`.

Production backend/source and the installed Linux client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`. Alembic `0054 / 0054`. No deploy, migration, client install, real model call, provider call, or production data mutation.

REL1D-B and REL1D-C were not started.

## Next

No Executor work is authorized from this HOLD.
