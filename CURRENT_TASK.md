# Current task

HOLD

Graph Refined P5R2 effective-identity and scan correction is implemented at `ad3c1377c1afcd3537b692175728cc3187bea88b`.

An explicit rejection suppresses that identity's display alias. The Person title still resolves. Confirmation or retraction restores the alias. Person communication and identity-candidate reads page through unrelated messages up to a fixed budget and report truncation when the budget ends first.

Focused checks: `tests/test_person_assistant.py` 36 passed; `tests/test_person_enrichment.py` 20 passed; `tests/test_person_salience.py` 9 passed; `tests/test_person_evidence_ledger.py` 6 passed; `tests/test_person_identity.py` 12 passed; `tests/test_tool_gateway.py` 28 passed. Combined run: 111 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No migration. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.

Do not start P6. Do not deploy.
