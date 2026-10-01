# Current task — HOLD

AH2-D Task tool description parity is implemented. Rollout is pending.

- Implementation: `cb941776d318bbddf50d536a785cee3ab7e1822e`
- `get_task_profile` description now names lifecycle status, `completion_mode`, confirmed `parent_task`, the four actor roles, dependencies, the readable planned interval, evidence, and read-only operational state. The tool still does not mutate.
- `create_task` and `update_task` share field descriptions for the four actor roles, prerequisite `depends_on_task_ids`, and additive `evidence_object_ids`.
- Property names and required sets are unchanged. Planned interval remains readable and not writable.
- Tests: 37 passed. Contract text only. Model behavior stays unverified until AH2-M.
- Schema, domain, API, UI, prompt, and production were not changed.
- Production remains `0719e9bf5af75a8065a9916d8e27c0247a3921ec`, Alembic `0052 / 0052`.

Do not start AH2-T, AH2-E, AH2-M, or AH2-C.
