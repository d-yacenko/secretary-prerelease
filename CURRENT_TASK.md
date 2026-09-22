# Current task — Telegram Bot API M4BS1: final live read-only Stage C acceptance awaiting explicit authorization

## Status

M4BR1R Stage C post-deploy verifier is ARCHITECT ACCEPTED.

Accepted verifier commit:
`bfea4b308e7513cc743da573d7934e85ff51b393`

Current production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Expected Alembic:
`0046`

Stage C deploy is already COMPLETE / PASS.

## Authorization state

FINAL LIVE READ-ONLY STAGE C VERIFIER IS NOT YET AUTHORIZED.

Acceptable explicit authorization text:

`Разрешаю финальный live read-only Stage C acceptance`

After explicit authorization, run exactly once:

`bash ops/production/verify_telegram_bot_stage_c.sh`

## Verifier guarantees

The accepted verifier:
- makes zero Telegram/provider calls;
- performs zero DB writes;
- performs zero env writes;
- performs zero service restart/recreate;
- does not deploy or move refs;
- checks exact production ref/HEAD/worktree;
- checks DB/API/worker running state and DB health;
- checks application health with bounded retry;
- checks Alembic exact `0046`;
- proves retired Bot routes absent;
- proves live MTProto route present;
- proves Bot Settings/runtime env absent;
- proves MTProto credentials preserved and AI=false;
- proves exactly one MTProto account and active scope count 28;
- proves legacy non-MTProto Telegram objects still exist in aggregate;
- proves at least one preserved legacy Bot-derived object remains readable through canonical generic Inbox eligibility;
- emits no Telegram object/account/peer/message identifiers or message content.

## Failure handling

If verifier blocks or fails:
- do not retry;
- do not bypass;
- do not use direct SSH;
- do not restart/recreate services;
- do not change DB/env;
- return the complete sanitized output and STOP.

## Not authorized

- any production mutation;
- provider calls;
- schema/data cleanup;
- MTProto changes;
- AI enablement.

`CURRENT_TASK.md` is the source of active authorization.
