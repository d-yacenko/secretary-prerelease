# Current task

HOLD

Graph Refined P5R Person safety correction is implemented at `29380e031071a12f097cae1ad3d1fa0467679b98`.

Exact Person resolution keeps an active rejection from resolving that identity and keeps a conflicting confirmation explicit. `find_person_communications` requires a Person resolved in the same turn. Retrieval includes the safely attributable outbound side for email, private Telegram, and anchored one-to-one chats. `find_person_identity_candidates` exposes a real source-derived identity for same-turn confirmation or rejection and does not attach it.

Focused checks: `tests/test_person_assistant.py` 29 passed; `tests/test_person_enrichment.py` 19 passed; `tests/test_person_salience.py` 9 passed; `tests/test_person_evidence_ledger.py` 6 passed; `tests/test_person_identity.py` 12 passed; `tests/test_tool_gateway.py` 28 passed. Combined run: 103 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No migration. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.

Do not start P6. Do not deploy.
