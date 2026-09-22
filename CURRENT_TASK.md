# Current task — Telegram Bot API M4BN1: execute one-shot live read-only post-retirement verification

## Status

Human explicitly authorized the live read-only post-retirement verification.

Accepted verifier code:
`27f54763bd04c72a98046a5d649b703072e0369f`

Current production runtime/ref:
`fe151f12f64886505253e765b82458710a949e34`

Expected Alembic:
`0046`

Stage B irreversible core actions are already materially applied:
- Bot webhook deleted;
- webhook read-back confirmed empty;
- four Bot env settings cleared;
- API + worker recreated;
- DB container/volume preserved;
- MTProto/protected credentials preserved;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`.

## Authorization

Authorize exactly ONE execution of:

`bash ops/production/verify_telegram_bot_retirement.sh`

The verifier may only read/inspect:
- canonical target/host pin/repository;
- fresh exact production ref and HEAD;
- tracked worktree cleanliness;
- DB/API/worker container existence/running state;
- DB health and volume identity;
- Bot settings empty in `.env`, Compose, and actual API/worker containers;
- MTProto/protected credentials consistency;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- application health with bounded retry up to 30 attempts, 2 seconds apart;
- Alembic exact `0046 (head)`.

## Hard prohibitions

The verifier must perform:
- Telegram/Bot API/provider calls = 0;
- DB writes = 0;
- env writes = 0;
- service restarts/recreates = 0;
- deploy/ref movement = 0.

## Failure handling

If verifier blocks or fails:
- do not retry;
- do not bypass;
- do not use direct SSH;
- do not restart/recreate services;
- do not restore Bot webhook/secrets;
- return the complete sanitized output and STOP.

## Required report

Return the complete sanitized verifier output including:
- all PASS markers reached;
- any `FAILURE_STAGE`;
- zero mutation/provider counters;
- terminal marker.

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
