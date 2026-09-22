# Current task — Telegram Bot API M4BT1: replacement final live read-only Stage C acceptance awaiting explicit authorization

## Status

M4BS1R authoritative-ref correction is ARCHITECT ACCEPTED.

Accepted verifier correction:
`dbf1b14941e7582346db17205823b130dfcd59ba`

Current production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Expected Alembic:
`0046`

The previous M4BS1 live authorization was consumed by a local pre-SSH false blocker. No production access or mutation occurred.

## Authorization state

REPLACEMENT FINAL LIVE READ-ONLY RUN IS NOT YET AUTHORIZED.

Acceptable explicit authorization text:

`Разрешаю повторный финальный live read-only Stage C acceptance`

After explicit authorization, run exactly once:

`bash ops/production/verify_telegram_bot_stage_c.sh`

## Verifier guarantees

The accepted verifier:
- validates authoritative remote `main` and `production` with strict `git ls-remote`;
- does not depend on `origin/production` or tracking-ref refresh;
- verifies exact production release and clean worktree;
- performs zero Telegram/provider calls;
- performs zero DB writes;
- performs zero env writes;
- performs zero service restart/recreate;
- does not deploy or move refs;
- verifies DB/API/worker state, health, Alembic 0046;
- verifies retired Bot routes/config absent;
- verifies MTProto route/config/account/scope preserved;
- verifies historical Bot-derived objects remain present and at least one is readable through canonical Inbox eligibility;
- emits no object/account/peer/message identifiers or message content.

## Failure handling

If verifier blocks or fails:
- do not retry;
- do not bypass;
- do not use direct SSH;
- do not restart/recreate services;
- do not modify DB/env;
- return the complete sanitized output and STOP.

`CURRENT_TASK.md` is the source of active authorization.
