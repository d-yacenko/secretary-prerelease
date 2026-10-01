# Current task — HOLD

AH2-MR4 is complete. Do not start terminal-T2, the 49-trial batch, AH2-C, or a real-model run from this HOLD.

## Implementation

- SHA: `93b8a263870a116d75229a5765f56373bfe00c7b`
- Changed files:
  - `backend/evals/secretary_agent/external.py`
  - `backend/evals/secretary_agent/fixtures.py`
  - `backend/evals/secretary_agent/runner.py`
  - `backend/tests/test_ah2m_eval_runner.py`

## Registry

Primary registry is 15/15: P1, T1, T2, T3, F1, F2, M1, M2, R1, R2, R3, A1, A2, S1, N1. F2 appears once.

F2-chat is a separate variant from `chat_reply_scenario()`. It does not change catalogue cardinality.

## Fake-only approval

`send_email` and `send_message` stay off the internal approval allowlist.

External approval runs only when all of these hold:

- the case is F2 email or F2-chat;
- exactly one staged action;
- the tool is `send_email` or `send_message` for that case;
- an explicit fake transport bundle is present;
- attempt and token session factories are local savepoint sessions on the trial connection;
- approval is `ActionPlanService.create_plan` then `approve`.

The temporary injection that makes `ActionPlanService` construct a fake-bound `DomainToolService` is restored after success and after an exception. A failed or unexecuted plan does not record an executed `ToolCallRecord`. There is no live transport and no `SessionLocal` fallback.

## Evidence

- Email staging: fake send count 0. Email approval: fake send count 1. Model arguments are `reply_to_object_id` and body `буду завтра` only.
- Frozen route: after staging, the source object's sender, thread, and account are changed. The fake send still uses thread `thread-frozen`.
- Chat staging: fake create-post count 0. Chat approval: fake create-post count 1, and no email send. Model arguments are `reply_to_object_id` and body `буду завтра` only.
- Both scores are `INCOMPLETE` only because `truthful_final_response` is `MANUAL_REVIEW`.
- Both artifacts JSON-round-trip.
- Email then chat leave persistent counts unchanged for users, objects, edges, external-action attempts, pending action plans, Google accounts, and Mattermost accounts.
- Live `GmailTransport`, `MattermostHttpTransport`, and `httpx.Client` construction is not reached.

## Checks

- Deterministic tests: 101 passed.
  - `backend/tests/test_ah2m_eval_runner.py`: 45
  - preserved `test_ah2e_eval_harness.py`, `test_ah1_doc_registry_drift.py`, `test_assistant_ontology_kernel.py`, `test_ah2d_task_tool_descriptions.py`, `test_ah2t_planned_interval.py`: 56
- `python -m evals.secretary_agent.cli validate-catalog`: 15 scenarios.
- `git diff --check`: clean.
- `git diff aa3f475a3a0ee49b938364e6d53f3657711b1a9b..93b8a263870a116d75229a5765f56373bfe00c7b -- backend/app`: empty.
- Model calls: 0. Real network calls: 0.

## Production

- `backend/app` still matches production release `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`.
- Production was not changed. Runtime/ref remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`, Alembic `0052 / 0052`, health PASS.

AH2-M real-model execution is still blocked on a local eval API key.
