# Current task — Telegram Bot API M4BV1: execute final one-shot live read-only Stage C acceptance

## Status

Human explicitly authorized the final live read-only Stage C acceptance after M4BU1.

Accepted verifier baseline:
- canonical Git bootstrap: `3c6da496fa0d6bb5dc7d4d37b22190c473a5a0bd`;
- protocol/runtime-env consistency: `7a9396a502224b02fb0037628531e4df6c9ada4d`.

Current production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Expected Alembic:
`0046`

## Authorization

Authorize exactly ONE execution of:

`bash ops/production/verify_telegram_bot_stage_c.sh`

The verifier may only read/inspect:
- validated canonical target/origin;
- authoritative remote `main` and `production` refs via explicit canonical URL;
- exact production HEAD and clean tracked worktree;
- DB/API/worker running state and DB health;
- Alembic exact `0046 (head)`;
- application health;
- absence of retired Bot variables from Compose API/worker and actual API/worker container environments;
- production `.env` legacy Bot keys absent or empty only;
- preservation of MTProto/protected credentials and `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- absence of retired Bot routes and Settings fields;
- presence of required MTProto route;
- exactly one MTProto account;
- active scope count 28;
- aggregate preserved legacy non-MTProto Telegram objects;
- existence of at least one historical Bot-derived object readable through canonical Inbox eligibility.

## Hard prohibitions

The verifier must perform:
- Telegram/provider calls = 0;
- DB writes = 0;
- env writes = 0;
- service restarts/recreates = 0;
- deploy/ref movement = 0.

It must emit no object/account/peer/message identifiers and no message content.

## Failure handling

If verifier blocks or fails:
- do not retry;
- do not bypass;
- do not use direct SSH;
- do not restart/recreate services;
- do not modify DB/env;
- return the complete sanitized output and STOP.

## Required report

Return the complete sanitized verifier output, including all PASS markers reached, any `FAILURE_STAGE`, zero mutation/provider counters, terminal marker, and final end marker if success.

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
