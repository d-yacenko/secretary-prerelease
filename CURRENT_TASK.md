# Current task — Telegram MTProto M4AR2 complete: await next authorization

## Status

M4AR2 read-only reconstruction is complete.

Production runtime/ref:
`b7fbdc71584cfde042a998fbfefb06015175a205`

Post-Sync persisted state:
- `INITIAL_STATE=false`
- `HISTORY_COMPLETE_BEFORE=false`
- `BACKFILL_CURSOR_PRESENT_BEFORE=true`

Pre-Sync state was:
- `INITIAL_STATE=true`
- `HISTORY_COMPLETE_BEFORE=false`
- `BACKFILL_CURSOR_PRESENT_BEFORE=false`

Read-only structural verification:
- production/runtime guards PASS;
- Alembic `0046`;
- account/manual-selection cardinality PASS;
- session/reference decrypt/parse/peer-match PASS;
- `FAILURE_SUBSTAGE=NONE`;
- `RAW_EXCEPTION_CLASS=NONE`;
- `TELEGRAM_NETWORK_CALLS=0`;
- no DB writes/materialization;
- no production mutation.

Conclusion:
- the deployed `None -> 0` Telethon bound normalization fixed the prior initial iterator `TypeError`;
- the single human Sync completed successfully and committed persistent history progress;
- history is not yet complete and a backfill cursor remains.

## Authorization state

No additional Telegram/provider action is currently authorized.

Do NOT:
- click Sync again;
- Apply Scope;
- run provider probes;
- login/re-login;
- change group/folder selection;
- mutate production.

A later task may authorize another bounded Sync to continue backfill.

`CURRENT_TASK.md` is the source of active authorization.
