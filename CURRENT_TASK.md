# Current task

HOLD

Graph Refined P4 bounded identity enrichment orchestration is implemented at `a0bfa2bc256cae628d492bce0a3562f624e48b76`.

The planner uses stored communication facts, exact identities, P2 evidence, and P3 salience. It does not call providers or models, does not create People for unknown senders, and does not merge People. Display-name similarity stays `needs_confirmation`. An exact attach happens only when that identity already belongs to the Person or explicit `user_confirmed` evidence authorizes it. A conflicting owner fails closed. Missing provider categories are reported and left for a later lookup.

Focused checks: `tests/test_person_enrichment.py` 12 passed; `tests/test_person_salience.py` 9 passed; `tests/test_person_evidence_ledger.py` 6 passed; `tests/test_person_identity.py` 12 passed; combined 39 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No migration. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.

Do not start P5. Do not deploy.
