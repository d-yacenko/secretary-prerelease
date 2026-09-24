# Current task

HOLD. Graph Refined P3 Person salience foundation is implemented at `3402cb2f450a036efc6ce4a6415441b43947a31e`.

Salience is computed when read, for existing active People only. It uses active exact identities. Unknown senders do not become People. Display-name matching is not used.

The score is bounded and explainable: direct 1:1 contact, reciprocity, capped frequency, recency buckets, capped public or group exposure, P2 route choice, durable explicit confirmation, and an existing task or calendar edge. A noisy public-channel author stays below a less frequent direct reciprocal contact. Confirmation alone does not reach the focus tier and does not mark content as important. The result sets `claims_object_importance` to false.

Rejected or deleted People and rejected identities contribute nothing. Another user's messages and People are invisible. The communication read is limited to 90 days and 40 rows. No migration was added. Proactive notifications, Task Graph, Inbox order, and Assistant behavior are unchanged.

`tests/test_person_salience.py`: 4 passed. `tests/test_person_evidence_ledger.py`: 6 passed. `tests/test_person_identity.py`: 12 passed. Combined focused run: 22 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No P4, UI, auto-enrichment, or live provider/LLM call. Migrations `0048` and `0049` were not applied in production. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`. `origin/production` was not moved.

Do not choose or start the next phase.
