# Current task — HOLD

REL1A.2.1 is implemented and waiting for Architect review. Do not deploy, migrate production, install the client, or start REL1B, REL1C, or REL1D from this HOLD.

## REL1A.2.1 — query-bound role autocomplete

- Implementation: `783d574264239b868a5fae9644cd76b00ad38236`
- Alembic head remains `0054`
- Backend and schema were not changed
- Production remains `2314bf72101fbd83d50a7b264154d73740e28db1`
- Production Alembic remains `0052 / 0052`
- Installed Linux client source remains `2314bf72101fbd83d50a7b264154d73740e28db1`

## Changed files

- `client/lib/graph/person_roles_section.dart`
- `client/test/graph/person_roles_section_test.dart`

## Client state

Changing the role text immediately clears the previous suggestions and exact-match result. While the current query is waiting for the server, `Создать роль «…»` is hidden and the previous terms are not shown. The create action appears only when the current collapsed text is non-empty, that query has a completed server result, and `exact_match_term_id` is null. An older response cannot publish terms or exact-match state after a newer query. A failed search stays cleared and does not restore the previous query. The server remains the lexical-identity authority.

## Checks

- Flutter `person_roles_section_test.dart`, `people_overview_test.dart`, `people_create_test.dart`: 21 passed, 0 failed
- `flutter analyze` of `person_roles_section.dart`: no issues
- `flutter build linux --debug`: succeeded, not installed
- `git diff --check`: clean

Model calls: 0. No production deploy. No production migration. No client install.

## HOLD

Do not start role-aware importance, Assistant role writes, screenshot import, Organization, Scheduled Activity, deployment, or client installation.
