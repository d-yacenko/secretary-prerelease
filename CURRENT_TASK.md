# Current task — HOLD

REL1A.2 is implemented and waiting for Architect review. Do not deploy, migrate production, install the client, or start REL1B, REL1C, or REL1D from this HOLD.

## REL1A.2 — Unicode lexical-identity hardening

- Implementation: `5b2e19c8f386225c262be4b3a551096f0427d6fc`
- Alembic head: `0054`
- Down revision: `0053`
- `0053` was not rewritten
- Production remains `2314bf72101fbd83d50a7b264154d73740e28db1`
- Production Alembic remains `0052 / 0052`
- Installed Linux client source remains `2314bf72101fbd83d50a7b264154d73740e28db1`

## Changed files

- `backend/alembic/versions/0054_person_role_key_width.py`
- `backend/app/db/models.py`
- `backend/app/domain/person_role_text.py`
- `backend/app/services/person_role_service.py`
- `backend/app/api/schemas.py`
- `backend/app/api/routes/graph_workspace.py`
- `backend/tests/test_rel1a_person_roles.py`
- `backend/tests/test_task_layout.py`
- `client/lib/api/api_models.dart`
- `client/lib/api/secretary_api_client.dart`
- `client/lib/graph/person_roles_section.dart`
- `client/test/graph/person_roles_section_test.dart`

## Schema and exact match

`normalized_key` is VARCHAR(360). `context_key` is VARCHAR(600). Display text stays at most 120, context text at most 200. Unique user/key and active assignment uniqueness are unchanged. Downgrade restores the `0053` widths for compatible rows and raises instead of truncating a longer key.

Case-fold still uses Unicode `casefold()`. A folded key that would exceed 360 or 600 is a validation error before persistence. A 120-character `ß` role stores `ss` repeated 120 times. A 200-character `ß` context stores the full 400-character key and repeats as the same assignment. `Straße` and `STRASSE` are one term. `директор` and `генеральный директор` stay distinct.

Search returns `exact_match_term_id` for the current user's canonical key. The id is present even when the bounded page does not include that term. Empty and unmatched queries return null.

The add-role dialog shows `Создать роль «…»` only when the server exact-match id is null. It does not decide equality with `toLowerCase()`. A completed search for older text cannot change the exact-match state of newer text.

Role vocabulary, the 16-role cap, retract, consolidation copy/undo, workspace projection, Task actor relations, and Person identity matching are unchanged. No role graph edge was added.

## Checks

- role, consolidation, workspace, identity, identity review, promotion, SEM1, task relations, and task layout: 124 passed, 0 failed
- Flutter `person_roles_section_test.dart`, `people_overview_test.dart`, `people_create_test.dart`: 17 passed, 0 failed
- `flutter analyze` of the four role client files: 0 errors, 7 pre-existing infos on `graph_workspace_screen.dart`
- `flutter build linux --debug`: succeeded, not installed
- Ruff: passed
- `git diff --check`: clean

Model calls: 0. No production deploy. No production migration. No client install.

## HOLD

Do not start role-aware importance, Assistant role writes, screenshot import, Organization, Scheduled Activity, deployment, or client installation.
