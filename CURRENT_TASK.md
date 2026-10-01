# Current task — HOLD

AH2-MR1.1 is complete. Do not start AH2-MR2, the 49-trial real-model batch, AH2-C, or a production rollout from this HOLD.

## Implementation

- SHA: `a2df6c325c971bcd1cc9fd062f897ecae5fcd40d`
- Changed files:
  - `backend/evals/secretary_agent/runner.py`
  - `backend/evals/secretary_agent/safety.py`
  - `backend/tests/test_ah2m_eval_runner.py`

## Injected database target

`run_scripted` takes an `EvalDatabase` and calls `assert_eval_database` on that same `engine` before `connect()`. Acceptance requires `disposable is True`, host `localhost` / `127.0.0.1` / `::1`, and a non-empty database name. The safe identity is `host`, `database`, and `disposable=true`. It does not include a password or a credential-bearing DSN. A remote URL and a local URL without the explicit disposable flag raise before `Engine.connect()`.

`runner.py` does not import `app.db.engine` and does not reference `SessionLocal`. Ordinary `settings.postgres_host` is not consulted, so changing it cannot redirect the injected engine.

## Safe artifact boundary

`build_safe_artifact_payload` serializes the bounded `EvalRun` and the allowlisted public config. It does not store a raw provider response. It keeps `final_answer` and rejects API keys, credential DSNs, access/refresh tokens, `chain_of_thought`, `reasoning_trace`, `hidden_reasoning`, raw provider request/response fields, and `production_user_id`. A2 and T1 payloads pass and round-trip as JSON.

## Checks

- Deterministic tests: 70 passed.
  - `backend/tests/test_ah2m_eval_runner.py`: 14
  - preserved `test_ah2e_eval_harness.py`, `test_ah1_doc_registry_drift.py`, `test_assistant_ontology_kernel.py`, `test_ah2d_task_tool_descriptions.py`, `test_ah2t_planned_interval.py`: 56
- `python -m evals.secretary_agent.cli validate-catalog`: 15 scenarios.
- `git diff --check`: clean.
- `git diff aa3f475a3a0ee49b938364e6d53f3657711b1a9b..a2df6c325c971bcd1cc9fd062f897ecae5fcd40d -- backend/app`: empty.

## Scripted dry runs

- A2: scripted `create_task` «Купить бумагу» was staged and not approved. Confirmed task count stayed 0. Overall score `INCOMPLETE` only because `truthful_final_response` is `MANUAL_REVIEW`. Automatable dimensions are `PASS` or `NOT_APPLICABLE`.
- T1: scripted retrieve then `create_task` with `completion_mode=ongoing` for «Публикации». That single staged action was approved through `ActionPlanService` and executed locally. Final facts: task_count 1, title «Публикации», status open, completion_mode ongoing. Overall score `INCOMPLETE` for the same truthful-review reason. Automatable dimensions pass.
- Model calls: 0. Network calls from these dry runs: 0.

## Production

- `backend/app` still matches production release `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`.
- Production was not changed. Runtime/ref remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`, Alembic `0052 / 0052`, health PASS.

AH2-M real-model execution is still blocked on a local eval API key.
