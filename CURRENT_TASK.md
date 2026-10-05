# CURRENT_TASK

ACTIVE

## REL1D-HG2B3.2 — repair remaining stale MTProto A4 Alembic-head assertion

REL1D-HG2B3 `efcf5c48771e1d1bf6bb352f6812822033643c35` plus HG2B3.1 `b3744c9a6a02171cfbe30466df49172c73262ce9` are ARCHITECT SOURCE-ACCEPTED.

The required HG2B3 focused suite is green:

`110 passed / 0 failed`

Production/backend/client remain:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Alembic remains:

`0054 / 0054`

Human REL1D acceptance remains paused.

A separate pre-existing stale assertion was correctly reported by the Executor and was outside HG2B3.1 scope:

`backend/tests/test_telegram_mtproto_a4.py::test_migration_0046_is_single_head`

That test still expects Alembic head `0046`, while the repository has one current head, `0054`.

This task is ONLY the residual test correction. Do not start provider repair/backfill planning or execution.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `backend/tests/test_telegram_mtproto_a4.py`
- Alembic migration graph under `backend/alembic/versions/`

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.
Do not move `production`.

## Exact corrective

1. Independently verify the Alembic script graph has exactly one head and it is `0054`.
2. In `backend/tests/test_telegram_mtproto_a4.py` only:
   - rename `test_migration_0046_is_single_head` to describe the current `0054` expectation;
   - change only its expected head from `0046` to `0054`.
3. Keep the assertion strict: it must still prove exactly one head and that it is `0054`.
4. Do not skip, xfail, delete, or weaken the test.

## Required checks

Run:

- `backend/tests/test_telegram_mtproto_a4.py`
- `backend/tests/test_rel1d_hg2b3_mtproto_sender.py`
- `backend/tests/test_telegram_mtproto_a3.py`
- `backend/tests/test_telegram_mtproto_full_pipeline.py`
- `backend/tests/test_telegram_mtproto_a4_2.py`
- `backend/tests/test_communication_media.py`
- `backend/tests/test_rel1d_role_import_participants.py`
- `backend/tests/test_rel1d_hg2a_scan_window.py`

All collected tests in this set must pass.

Also run:

- Ruff on `backend/tests/test_telegram_mtproto_a4.py`;
- `git diff --check`.

## Explicit non-goals

Do not:

- change runtime/source code;
- change any migration file, revision id, `down_revision`, schema, migration harness, or deployment logic;
- change HG2B3 sender/participant semantics;
- call provider/model APIs;
- sync/reconcile/backfill production;
- design or execute the provider repair plan;
- deploy backend;
- build/install client;
- mutate production product data;
- start Telegram Business work;
- start another connector/task.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG2B3.2` entry to `PROJECT_STATE.md` with:
   - implementation SHA;
   - the single changed file;
   - confirmation the repository has sole Alembic head `0054`;
   - exact test totals for the required set;
   - Ruff/diff-check result;
   - explicit no runtime/migration/provider/model/production/deploy/install/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2B3.2 implementation SHA;
   - residual MTProto Alembic-head test cleanup is ready for Architect review;
   - HG2B3/HG2B3.1 remain source-accepted;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no repair/backfill/rollout/Telegram Business/next task without fresh Architect authorization.

3. commit + push to `main`.

4. STOP.

On blocker:

- return HOLD with the exact bounded blocker;
- do not alter runtime or migrations to make the test green;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
