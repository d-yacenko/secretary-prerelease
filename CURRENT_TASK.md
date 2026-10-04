# CURRENT_TASK

## Status

HOLD

## REL1D-C1

Implemented at `3d3bead03271bad5dfc5713eaf78a4d1062cb11e`.

`POST /people/role-import/action-plan` reruns REL1D-B grounding and stores one pending ActionPlan whose only action is internal `apply_role_import_batch`. The tool is `INTERNAL_WRITE`, not Assistant-exposed, and not MCP-exposed. Approval revalidates the frozen source revision, Person or promotion target, and RoleTerm inside the existing ActionPlan savepoint, under the user serialization lock plus the source Object and used Representation locks. Reject, expiry, and any later-row failure write no Person or role facts. A new assignment uses `origin=user`, `provenance_kind=role_import_confirmed`, and `source_object_id`. An already active assignment does not rewrite prior provenance or source.

Files: `backend/app/services/person_role_import_batch_models.py`, `backend/app/services/person_role_import_batch_service.py`, `backend/app/services/person_role_import_source_service.py`, `backend/app/services/person_role_service.py`, `backend/app/services/domain_tool_service.py`, `backend/app/api/routes/role_import.py`, `backend/app/tools/registry.py`, `backend/app/assistant/approval_presentation.py`, `backend/app/assistant/execution_effects.py`, `docs/ontology_harness_parity_audit.md`, `backend/tests/test_rel1d_role_import_batch.py`, `backend/tests/test_tool_gateway.py`.

Tests: `test_rel1d_role_import_batch.py` 31 passed, 0 failed. Grounding, source, REL1A, REL1C writes, ActionPlan, tool gateway, Person promotion, REL1B evidence and task context, approval presentation, registry drift, and MCP parity together 225 passed, 0 failed. Ruff passed. `py_compile` passed. `git diff --check` clean.

Schema head remains `0054`. Production and the installed client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`, Alembic `0054 / 0054`, health PASS. No deploy, migration, client install, model call, or provider call.

REL1D-C2 was not started.
