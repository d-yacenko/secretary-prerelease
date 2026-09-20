# Current task — Telegram MTProto M4AO2: one human-shell two-page provider probe

## Status

M4AO1 probe build/review is complete at canonical main commit:

`10bed20db42677098c3c47c81140c6dec7714229`

Reviewed probe artifacts:
- `ops/production/manual_mtproto_history_two_page_probe.sh`
- `ops/production/manual_mtproto_history_two_page.py`
- `ops/production/tests/test_manual_mtproto_history_two_page.py`

Local review evidence:
- 22 focused tests PASS;
- `bash -n` PASS;
- Ruff PASS;
- diff-check PASS;
- production SSH = 0;
- Telegram/provider calls = 0;
- production mutation = 0.

M4AN2 structural localization already PASS. Current production runtime/ref remains exact:

`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Current state before provider probe:
- `INITIAL_STATE=true`
- `HISTORY_COMPLETE_BEFORE=false`
- `BACKFILL_CURSOR_PRESENT_BEFORE=false`

Earlier M4AH3 proved page1 with 100 messages and 100 exact conversions.

## Authorization

Authorize exactly ONE manual live execution of the reviewed two-page provider probe from the proven human sandbox shell.

This authorization is HUMAN-SHELL ONLY.

The Executor subprocess must NOT execute production SSH for this task.

## Exact human command

From the canonical human-shell checkout:

```bash
cd ~/work/secretary-prerelease
git fetch origin
git checkout --detach origin/main
git rev-parse HEAD
bash ops/production/manual_mtproto_history_two_page_probe.sh
```

Before running the probe, `git rev-parse HEAD` must equal:

`10bed20db42677098c3c47c81140c6dec7714229`

If it does not, STOP and do not run the probe.

## One-shot semantics

The probe may be launched exactly once under this authorization.

No automatic or manual retry.

A local pre-SSH failure does not consume the provider run.

The live provider run is considered started once the reviewed remote helper begins provider operations.

If any live provider stage fails, STOP and return the sanitized output exactly as emitted. Do not retry.

## Allowed live provider work

Maximum:
- 2 pages;
- 200 messages total;
- 6 logical provider operations total;
- connect <=2;
- is_user_authorized <=2;
- iter_messages <=2.

Page1:
- fresh Telethon client;
- connect;
- authorization check;
- iter_messages limit=100 reverse=false;
- exact `_history_entry_from_message` conversion.

After page1:
- exact production `_next_backfill_state` + cutoff semantics;
- derive `PAGE2_REQUIRED`.

Page2 only if required:
- NEW fresh Telethon client;
- connect;
- authorization check;
- iter_messages max_id=derived cursor, limit<=100, reverse=false;
- exact conversion.

## Strictly forbidden

Do NOT:
- call Secretary Sync API;
- call application `fetch_history`;
- login/re-login;
- discover folders/groups/dialogs;
- Apply Scope;
- perform Telegram write RPCs;
- perform DB writes/flush/commit;
- materialize/upsert;
- restart/recreate services;
- edit production files/env;
- change refs;
- run migrations;
- enable MTProto AI;
- change Bot API;
- print raw message content, IDs, session/reference, credentials, traceback, or raw stderr;
- retry the probe.

## Required outcome

Paste the complete sanitized probe output back to the Architect.

Expected successful terminal markers include:
- reviewed remote terminal marker;
- `MANUAL_M4AO1_END=true`.

The important diagnostic fields are:
- PAGE1_PASS / page1 counts;
- PAGE2_REQUIRED;
- PAGE2_PASS / page2 counts when required;
- CONNECT_CALL_COUNT;
- IS_USER_AUTHORIZED_CALL_COUNT;
- ITER_MESSAGES_CALL_COUNT;
- TELEGRAM_NETWORK_CALLS;
- FAILURE_STAGE / RAW_EXCEPTION_CLASS / MESSAGE_ORDINAL if failure occurs.

Do not interpret or fix the result locally.

Final human action:
run once, paste output, STOP.

`CURRENT_TASK.md` is the source of active authorization.
