# Current task — Telegram Bot API M4BZ1: execute final one-shot live read-only Stage C acceptance

## Status

Human explicitly authorized the final live read-only Stage C acceptance.

Accepted verifier redesign:
`02c6240bb17e7d6a353db907b49cf32e2caf5eaf`

Current production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Expected Alembic:
`0046`

## Authorization

Authorize exactly ONE execution of:

`bash ops/production/verify_telegram_bot_stage_c.sh`

## Expected success evidence

A successful run must include:
- all Stage 0/1 PASS markers;
- `LEGACY_BOT_ROUTES_ABSENT_PASS=true`;
- `MTPROTO_ROUTE_PRESENT_PASS=true`;
- `BOT_SETTINGS_MODEL_ABSENT_PASS=true`;
- `MTPROTO_ACCOUNT_COUNT=1`;
- `ACTIVE_SCOPE_COUNT=28`;
- `LEGACY_BOT_OBJECT_COUNT` >= 1;
- `LEGACY_BOT_INBOX_READABLE=true`;
- `TELEGRAM_NETWORK_CALLS=0`;
- `DB_WRITES=0`;
- `ENV_WRITES=0`;
- `SERVICE_RECREATIONS=0`;
- `M4BR1_TERMINAL=success`;
- `M4BR1_END=true`.

## Read-only guarantees

No:
- Telegram/provider calls;
- DB writes;
- env writes;
- service restarts/recreates;
- deploy/rollback/ref movement;
- schema/data cleanup;
- MTProto behavior/config changes;
- AI enablement.

## Failure handling

If verifier fails or blocks:
- do not retry;
- do not bypass;
- do not use direct SSH;
- do not restart/recreate services;
- do not modify DB/env;
- return complete sanitized stdout and STOP.

## Required report

Return the complete sanitized stdout exactly as produced.

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
