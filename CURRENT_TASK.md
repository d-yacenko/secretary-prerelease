# Current task — HOLD

## REL1C-B — approval-gated Assistant Person-role add/retract

Implementation: `22a4ac91e52bc3097e8945dc3223fdc0adaa7ba9`.

Changed files:

- `backend/app/services/person_role_service.py`
- `backend/app/services/person_role_assistant_service.py`
- `backend/app/services/domain_tool_service.py`
- `backend/app/tools/schemas.py`
- `backend/app/tools/assistant_contracts.py`
- `backend/app/tools/registry.py`
- `backend/app/assistant/reference_ids.py`
- `backend/app/assistant/tool_runner.py`
- `backend/app/assistant/approval_presentation.py`
- `backend/app/assistant/execution_effects.py`
- `backend/app/llm/openai_assistant_provider.py`
- `backend/tests/test_rel1c_assistant_role_writes.py`
- `backend/tests/test_rel1c_assistant_role_reads.py`
- `backend/tests/test_tool_gateway.py`
- `backend/tests/test_h2d_task_mcp_parity.py`
- `docs/ontology_harness_parity_audit.md`

- `assign_person_role` is `INTERNAL_WRITE` and `retract_person_role` is `DESTRUCTIVE_INTERNAL_WRITE`. Both require ActionPlan approval and a same-turn resolved Person.
- An existing RoleTerm is reused only from an exact id exposed this turn. A new term is staged only after a no-exact lookup of the same lexical key. Suggestions are not substitutes.
- A new Assistant assignment records `origin=agent` and `assistant_action_plan`. An already active manual assignment stays manual.
- Approval cards show the Person title, role, context, and reuse or create mode. `changed=false` is a no-op in finalization.
- Schema head remains `0054`.
- Tests: `test_rel1c_assistant_role_writes.py` 9 passed, 0 failed. `test_rel1c_assistant_role_reads.py` 12 passed, 0 failed. `test_person_assistant.py` 36 passed, 0 failed. `test_assistant_action_plans.py` 45 passed, 0 failed. `test_tool_gateway.py` 28 passed, 0 failed. `test_ah1_doc_registry_drift.py` 4 passed, 0 failed. `test_h2d_task_mcp_parity.py` 5 passed, 0 failed. `test_ah2_ap1_approval_presentation.py` 13 passed, 0 failed. `test_rel1a_person_roles.py` 18 passed, 0 failed. `test_rel1b_person_role_relevance_evidence.py` 16 passed, 0 failed. `test_rel1b_task_context_relevance.py` 17 passed, 0 failed. `test_workflow_intelligence_proactive_personalization_e_c.py` 46 passed, 0 failed. `test_ah2_sem1_relation_boundary.py` 4 passed, 0 failed. Focused instruction and finalization tests 36 passed, 0 failed.
- Production backend/source and the installed Linux client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`.
- Production Alembic remains `0054 / 0054`.
- No deploy, migration, client install, model call, provider call, or product-data action.
- REL1D was not started.

Do not deploy or start the next slice from HOLD.
