# Current task — Telegram Bot API M4BT1: execute replacement final one-shot live read-only Stage C acceptance

## Status

Human explicitly authorized the replacement final live read-only Stage C acceptance.

Accepted verifier correction:
`dbf1b14941e7582346db17205823b130dfcd59ba`

Current production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Expected Alembic:
`0046`

The previous M4BS1 run blocked locally before SSH because of stale tracking-ref verification. No production access or mutation occurred.

## Authorization

Authorize exactly ONE execution of:

`bash ops/production/verify_telegram_bot_stage_c.sh`

The accepted verifier may only read/inspect:
- authoritative remote `main` and `production` refs via strict `git ls-remote`;
- exact production HEAD and clean tracked worktree;
- DB/API/worker running state and DB health;
- application health with bounded retry;
- Alembic exact `0046 (head)`;
- absence of retired Bot routes and Bot runtime Settings/env;
- presence of required MTProto route;
- preservation of MTProto credentials and `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- exactly one MTProto account;
- active scope count 28;
- aggregate historical non-MTProto Telegram object count;
- existence of at least one preserved historical Bot-derived object readable through canonical Inbox eligibility.

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
