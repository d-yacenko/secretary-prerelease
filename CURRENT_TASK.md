# Current task — HOLD

## REL1B-B — confirmed active Task context + model-visible role-aware Personal Relevance

Implementation: `362c4fb2a10dbb557bf58c01acd1075c1dae4417`.

Changed files:

- `backend/app/personal_relevance/models.py`
- `backend/app/personal_relevance/related_tasks.py`
- `backend/app/services/personal_relevance_evidence_service.py`
- `backend/app/services/proactive_review_service.py`
- `backend/app/proactive/instructions.py`
- `backend/app/services/task_relation_service.py`
- `backend/app/services/graph_service.py`
- `backend/tests/test_rel1b_task_context_relevance.py`
- `backend/tests/test_rel1b_person_role_relevance_evidence.py`
- `backend/tests/test_workflow_intelligence_personal_relevance_e_b.py`
- `backend/tests/test_workflow_intelligence_proactive_personalization_e_c.py`

- Personal Relevance evidence version is `3`.
- Schema head remains `0054`.
- Object evidence now includes bounded confirmed active Task actor context: at most 8 Tasks, UUID order, confirmed actor links only.
- The Proactive seed receives bounded grounded Person roles and that Task context: 4 People, 4 roles, and 4 Tasks per seed object. Role terms are evidence, not weights or a ranking.
- Authority locks the initial snapshot's related Task rows. Task actor writes, including low-level actor-edge mutations, take the user serialization gate.
- Tests: REL1B-B, REL1B-A, REL1A, personal-relevance E-B, Person identity, and the consolidation identity/role move test together 101 passed, 0 failed. Task relations, SEM1, and Person consolidation together 30 passed, 0 failed. Proactive personalization E-C 46 passed, 0 failed. Proactive secretary 63 passed, 0 failed.
- Production backend/source and the installed Linux client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`.
- Production Alembic remains `0054 / 0054`.
- No deploy, migration, client install, model call, provider call, or product-data action.
- REL1C and REL1D were not started.

Do not deploy or start the next slice from HOLD.
