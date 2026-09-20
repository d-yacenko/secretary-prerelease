# Current task — Telegram MTProto M4AP1: normalize absent Telethon history bounds

## Status

M4AO2 one-shot human-shell provider probe completed and localized the live failure.

Observed live result:
- production guards PASS;
- structural/session/reference checks PASS;
- connect PASS;
- is_user_authorized PASS;
- first history iterator failed before yielding any message;
- `PAGE1_PASS=false`;
- `PAGE1_MESSAGES_SEEN=0`;
- `PAGE1_ENTRIES_CONVERTED=0`;
- `PAGE1_ENTRIES_NONE=0`;
- `FAILURE_STAGE=STAGE_3_PAGE1_ITERATION`;
- `RAW_EXCEPTION_CLASS=TypeError`;
- `MESSAGE_ORDINAL=1`;
- logical provider counts connect/auth/iter = 1/1/1;
- `TELEGRAM_NETWORK_CALLS=3`;
- no DB writes/materialization;
- no production mutation.

Root cause:
`TelethonMtprotoTransport.fetch_history` forwards absent optional bounds as explicit `None`:

- `min_message_id=None -> min_id=None`
- `max_message_id=None -> max_id=None`

Telethon v1 history iteration treats these bounds as numeric values during iterator initialization, including expressions equivalent to:
- `max(offset_id, max_id)` in normal order;
- `max(offset_id, min_id)` in reverse order.

Therefore explicit `None` can raise `TypeError` before the first message is yielded.

This explains the M4AO2 failure and also explains why earlier raw page1 diagnostics could pass when absent bounds were omitted rather than explicitly passed as None.

## Goal

Implement the smallest transport-boundary fix and focused regressions.

No production deploy in this task.

## Executor workspace

Work only from:

`~/work/secretary-executor`

Canonical origin:

`https://github.com/d-yacenko/secretary-prerelease.git`

Do not use:
- `~/work/secretary`
- `~/work/secretary-prerelease`

for implementation work.

## Bootstrap

Before implementation:

```bash
git fetch origin
git switch main
git pull --ff-only
git remote get-url origin
git rev-parse HEAD
git status --short
```

Require:
- exact canonical origin;
- current `origin/main`;
- clean worktree.

Then read:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `backend/app/connectors/telegram/mtproto_transport.py`
- `backend/tests/test_telegram_mtproto_a3.py`
- `backend/tests/test_telegram_mtproto_m4ai.py`

## Required implementation

In `TelethonMtprotoTransport.fetch_history`, normalize absent bounds to Telethon's numeric sentinel before calling `iter_messages`:

- absent `min_message_id` => `min_id=0`
- absent `max_message_id` => `max_id=0`

Keep the public method signature unchanged.

Do not change:
- page size;
- reverse semantics;
- error taxonomy;
- auth handling;
- conversion behavior;
- retry behavior;
- discovery;
- write operations;
- DB schema;
- materialization.

Prefer the smallest explicit boundary normalization.

## Required regressions

Add focused tests that assert the real transport calls Telethon with numeric bounds in all relevant history modes.

At minimum:

1. Initial history:
   - `min_message_id=None`
   - `max_message_id=None`
   - `reverse=False`
   - fake client records:
     - `min_id == 0`
     - `max_id == 0`

2. Incremental history:
   - positive `min_message_id`
   - absent max
   - `reverse=True`
   - fake client records:
     - exact positive `min_id`
     - `max_id == 0`

3. Backfill history:
   - absent min
   - positive `max_message_id`
   - `reverse=False`
   - fake client records:
     - `min_id == 0`
     - exact positive `max_id`

4. Preserve current provider-neutral mapping:
   - a non-auth `TypeError` from provider iteration is still mapped to `TelegramMtprotoProviderUnavailableError`.
   - do not weaken existing M4AI taxonomy regressions.

5. If practical, include one regression that would fail under explicit `None` but pass under numeric sentinels, closely modeling Telethon iterator initialization.

## Verification

Run focused tests for:
- Telegram MTProto A3 history transport/service;
- M4AI taxonomy;
- any newly added regression file.

Run Ruff on changed Python files.

Run repository diff-check / relevant static checks.

No live Telegram/provider calls.
No production SSH.
No production mutation.

## Deliverable

If all checks PASS:
- commit/push to canonical main;
- update `PROJECT_STATE.md` with the implemented root-cause fix and verification;
- do NOT deploy.

Report:
- commit SHA;
- changed files;
- focused test counts/results;
- Ruff/diff-check;
- confirmation production SSH = 0;
- confirmation Telegram/provider calls = 0;
- confirmation production mutation = 0.

Final marker:

`TELEGRAM_MTPROTO_M4AP1_BOUND_NORMALIZATION_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
