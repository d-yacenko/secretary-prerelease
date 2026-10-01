# Current task — HOLD

AH2-MR3 is complete. Do not start F2, external fixtures, the 49-trial batch, AH2-C, or a real-model run from this HOLD.

## Implementation

- SHA: `d2a53a2609b214317295c685b2156b5cbd5559cd`
- Changed files:
  - `backend/evals/secretary_agent/fixtures.py`
  - `backend/evals/secretary_agent/runner.py`
  - `backend/tests/test_ah2m_eval_runner.py`

## Registry

14 of 15 primary catalogue scenarios: P1, T1, T2, T3, F1, M1, M2, R1, R2, R3, A1, A2, S1, N1. F2 is absent.

## Approval allowlist

Execution happens only for `staged_then_executed`, or `staged_then_executed_if_present` when one action is staged, and only when that tool is `create_task`, `update_task`, `link_objects`, `create_scheduled_activity`, or `set_task_status`. The path is `ActionPlanService.create_plan` then `approve`. `send_email` and `create_calendar_event` raise before a plan is created. `staged_only` and `approval=none` do not execute.

## Scenario results

- F1: PDF is seeded. Round 1 retrieves «Публикации». Before that round's commit, `update_task` on the Task id is rejected as not exposed. After the commit, one approved `update_task` puts the PDF in `evidence_object_ids`. The DB has one confirmed `references` edge from the Task to the PDF. The PDF is not a Task. No second Task is created.
- M1: one scheduled activity «Позвонить в издательство» at `2026-10-02T09:00:00+02:00`, priority normal. Task count 0. No calendar event.
- M2: retrieve «Черновик», then one `update_task` with planned start `2026-10-06T10:00:00+02:00`, planned end `2026-10-06T12:00:00+02:00`, and due `2026-10-09T18:00:00+02:00`. One Task remains. End is after start. No reminder or calendar object.
- R1: child Task is seeded. Retrieve finds ongoing «Публикации». Approved `link_objects` writes child to parent `part_of`. Not reversed and not `depends_on`.
- R2: one round resolves «Марина» and retrieves «Черновик». Before the commit, `waiting_on_person_ids` using the resolved person id is rejected as not exposed. After the commit, approved `update_task` writes one `waiting_on` edge. No `related_to`.
- A1: approved `set_task_status` open on an already open Task records `changed=false`. Status stays open.

Each new run is `INCOMPLETE` only because `truthful_final_response` is `MANUAL_REVIEW`. Artifacts JSON-round-trip. Prior P1/T1/T2/T3/R3/S1/N1/A2 scenarios stay green.

## Isolation

M1 then F1, each with an inner approved action and an outer rollback, leave persistent user, object, and edge counts unchanged.

## Checks

- Deterministic tests: 93 passed.
  - `backend/tests/test_ah2m_eval_runner.py`: 37
  - preserved `test_ah2e_eval_harness.py`, `test_ah1_doc_registry_drift.py`, `test_assistant_ontology_kernel.py`, `test_ah2d_task_tool_descriptions.py`, `test_ah2t_planned_interval.py`: 56
- `python -m evals.secretary_agent.cli validate-catalog`: 15 scenarios.
- `git diff --check`: clean.
- `git diff aa3f475a3a0ee49b938364e6d53f3657711b1a9b..d2a53a2609b214317295c685b2156b5cbd5559cd -- backend/app`: empty.
- Model calls: 0. External network calls: 0.

## Production

- `backend/app` still matches production release `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`.
- Production was not changed. Runtime/ref remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`, Alembic `0052 / 0052`, health PASS.

AH2-M real-model execution is still blocked on a local eval API key.
