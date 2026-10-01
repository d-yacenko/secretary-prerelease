# Current task — HOLD

AH2-MR2.1 is complete. Do not start mutation fixtures, the 49-trial batch, AH2-C, or a real-model run from this HOLD.

## Implementation

- SHA: `a9cb409e18b56f7481f4078aeef44593a70d96fc`
- Changed files:
  - `backend/evals/secretary_agent/fixtures.py`
  - `backend/evals/secretary_agent/runner.py`
  - `backend/evals/secretary_agent/scripted.py`
  - `backend/tests/test_ah2m_eval_runner.py`

## Provider call surface

`provider.run` receives message, history, ui_context, reference datetime, timezone, tool_runner, identity_facts, and the keyword-only live `system_instructions` and `tool_definitions`. `PreparedFixture` does not reach `run()`. `bind_rounds` receives only the scripted tool rounds and rejects a fixture object.

## Round commits

A scripted round is one model response's tool calls. `ScriptedProvider` calls `commit_model_visible_outputs()` after each round. The generic runner does not commit again after the provider returns. P1, T2, T3, R3, S1, and N1 are one read round. A2 is one staging round. T1 is two rounds: `retrieve`, then `create_task`.

## R3 allowlist proof

An edge id taken from the bounded `list_neighbors` output is rejected as not exposed before the commit. After the commit, the same id reaches `approval_required` and is not executed. The scored R3 trace is still only `list_neighbors`; evidence_edge_count stays 2 and removed stays false.

## Preserved scenarios

P1, T2, T3, S1, N1, A2, and T1 remain structurally green. T1 still creates one confirmed open ongoing Task «Публикации» through `ActionPlanService`. Artifacts JSON-round-trip. Sequential P1 then N1 leave zero `ah2mr1-%` users.

## Checks

- Deterministic tests: 83 passed.
  - `backend/tests/test_ah2m_eval_runner.py`: 27
  - preserved `test_ah2e_eval_harness.py`, `test_ah1_doc_registry_drift.py`, `test_assistant_ontology_kernel.py`, `test_ah2d_task_tool_descriptions.py`, `test_ah2t_planned_interval.py`: 56
- `python -m evals.secretary_agent.cli validate-catalog`: 15 scenarios.
- `git diff --check`: clean.
- `git diff aa3f475a3a0ee49b938364e6d53f3657711b1a9b..a9cb409e18b56f7481f4078aeef44593a70d96fc -- backend/app`: empty.
- Model calls: 0. External network calls: 0.

## Production

- `backend/app` still matches production release `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`.
- Production was not changed. Runtime/ref remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`, Alembic `0052 / 0052`, health PASS.

AH2-M real-model execution is still blocked on a local eval API key.
