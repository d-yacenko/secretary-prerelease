# Current task

HOLD. Graph Refined P3R2 salience ranking-pool integrity is implemented at `37130c3468418fefa2231094d7b28ced5415bd42`.

`rank()` scores a bounded candidate pool and returns at most `MAX_RANKED_PEOPLE`. The pool is the union of three sources:

- exact identities referenced by the bounded 90-day communication scan, so a newer Person is not hidden behind older identity rows;
- active P2 attention, with explicit confirmation ordered before route choice and newer feedback first, bounded by `MAX_ATTENTION_CANDIDATES`;
- active edges from an active Person to an active task or calendar object, newest first, bounded by `MAX_TASK_CANDIDATES`. Unrelated edges do not fill that bound.

If a source is truncated, the salience result says so. Rejected, deleted, and cross-user People stay out. `evaluate()` keeps the existing scan and per-Person hit caps. No migration. `claims_object_importance` remains false.

`tests/test_person_salience.py`: 8 passed. `tests/test_person_evidence_ledger.py`: 6 passed. `tests/test_person_identity.py`: 12 passed. Combined focused run: 26 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No P4, UI, proactive, Assistant, or Task Graph integration, and no live provider/LLM call. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`. `origin/production` was not moved.

Do not choose or start the next phase.
