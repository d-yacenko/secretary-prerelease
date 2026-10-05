# CURRENT_TASK

ACTIVE

## REL1D-HG2B3.2R — repair the two residual stale assertions in MTProto A4 test

REL1D-HG2B3 `efcf5c48771e1d1bf6bb352f6812822033643c35` plus HG2B3.1 `b3744c9a6a02171cfbe30466df49172c73262ce9` remain ARCHITECT SOURCE-ACCEPTED.

REL1D-HG2B3.2 correctly returned HOLD at `43392203c9872b108388baa2a97d996785a89336` because the required set exposed a second stale assertion outside its original scope.

Architect review established that both remaining failures/risks are test drift in the same file:

`backend/tests/test_telegram_mtproto_a4.py`

Production/backend/client remain:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Alembic remains:

`0054 / 0054`

Human REL1D acceptance remains paused.

This task is TEST-ONLY.

## Confirmed runtime contract

`TelethonMtprotoTransport.fetch_dialog_universe(..., limit)` intentionally requests:

`client.iter_dialogs(limit=scan_limit + 1)`

The extra row is a truncation sentinel. It is not retained or processed into the returned dialog universe after the configured scan limit.

This behavior was introduced in commit:

`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

and current `backend/tests/test_telegram_mtproto_a4_2.py` already proves:

- exact boundary counts are complete;
- the provider request uses `TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT + 1`;
- only an actually observed 2001st row marks the 2000-row universe truncated.

Therefore the older A4 expectation of `iter_dialogs(limit=500)` is stale. Do not change runtime to satisfy it.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `backend/tests/test_telegram_mtproto_a4.py`
- `backend/tests/test_telegram_mtproto_a4_2.py`
- `backend/app/connectors/telegram/mtproto_transport.py`

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.
Do not move `production`.

## Exact corrective

Change ONLY:

`backend/tests/test_telegram_mtproto_a4.py`

Make exactly these semantic corrections:

1. Alembic-head test:
   - rename `test_migration_0046_is_single_head` so its name describes `0054`;
   - change expected heads from `["0046"]` to `["0054"]`;
   - keep the assertion strict: exactly one head.

2. Dialog-universe test:
   - keep `test_transport_uses_unfiltered_bounded_dialog_scan_and_raw_facts` unless a rename is strictly needed for accuracy;
   - change only its expected provider call from `{"limit": 500}` to `{"limit": 501}`;
   - do not change the fake client behavior or runtime implementation;
   - do not weaken/remove the raw-fact assertions.

No other file may change except ledger files required by completion protocol.

## Required checks

Run exactly the same required set that produced 127 passed / 1 failed:

- `backend/tests/test_telegram_mtproto_a4.py`
- `backend/tests/test_rel1d_hg2b3_mtproto_sender.py`
- `backend/tests/test_telegram_mtproto_a3.py`
- `backend/tests/test_telegram_mtproto_full_pipeline.py`
- `backend/tests/test_telegram_mtproto_a4_2.py`
- `backend/tests/test_communication_media.py`
- `backend/tests/test_rel1d_role_import_participants.py`
- `backend/tests/test_rel1d_hg2a_scan_window.py`

Collection previously contained 128 tests. If collection is unchanged, expected result is:

`128 passed / 0 failed`

Also run:

- Ruff on `backend/tests/test_telegram_mtproto_a4.py`;
- `git diff --check`.

## Explicit non-goals

Do not:

- change runtime/source code;
- change any migration file, revision id, `down_revision`, schema, migration harness, or deploy logic;
- change Telegram sender/participant semantics;
- change scope/truncation runtime behavior;
- call provider/model APIs;
- sync/reconcile/backfill production;
- design or execute provider repair;
- deploy backend;
- build/install client;
- mutate production product data;
- start Telegram Business work;
- start another task.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG2B3.2R` entry to `PROJECT_STATE.md` including:
   - implementation SHA;
   - single changed test file;
   - exact two stale assertion corrections;
   - sole Alembic head `0054`;
   - exact required-set totals;
   - Ruff/diff-check result;
   - explicit no runtime/migration/provider/model/production/deploy/install/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2B3.2R implementation SHA;
   - residual MTProto A4 test cleanup is ready for Architect review;
   - HG2B3/HG2B3.1 remain source-accepted;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no repair/backfill/rollout/Telegram Business/next task without fresh Architect authorization.

3. commit + push to `main`.

4. STOP.

On blocker:

- return HOLD with exact bounded blocker;
- do not change runtime or migrations;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
