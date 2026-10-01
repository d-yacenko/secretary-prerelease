# Current task — HOLD

AH2-P prompt semantic routing is implemented and awaiting a separate rollout plus human/model verification.

- Implementation: `3c463014d38433523f7196a9682b2b7324d94b15`
- `SYSTEM_INSTRUCTIONS` now names `requested_by`, `delegated_to`, `waiting_on`, and `involves` as typed Task-to-Person facts, not `related_to`.
- `part_of` is child → parent composition. `depends_on` is a prerequisite and is not composition.
- Removable semantic edges, including `depends_on`, `part_of`, and actor roles, are removed by `list_neighbors`, the exact `edge.id`, and `remove_relation`. Omitting an additive `update_task` id is not removal.
- Tests: 31 passed (`test_assistant_ontology_kernel.py`, `test_ah1_doc_registry_drift.py`, `test_domain_tools.py`, `test_task_relations.py`). Static prompt text only. Model behavior is not proven.
- Tool schemas, domain services, API, UI, and migrations were not changed.
- Production was not deployed and remains `0719e9bf5af75a8065a9916d8e27c0247a3921ec`, Alembic `0052 / 0052`.
- Rollout and human/model verification are pending.

Do not start AH2-D, AH2-T, AH2-E, AH2-M, or AH2-C.
