# Current task — HOLD

No implementation task is authorized.

Graph Refined P1, canonical Person + provider identities, is complete.

Implementation SHA: `3c773db48b8bc0f27a0f6896f94295bfbc5781b1`

Files changed:
- `backend/alembic/versions/0048_person_identities.py`
- `backend/app/db/models.py`
- `backend/app/domain/person_identity.py`
- `backend/app/domain/person_identity_evidence.py`
- `backend/app/services/person_identity_service.py`
- `backend/tests/test_person_identity.py`

A Person is a user-owned Object with `kind="person"`. Exact provider identities link deterministically. Display names are not merge keys. Conflicting exact identities return `person_identity_conflict`.

Focused checks: `tests/test_person_identity.py` 10 passed, including migration `0048` downgrade to `0047` and upgrade back to head. Ruff and Python compile of touched files passed. `git diff --check` clean.

No fuzzy matching, Graph UI, or send-by-person. No live provider/LLM call. Migration `0048` was not applied in production. No production deploy. Telegram MTProto AI activation/quarantine unchanged.

Production remains `296b4735f9473ea60ef22f1827ed94260603128e`. Alembic remains `0047 / 0047`.
