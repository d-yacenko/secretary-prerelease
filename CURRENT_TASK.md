# Current task — HOLD

## REL1C-A — Assistant read-only Person role queries

Implementation: `ab6b05c84982275f443faa7877e189ddd6d9c34c`.

Changed files:

- `backend/app/services/person_role_assistant_service.py`
- `backend/app/services/domain_tool_service.py`
- `backend/app/tools/schemas.py`
- `backend/app/tools/assistant_contracts.py`
- `backend/app/tools/registry.py`
- `backend/app/assistant/tool_runner.py`
- `backend/app/assistant/tool_output.py`
- `backend/app/assistant/reference_ids.py`
- `backend/app/llm/openai_assistant_provider.py`
- `backend/tests/test_rel1c_assistant_role_reads.py`
- `backend/tests/test_tool_gateway.py`
- `backend/tests/test_h2d_task_mcp_parity.py`
- `backend/tests/test_person_assistant.py`
- `docs/ontology_harness_parity_audit.md`

- `get_person_roles` reads active roles only after `resolve_person` returns `state=resolved` for that Person in the same turn.
- `find_people_by_role` returns people for an exact lexical RoleTerm. Suggestions are nearby vocabulary, not matches, and do not resolve a Person.
- At most 16 roles per Person and at most 12 people per query. Model-visible output stays within 12000 characters and omits normalized keys, provenance, and raw identities.
- Schema head remains `0054`.
- Tests: `test_rel1c_assistant_role_reads.py` 12 passed, 0 failed. `test_person_assistant.py` 36 passed, 0 failed. `test_tool_gateway.py` 28 passed, 0 failed. `test_ah1_doc_registry_drift.py` 4 passed, 0 failed. `test_rel1a_person_roles.py` 18 passed, 0 failed. `test_rel1b_person_role_relevance_evidence.py` 16 passed, 0 failed. `test_rel1b_task_context_relevance.py` 17 passed, 0 failed. `test_ah2_sem1_relation_boundary.py` 4 passed, 0 failed. `test_h2d_task_mcp_parity.py` 5 passed, 0 failed. Focused instruction tests 43 passed, 0 failed: selected-Task waiting 6, ontology kernel 3, untrusted prompt boundary 3, name variants 13, exact object email reply 18.
- Production backend/source and the installed Linux client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`.
- Production Alembic remains `0054 / 0054`.
- No deploy, migration, client install, model call, provider call, or product-data action.
- REL1C-B and REL1D were not started.

Do not deploy or start the next slice from HOLD.
