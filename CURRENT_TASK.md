# Current task

HOLD

Graph Refined P5 Person-aware Assistant retrieval and reversible identity feedback is implemented at `59b54671ed0707c237bdf3d90d3eb70317ffc3eb`.

`resolve_person` returns one Person, an explicit ambiguity, or no candidate. Salience only orders the candidates. `find_person_communications` reads communications linked by active exact identities. Telegram content and Telegram identity summaries follow the existing AI gate. Confirmation, rejection, and retraction require a Person and identity already shown in the same turn. They do not merge People and do not send messages.

Focused checks: `tests/test_person_assistant.py` 15 passed; `tests/test_person_enrichment.py` 19 passed; `tests/test_person_salience.py` 9 passed; `tests/test_person_evidence_ledger.py` 6 passed; `tests/test_person_identity.py` 12 passed; `tests/test_tool_gateway.py` included. Combined run: 89 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No migration. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.

Do not start P6. Do not deploy.
