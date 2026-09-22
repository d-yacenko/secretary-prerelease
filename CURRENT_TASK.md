# Current task — Telegram Bot API M4BZ1: final live read-only Stage C acceptance awaiting explicit authorization

## Status

M4BY1 Stage 2 redesign is ARCHITECT ACCEPTED.

Accepted verifier redesign commit:
`02c6240bb17e7d6a353db907b49cf32e2caf5eaf`

Current production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Expected Alembic:
`0046`

Previously proven live invariants:
- exact production HEAD/ref;
- clean production worktree;
- DB/API/worker running;
- DB healthy;
- Alembic 0046;
- application health;
- retired Bot runtime env absent;
- MTProto/protected credentials preserved;
- TELEGRAM_MTPROTO_AI_ENABLED=false;
- zero provider calls / DB writes / env writes / service recreations.

## Stage 2 architecture now accepted

- route checks use read-only GET `http://127.0.0.1:18080/openapi.json`;
- no `app.main` import in DB child;
- Settings uses a separate minimal child;
- DB/read-state uses a narrow child only;
- no generic `STAGE_2_BOOTSTRAP` normal-path failure remains;
- fixed sanitized narrow failure stages remain available.

## Authorization state

FINAL LIVE READ-ONLY STAGE C ACCEPTANCE IS NOT YET AUTHORIZED.

Acceptable explicit authorization text:

`Разрешаю финальный live read-only Stage C acceptance M4BZ1`

After explicit authorization, execute exactly once:

`bash ops/production/verify_telegram_bot_stage_c.sh`

## Expected success evidence

A successful run must include:
- all existing Stage 0/1 PASS markers;
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

## Failure handling

If verifier fails or blocks:
- do not retry;
- do not bypass;
- do not use direct SSH;
- do not restart/recreate services;
- do not modify DB/env;
- return complete sanitized stdout and STOP.

## Hard prohibitions

No:
- Telegram/provider calls;
- DB writes;
- env writes;
- service restarts/recreates;
- deploy/rollback/ref movement;
- schema/data cleanup;
- MTProto behavior/config changes;
- AI enablement.

`CURRENT_TASK.md` is the source of active authorization.
