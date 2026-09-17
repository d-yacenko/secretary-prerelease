# Current task — Telegram Integration Gate I1C migration-guard correction

## Status

- Telegram A4.1–A4.4: ACCEPTED.
- Integration merge `origin/main` -> `review/telegram-depth-a4-folder-scope` completed at `2a4da0cf7d1bb1cfd2e83c39b3b4dd1e24a938b4` with zero first-parent content diff.
- I1R baseline attribution proved:
  - Ruff: 107 common baseline violations, 0 review-only, 1 main-only.
  - Pytest: 105 common failure/error identities, 0 main-only, 6 review-only.
- Architect independently inspected all six review-only tests and migrations `0044`, `0045`, `0046`.
- All six review-only failures are stale migration-head guards asserting `versions[-1].startswith("0044")` while the accepted Telegram migration chain is now `0044 -> 0045 -> 0046`.
- Runtime/application code and migration definitions are not implicated.
- I1 remains PENDING until this narrow test-only correction is verified.

## Objective

Update exactly six stale migration-head assertions from `0044` to `0046`, then prove the integrated review failure/error signature matches the exact pre-integration main baseline.

This is a test-maintenance correction only. Do not change application/runtime code or migration files.

## Fixed starting point

Work only on `review/telegram-depth-a4-folder-scope` after fast-forwarding to the latest Architect bookkeeping HEAD.

Preserve ancestry through integration merge:

`2a4da0cf7d1bb1cfd2e83c39b3b4dd1e24a938b4`

Exact baseline for attribution remains:

`1be75b6d4329e25baaf158b9c61dafa3029b0184`

## Authorized edits — exactly six lines

In each file below, replace only:

`assert versions[-1].startswith("0044")`

with:

`assert versions[-1].startswith("0046")`

Files/tests:

1. `backend/tests/test_scheduled_work_a.py`
   - `test_migration_0038_revises_0037`
2. `backend/tests/test_teams_a.py`
   - `test_migration_0040_revises_0039`
3. `backend/tests/test_telegram_a.py`
   - `test_migration_0039_revises_0038`
4. `backend/tests/test_temporal_signals_a.py`
   - `test_migration_0037_temporal_signals_default_false`
5. `backend/tests/test_workflow_intelligence_relevance_c.py`
   - `test_pass_c_did_not_add_label_migration`
6. `backend/tests/test_workflow_intelligence_semantic_context_e_a.py`
   - `test_migration_0033_from_0032`

No refactor/generalization in I1C. No helper extraction. No migration changes.

## Required verification

Use local development PostgreSQL only.

1. Run exactly the six corrected tests by nodeid. All six must PASS.

2. Migration verification:

`alembic upgrade head`

`alembic heads`

Expected one head only: `0046`.

3. Full backend regression:

`pytest -q`

Capture full output outside repository and compare FAILED/ERROR identities against the saved/exact main baseline from I1R.

Expected acceptance condition:

- review-only FAILED/ERROR identities: 0;
- main-only identities do not matter for Telegram integration, but report them;
- all remaining review failures/errors must be contained in the exact main baseline identity set.

Based on I1R, a deterministic run would normally move the six stale failures to passes (approximately `2936 passed, 97 failed, 8 errors, 3 skipped`), but identity equality/containment is authoritative, not raw counts.

If new review-only identity appears, STOP and report it. Do not fix anything else.

4. Telegram regression:

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py tests/test_telegram_mtproto_a4_3.py tests/test_telegram_mtproto_a4_4.py`

Expected: 137 passed unless collection count has legitimately changed; report exact result.

5. Static/hygiene:

`ruff check app tests --output-format concise`

The accepted criterion is no review-only Ruff violations versus the exact main baseline. Do not fix baseline Ruff debt in I1C.

`git diff --check`

`git status --short`

6. Diff scope:

The implementation commit must change exactly the six listed test files and exactly one assertion line in each. No other tracked file content change is authorized in the Executor commit.

## Completion report

Commit and push only to `review/telegram-depth-a4-folder-scope`.

Return:

- starting review SHA;
- I1C commit SHA;
- final remote review SHA;
- changed-file list;
- exact diff summary confirming six one-line test changes only;
- six-test nodeid command/result;
- `alembic upgrade head` result;
- `alembic heads` result;
- full `pytest -q` counts;
- common/review-only/main-only FAILED/ERROR identity counts versus exact main baseline;
- Telegram suite result;
- Ruff common/review-only/main-only attribution (or proof review-only remains zero);
- `git diff --check` result;
- final clean `git status --short`;
- confirmation no application/runtime/migration/UI/production/A4.5 changes;
- final marker exactly:

`TELEGRAM_INTEGRATION_GATE_I1C_READY`

Then STOP.

## Production boundary

No main fast-forward, production deploy, migration execution, SSH, production Compose, provider mutation, UI work, or A4.5 is authorized in I1C.
