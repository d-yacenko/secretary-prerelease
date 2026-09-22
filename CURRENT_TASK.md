# Current task — Telegram Bot API M4BS1: execute final one-shot live read-only Stage C acceptance

## Status

Human explicitly authorized the final live read-only Stage C acceptance.

Accepted verifier code:
`bfea4b308e7513cc743da573d7934e85ff51b393`

Current production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Expected Alembic:
`0046`

Stage C schema-neutral deploy is already COMPLETE / PASS.

## Authorization

Authorize exactly ONE execution of:

`bash ops/production/verify_telegram_bot_stage_c.sh`

The verifier may only read/inspect:
- canonical target/host pin/repository;
- fresh exact production ref and HEAD;
- tracked worktree cleanliness;
- DB/API/worker container running state and DB health;
- application health with bounded retry;
- Alembic exact `0046 (head)`;
- absence of retired Bot routes;
- presence of required MTProto route;
- absence of Bot Settings/runtime env;
- preservation of MTProto credentials and AI=false;
- exactly one MTProto account;
- active scope count 28;
- aggregate historical non-MTProto Telegram object count;
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

Return the complete sanitized verifier output including all PASS markers reached, any `FAILURE_STAGE`, zero mutation/provider counters, and terminal marker.

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
