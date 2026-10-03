# Current task — HOLD

REL1A is implemented and waiting for Architect review. Do not deploy, migrate production, install the client, or start REL1B, REL1C, or REL1D from this HOLD.

## REL1A — emergent Person role vocabulary + manual assignments

- Implementation: `e7f1e79dd83e3007bc97a6dff7aa1bd083128d93`
- Migration: Alembic `0053`, down revision `0052`
- Production remains `2314bf72101fbd83d50a7b264154d73740e28db1`
- Production Alembic remains `0052 / 0052`
- Health remains PASS

## Changed files

- `backend/alembic/versions/0053_person_role_vocabulary.py`
- `backend/app/db/models.py`
- `backend/app/domain/person_role_text.py`
- `backend/app/services/person_role_service.py`
- `backend/app/services/person_graph_workspace_service.py`
- `backend/app/api/schemas.py`
- `backend/app/api/routes/graph_workspace.py`
- `backend/tests/test_rel1a_person_roles.py`
- `backend/tests/test_task_layout.py`
- `client/lib/api/api_models.dart`
- `client/lib/api/secretary_api_client.dart`
- `client/lib/graph/person_roles_section.dart`
- `client/lib/graph/graph_workspace_screen.dart`
- `client/test/graph/person_roles_section_test.dart`

## Schema and normalization

`person_role_terms` is a per-user vocabulary: display text plus a normalized key, unique per user. `person_role_assignments` attaches one term to one Person, with optional context, `origin=user`, `state=active|retracted`, provenance `user_manual`, and a nullable `source_object_id` for a later import. The active uniqueness key is user, person, term, and context key.

Trim and collapse whitespace. Case-fold only the key. The first accepted display text stays. Exact forms such as `Директор`, ` директор `, and `ДИРЕКТОР` reuse one term. `директор` and `генеральный директор` stay distinct. There is no stemming, translation, edit distance, embedding, or synonym merge.

The same role without context and with `Arenadata` are different assignments. Context case and whitespace collapse only a trivial duplicate. Repeating an active assignment is idempotent. Retract keeps the row and the term. The active cap is 16; retract frees a slot.

## API and UI

`GET /graph/person-role-terms` returns a bounded lexical page for the current user. `POST /graph/people/{person_id}/roles` reuses or creates the term and the assignment together. `DELETE /graph/people/{person_id}/roles/{assignment_id}` retracts. People workspace includes active assignments from one batched query. Retracted rows are absent.

The rooted Person detail has a `Роли` section. Typing shows existing terms. `Создать роль «…»` appears only when the typed text is not an exact lexical match. Context is optional. Cards show the first two distinct role titles and an overflow count, without raw ids. A Person with no roles stays clean.

Disposable `0052 -> 0053 -> 0052 -> head` kept the Person and Task rows. Personal relevance, proactive ranking, Assistant tools, and MCP were not changed.

## Checks

- `test_rel1a_person_roles.py`: 12 passed
- that file with person workspace, identity, identity review, promotion, consolidation, SEM1, task relations, and task layout: 112 passed
- Flutter `person_roles_section_test.dart`, `people_overview_test.dart`, `people_create_test.dart`: 16 passed
- `flutter analyze` of the four changed client files: 0 errors, 7 pre-existing infos on `graph_workspace_screen.dart`
- `flutter build linux --debug`: succeeded, not installed
- Ruff on the new Python files: passed
- `git diff --check`: clean

Model calls: 0. No production deploy. No production migration. No client install.

## HOLD

Do not start role-aware importance, Assistant role writes, screenshot import, Organization, Scheduled Activity, deployment, or client installation.
