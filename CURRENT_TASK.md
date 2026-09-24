# Current task

HOLD. Graph Refined P2 explainable identity evidence and candidate scoring is implemented at `b94a56a19c891f31a6f6c8d6964ba6c905d7719e`.

Migration `0049` adds `person_identity_evidence`. Evidence is user-scoped, targets a Person, and stores the candidate identity tuple. Corrections retract the prior row instead of rewriting it. Deleting a source communication object sets `source_object_id` to null and keeps the evidence row. Provider secrets are rejected.

The score is derived from active rows. Explicit confirmation yields `confirmed`. An active rejection yields `rejected` and suppresses weaker positive evidence. Route choice raises the score and stays below `confirmed`. Name similarity alone stays below the automatic-link threshold and never yields `confirmed`. The same provenance key does not add the score twice. Contradictory rows stay visible in the components. The same candidate can score differently for two People.

Candidate helpers resolve an existing exact identity and propose name overlap from Person titles and identity display values. They do not create People, attach identities, or merge anyone.

`tests/test_person_evidence_ledger.py`: 4 passed, including `0048 <-> 0049`. `tests/test_person_identity.py`: 12 passed. Combined focused run: 16 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No P3 work, UI, Assistant lookup, send-by-person, or live provider/LLM call. Migrations `0048` and `0049` were not applied in production. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`. `origin/production` was not moved.

Do not choose or start the next phase.
