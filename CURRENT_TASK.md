# Current task

HOLD. Graph Refined P3R3 salience candidate dedupe and scoring consistency is implemented at `34d96e4b66b4eb92aceb8b0aebac96d635fd9c5c`.

Attention and task/calendar bounds now count distinct People. A Person is kept by its best feedback row: explicit confirmation before route choice, then newer feedback, with a stable tie-break. A Person is kept by its newest active task or calendar edge. Extra rows for someone already selected do not consume the bound. Truncation means there are more distinct eligible People than the bound.

Scoring uses that same set. Attention flags and task/calendar links are computed for every Person in the pool, so a Person admitted for confirmation or a task link still receives that component when other People have many rows. `rank()` still returns at most `MAX_RANKED_PEOPLE`. The communication scan is unchanged. No migration. `claims_object_importance` remains false.

`tests/test_person_salience.py`: 9 passed. `tests/test_person_evidence_ledger.py`: 6 passed. `tests/test_person_identity.py`: 12 passed. Combined focused run: 27 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No P4, UI, proactive, Assistant, or Task Graph integration, and no live provider/LLM call. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`. `origin/production` was not moved.

Do not choose or start the next phase.
