# Current task — HOLD

AH2-SEM1 is implemented and waiting for Architect review. Do not start the next slice from this HOLD.

## AH2-SEM1 — explicit unsupported-relation boundary

- Implementation: `2b52524dd3d0a4426f4c9fdf45759c7584a88497`
- AH2-STG1 remains ARCHITECT SOURCE-ACCEPTED at `10b1a53c4e017d84849b603ccb09af1142709903` (HOLD `3e2ad472ab51973d8782a1dc2a8f056e00895621`, ledger `a129e59fee612df99ef329bfbc9268f9604cac59`)
- Production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`
- Health remains PASS

## Changed files

- `backend/app/llm/openai_assistant_provider.py`
- `backend/app/tools/assistant_contracts.py`
- `backend/tests/test_ah2_sem1_relation_boundary.py`
- `backend/tests/test_ah2d_task_tool_descriptions.py`
- `backend/tests/test_ah2m_eval_runner.py`

## Closed-ontology instruction contract

Interactive instructions state that the Task relation vocabulary is closed.

Actor roles are only `requested_by`, `delegated_to`, `waiting_on`, and `involves`.

Generic `link_objects` relations are only `related_to`, `references`, `depends_on`, and `part_of`.

An unsupported requested relation must be described as not represented. The model may ask which supported meaning is intended. It must not approximate that request with `delegated_to`, `involves`, `related_to`, or any other supported relation, and it must not create, update, or link anything for it. Making a Task someone's manager is named as that case. No Russian sentence is hard-coded as the answer, and no keyword blocker was added.

## Tool descriptions

`requested_by_person_id`, `delegated_to_person_ids`, `waiting_on_person_ids`, and `involved_person_ids` stay distinct and say they require that exact role and are not a fallback for an unsupported relationship.

`link_objects` says the generic list is closed and that `related_to` is not a catch-all substitute. Its enum remains `related_to, references, depends_on, part_of`. The four actor-role fields are unchanged.

## T3, R1, and R2

The T3 scripted fixture still calls only `get_object`, records `unchanged=true`, does not call `link_objects`, `update_task`, `create_task`, or `set_task_status`, and does not raise approval. R1 and R2 remain on their existing canonical paths.

## Checks

- `test_ah2_sem1_relation_boundary.py`: 4 passed
- `test_ah2d_task_tool_descriptions.py`: 3 passed
- `test_assistant_ontology_kernel.py`: 3 passed
- `test_untrusted_prompt_boundary.py`: 3 passed
- `test_ah2_stg1_staging_truth.py`: 7 passed
- `test_ah2_ap1_approval_presentation.py`: 13 passed
- those six files together: 33 passed
- `test_ah2m_eval_runner.py` filtered to T3, R1, and R2: 4 passed
- `test_task_relations.py`, `test_h2d_task_mcp_parity.py`, and `test_h2b_link_objects.py`: 20 passed
- `git diff --check`: clean

Model calls: 0. Real network calls: 0. No schema migration. No deploy. No client install.

The stale-date M1 fixture and `test_product_code_matches_production_release` were not modified.

Do not start Person alias/morphology work, Scheduled Activity integration, stale-eval maintenance, rollout, or any other slice from this HOLD.
