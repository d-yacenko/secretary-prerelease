# Current task — HOLD

REL1A.1 is implemented and waiting for Architect review. Do not deploy, migrate production, install the client, or start REL1B, REL1C, or REL1D from this HOLD.

## REL1A.1 — preserve Person roles through consolidation

- Implementation: `9de2cccd218b76c04e98049b7bcc86c36a4058fe`
- Schema head remains Alembic `0053`
- No new migration
- Production remains `2314bf72101fbd83d50a7b264154d73740e28db1`
- Production Alembic remains `0052 / 0052`
- Health remains PASS

## Changed files

- `backend/app/services/person_consolidation_service.py`
- `backend/app/services/person_role_service.py`
- `backend/app/api/schemas.py`
- `backend/app/api/routes/graph_workspace.py`
- `backend/tests/test_person_consolidation.py`
- `backend/tests/test_rel1a_person_roles.py`
- `client/lib/api/api_models.dart`
- `client/test/graph/person_roles_section_test.dart`

## Merge and undo

An active duplicate assignment is copied onto the survivor only when that survivor does not already have the same `role_term_id` and `context_key`. The copy keeps context text, origin, provenance, and `source_object_id`. No new RoleTerm and no graph edge are created. The duplicate's original row is left unchanged.

The same role and context on both people produces no second survivor row. Different contexts stay as separate active assignments. If the distinct result would exceed 16 active assignments, preview and apply fail before Person, identity, or role mutation.

The merge audit records each created survivor assignment and the pre-existing semantic keys. Undo retracts only the created rows. It fails closed when a created row is missing, belongs to someone else, is no longer active, or no longer matches the audited fields. A survivor assignment that existed before the merge is not retracted. After undo, the duplicate's original roles are visible again. Applying an already established merge does not create another assignment.

`person_id` is present on POST assignment, DELETE retract, and the People workspace projection. Public retract requires an active current-user Person. A rejected, deleted, or merged-away Person returns 422 and is not mutated. A cross-user or mismatched assignment stays 404.

## Checks

- `test_person_consolidation.py` and `test_rel1a_person_roles.py`: 30 passed
- those two with person workspace, identity, identity review, promotion, SEM1, task relations, and task layout: 119 passed
- Flutter `person_roles_section_test.dart`, `people_overview_test.dart`, `people_create_test.dart`: 16 passed
- `flutter analyze` of the four role client files: 0 errors, 7 pre-existing infos on `graph_workspace_screen.dart`
- `flutter build linux --debug`: succeeded, not installed
- Ruff: passed
- `git diff --check`: clean

Model calls: 0. No production deploy. No production migration. No client install.

## HOLD

Do not start role-aware importance, Assistant role writes, screenshot import, Organization, Scheduled Activity, deployment, or client installation.
