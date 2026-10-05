# REL1D-HG2D1.1 production-baseline diagnostic

Evidence classification: `NO_CANDIDATE_REGRESSION_PROVEN__BASELINE_GLOBAL_GATES_ALREADY_RED`

The candidate remains NOT QUALIFIED. This document does not authorize deployment or a production-ref move.

## 1. Identity and environment

- Rollback SHA: `bc69c6fa5c0735db9509d12dd5f77e6285e45901`
- Candidate SHA: `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`
- `origin/main` at diagnosis: `477f202da3755dd207fdf033a44a1bde45b0495f`
- `origin/production` at diagnosis: `bc69c6fa5c0735db9509d12dd5f77e6285e45901`
- Python: 3.13.13, executable `python3`
- pytest: 9.0.0, `python3 -m pytest`
- Ruff: 0.16.5, same `ruff` binary
- Both SHAs used that same installed environment. No dependency set was installed for either SHA.
- `PYTHONDONTWRITEBYTECODE=1` was set on both pytest commands. Pytest cache was disabled with `-p no:cacheprovider`.

Dependency and test-runner configuration compared with `git diff` from rollback to candidate:

- `backend/pyproject.toml`: unchanged
- `backend/uv.lock`: unchanged
- `backend/tests/conftest.py`: unchanged
- `backend/conftest.py`, `backend/pytest.ini`, `backend/setup.cfg`, requirements files, `poetry.lock`, and `Pipfile`/`Pipfile.lock`: not present
- No changed path matches a requirements, lock, pyproject, conftest, or pytest config file

The comparison is valid. The checkouts were detached worktrees of those exact SHAs and were not edited.

## 2. Pytest rollback result

Command, from the rollback worktree `backend/`:

`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -m "not live" -q --tb=no --junitxml=<temporary-path>`

Exit code 1.

Terminal summary: `721 failed, 3519 passed, 3 deselected, 170 warnings, 8 errors in 265.08s (0:04:25)`

JUnit: tests 4248, failures 721, errors 8, skipped 0. No xfailed or xpassed outcome was represented. Deselected 3 comes from the terminal summary and is not inside the JUnit executed count.

## 3. Pytest candidate result

The same command, from the candidate worktree `backend/`, in the same environment.

Exit code 1.

Terminal summary: `716 failed, 3630 passed, 3 deselected, 170 warnings, 8 errors in 227.25s (0:03:47)`

JUnit: tests 4354, failures 716, errors 8, skipped 0. No xfailed or xpassed outcome was represented. Deselected 3.

## 4. Pytest differential

JUnit node identifiers:

- Common failing or error identifiers: 724 (716 failures and 8 errors)
- Rollback-only failing or error identifiers: 5
- Candidate-only failing or error identifiers that exist in the rollback collection: 0
- Candidate-only failing or error identifiers from files absent at rollback: 0
- Candidate-only failing or error identifiers that are new node ids in files present at rollback: 0
- Candidate node ids absent from rollback that passed: 109

No candidate-only traceback rerun was performed.

The 109 passing candidate-only node ids are in added HG2 test files (96) and in modified files `backend/tests/test_phase_27b_mattermost.py` (10), `backend/tests/test_telegram_mtproto_a3.py` (1), `backend/tests/test_telegram_mtproto_a4.py` (1), and `backend/tests/test_telegram_mtproto_a4_2.py` (1).

Rollback-only failing identifiers:

- `tests/test_rel1b_task_context_relevance.py::test_seed_projection_caps_and_hides_role_internals` — file unchanged in the candidate delta; the same node id passed on the candidate run
- `tests/test_telegram_mtproto_a4.py::test_transport_uses_unfiltered_bounded_dialog_scan_and_raw_facts` — file modified; the same node id passed on the candidate run
- `tests/test_telegram_mtproto_a3.py::test_migration_0044_is_the_single_alembic_head` — absent from candidate collection; the renamed head test in that modified file passed
- `tests/test_telegram_mtproto_a4.py::test_migration_0046_is_single_head` — absent from candidate collection; the renamed head test in that modified file passed
- `tests/test_telegram_mtproto_a4_2.py::test_migration_0046_is_single_head` — absent from candidate collection; the renamed head test in that modified file passed

Common failure and error signature families, counted on the shared 724 identifiers:

- 663: `psycopg.errors.UndefinedColumn` for `objects.completion_mode` (602 messages say the column of relation `objects` does not exist; 61 say `objects.completion_mode` does not exist)
- 11: numeric assertion mismatch
- 6: `AssertionError: assert False`
- 6: setup error in `tests/test_assistant_failure_taxonomy.py`
- 4: `ForeignKeyViolation` on `ai_traces.user_id`
- 3: `KeyError: 'pending_action_plan'`
- 2: Alembic head list assertion
- 2: missing UUID membership assertion
- 2: setup error in `tests/test_universal_object_delete.py`
- 2: `EvalSafetyError: eval approval executes exactly one staged action`
- 2: `TypeError: YandexMailSyncService._materialize_uids() missing 1 required keyword-only argument: 'source_account_email'`
- remaining identifiers are single or double assertion mismatches

The dominant family is the missing `completion_mode` column. The same exception is in the rollback JUnit results for those shared tests and in the candidate JUnit results. It is a shared suite symptom already present at the production baseline. It was not repaired.

## 5. Ruff differential

Command in each exact `backend/` worktree:

`ruff check app tests --output-format json`

Both exit codes are 1. Both totals are 96. Counts by code are identical:

- I001 38
- F401 36
- UP017 3
- SIM117 3
- RUF059 3
- BLE001 2
- SIM102 2
- F811 2
- F841 2
- SIM222 1
- FURB162 1
- SIM114 1
- ISC004 1
- RUF012 1

Comparison key was relative path, Ruff code, message, and the stripped source line, ignoring the line number. Common findings: 96. Rollback-only: 0. Candidate-only: 0.

All 96 candidate findings are in files unchanged from rollback to candidate. There are no candidate-only findings in added or modified files.

## 6. Architect-decision evidence

`NO_CANDIDATE_REGRESSION_PROVEN__BASELINE_GLOBAL_GATES_ALREADY_RED`

The production baseline already fails the full non-live suite and repository-wide Ruff. The candidate adds no failing or error test and no Ruff finding. Its new tests passed. Five rollback failures are absent or passing on the candidate.

The Architect decides separately whether candidate-specific issues require corrective work, or whether qualification policy may use a production-baseline no-regression gate for this historical global debt. This diagnosis does not make that policy decision and does not recommend moving `production`.

## 7. Release boundary

The candidate remains NOT QUALIFIED. No source or test fix was made. No deploy or ref move occurred. No SSH, provider call, or production database access occurred. No data repair or client rollout occurred. Human REL1D acceptance remains paused.
