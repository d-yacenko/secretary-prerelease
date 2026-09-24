# Current task

HOLD

Graph Refined P4R confirmation-conflict safety is implemented at `f6f255ea4fbd0e873afdab29297a88a50d2abbab`.

Several active `user_confirmed` rows for one identity are an explicit conflict. The planner does not attach and does not treat those confirmations as missing. Existing ownership stays unchanged. One remaining active confirmation still authorizes an exact attach. Rejected, deleted, and cross-user confirmations do not count. The evidence ledger is not rewritten.

Focused checks: `tests/test_person_enrichment.py` 19 passed; `tests/test_person_salience.py` 9 passed; `tests/test_person_evidence_ledger.py` 6 passed; `tests/test_person_identity.py` 12 passed; combined 46 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No migration. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.

Do not start P5. Do not deploy.
