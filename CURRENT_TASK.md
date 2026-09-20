# Current task — Telegram MTProto M4AS1: one controlled backfill continuation Sync

## Status

The first post-fix human Sync completed successfully and committed persistent progress.

Production runtime/ref:
`b7fbdc71584cfde042a998fbfefb06015175a205`

Persisted state after that Sync:
- `INITIAL_STATE=false`
- `HISTORY_COMPLETE_BEFORE=false`
- `BACKFILL_CURSOR_PRESENT_BEFORE=true`

Therefore initial import succeeded, but the bounded 14-day history backfill is not complete.

The existing UI exposes the per-Sync aggregate summary only while the Account screen remains mounted.

## Goal

Perform exactly ONE additional human-controlled Sync of the same already-selected Telegram group to continue the bounded backfill.

This task is HUMAN UI ONLY.

No Executor SSH, provider probe, login, discovery, or production mutation is authorized.

## Human procedure

1. Launch/open the persistent Secretary preview client.
2. Open Account / Telegram MTProto.
3. Confirm:
   - account is connected;
   - the same previously selected group remains selected.
4. Do NOT Apply Scope.
5. Press `Синхронизировать` exactly once for that same selected group.
6. Stay on the Account screen until the operation finishes.
7. Capture the visible Sync summary immediately before navigating away.

Expected summary format includes safe aggregate values such as:
- scanned
- materialized
- created
- updated
- unchanged
- skipped
- history_complete

Do not include peer/account/group IDs in the report.

## One-shot rule

Exactly one Sync click is authorized.

If it errors:
- do not retry;
- do not leave and re-enter to attempt again;
- do not login/re-login;
- do not Apply Scope;
- do not change group/folder selection.

If it succeeds and `history_complete=false`:
- STOP; another backfill continuation requires a new authorization.

If it succeeds and `history_complete=true`:
- STOP; bounded initial history backfill is complete.

## Strictly forbidden

Do NOT:
- click Sync more than once;
- run human-shell provider probes;
- use Executor or manual SSH;
- run migrations;
- edit production;
- enable MTProto AI;
- change Bot API;
- change scope/selections;
- login/re-login.

## Required report

Return only:
- account connected: yes/no;
- same selected group present: yes/no;
- Sync clicked: exactly once;
- visible aggregate summary without IDs;
- `history_complete=true|false`;
- or exact user-facing error if it fails.

Final marker:
`TELEGRAM_MTPROTO_M4AS1_BACKFILL_SYNC_COMPLETE`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
