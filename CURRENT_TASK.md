# CURRENT_TASK

ACTIVE

## REL1D-HG2B3.1 — repair stale MTProto Alembic-head assertions

REL1D-HG2B3 implementation `efcf5c48771e1d1bf6bb352f6812822033643c35` has passed Architect runtime/source review for its intended sender-identity semantics.

It is NOT YET ARCHITECT SOURCE-ACCEPTED only because the required focused suite is red on two pre-existing stale Alembic-head assertions:

- `backend/tests/test_telegram_mtproto_a3.py::test_migration_0044_is_the_single_alembic_head`
- `backend/tests/test_telegram_mtproto_a4_2.py::test_migration_0046_is_single_head`

Both tests predate HG2B3, neither file was changed by HG2B3, and both assert an obsolete migration head while the repository and production are already at:

`0054 / 0054`

This task is TEST-ONLY.

Production/backend/client remain:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Human REL1D acceptance remains paused.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `backend/tests/test_telegram_mtproto_a3.py`
- `backend/tests/test_telegram_mtproto_a4_2.py`
- Alembic migration graph under `backend/alembic/versions/`

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.

Do not move `production`.

## Exact corrective

1. Verify independently that the repository has exactly one Alembic head and it is `0054`.
2. In the two stale MTProto tests only:
   - update the expected single head to `0054`;
   - rename the stale test function names to describe the current `0054` expectation if needed for clarity.
3. Do not change runtime code.
4. Do not change any migration file, revision id, down_revision, schema, migration harness, or deployment logic.
5. Do not suppress, skip, xfail, delete, or weaken the assertions. They must still prove there is exactly one Alembic head and that it is `0054`.

## Required checks

Run the same focused HG2B3 suite:

- `backend/tests/test_rel1d_hg2b3_mtproto_sender.py`
- `backend/tests/test_telegram_mtproto_a3.py`
- `backend/tests/test_telegram_mtproto_full_pipeline.py`
- `backend/tests/test_telegram_mtproto_a4_2.py`
- `backend/tests/test_communication_media.py`
- `backend/tests/test_rel1d_role_import_participants.py`
- `backend/tests/test_rel1d_hg2a_scan_window.py`

Expected result after this test-only correction: all tests in this focused set pass. The prior run contained 110 total tests (108 passed / 2 stale-head failures), so if collection is unchanged the expected total is 110 passed / 0 failed.

Also run:

- Ruff on the two touched test files;
- `git diff --check`.

## Explicit non-goals

Do not:

- change HG2B3 runtime/source semantics;
- change Telegram parsing, sender metadata, participant gating, outbound behavior, materialization, or reconcile behavior;
- add or alter migrations;
- call any provider/model;
- sync/reconcile/backfill production;
- deploy backend;
- build/install client;
- mutate production product data;
- start the repair/backfill plan;
- start Telegram Business work;
- start another connector task.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG2B3.1` entry to `PROJECT_STATE.md` with:
   - implementation SHA;
   - exact two test files changed;
   - confirmation repository single head is `0054`;
   - exact focused test result;
   - Ruff/diff-check result;
   - explicit no runtime/migration/provider/model/production/deploy/install/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2B3.1 implementation SHA;
   - HG2B3/HG2B3.1 package is ready for Architect source-acceptance review;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no repair/backfill/rollout/Telegram Business/next task without fresh Architect authorization.

3. commit + push to `main`.

4. STOP.

On blocker:

- return HOLD with the exact bounded blocker;
- do not alter runtime or migrations to make the tests green;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
