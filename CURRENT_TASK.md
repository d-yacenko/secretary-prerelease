# Current task

HOLD. Graph Refined P2R evidence ownership and active-candidate safety is implemented at `feaa7becb4b006057f2276a53b22a357c9a34891`.

A `person_identity_id` on new evidence must belong to the same Secretary user, the same target Person, and the same identity tuple, and the identity must be active. A link to another Person, a tuple mismatch, or a rejected identity fails closed. After detach, the existing evidence row stays readable and is not rewritten. A new link to that rejected identity is refused.

Exact resolution returns no Person when that Person is rejected or deleted. Name candidates use only active People and active identity display values whose Person is also active. Historical rows are not deleted. Migration `0049` is unchanged.

`tests/test_person_evidence_ledger.py`: 6 passed. `tests/test_person_identity.py`: 12 passed. Combined focused run: 18 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No P3, Person salience, UI, Assistant lookup, auto-merge, auto-attach, or send-by-person. Migrations `0048` and `0049` were not applied in production. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`. `origin/production` was not moved.

Do not choose or start the next phase.
