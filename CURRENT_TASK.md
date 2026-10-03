# CURRENT_TASK

## Status

HOLD

## Completed

REL1D-A.1 role-import audit lifecycle and token accounting.

Implementation: `b596967aefac1f1db093ea01ec67561c578a1a3c`

Changed files:

- `backend/app/ai_audit/constants.py`
- `backend/app/llm/openai_role_import_provider.py`
- `backend/app/services/person_role_import_extraction_service.py`
- `backend/tests/test_rel1d_role_import_extraction.py`

One successful Responses call emits one `model_round`. Proposal facts use non-chargeable `role_import_proposal`. A 2/3 token response charges 5, and two charge 10. Failed and budget-blocked calls charge 0. Traces finish through the canonical path and survive request rollback.

Tests: REL1D-A source and extraction 36 passed, 0 failed. Focused audit, budget, resource, format-parity, REL1A, and REL1C run excluding the four known failures: 158 passed, 1 failed. That failure is `test_transcription_actual_usage_blocks_the_next_paid_call` on a non-WAV payload and reproduces alone. The four known failures were not rewritten. `test_mixed_workload_summary_metrics` still expects `trace_count == 4`; this run observed 21 because durable role-import traces for the bootstrap user are inside its window. The three resource failures are unchanged.

Schema head remains Alembic `0054`.

Production backend/source and the installed Linux client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`. Alembic `0054 / 0054`. No deploy, migration, client install, real model call, provider call, or production data mutation.

REL1D-B and REL1D-C were not started.

## Next

No Executor work is authorized from this HOLD.
