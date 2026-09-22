# Current task — Telegram Bot API M4BV1: final live read-only Stage C acceptance awaiting explicit authorization

## Status

M4BU1 protocol/runtime-env correction is ARCHITECT ACCEPTED.

Accepted verifier code includes:
- canonical Git bootstrap correction: `3c6da496fa0d6bb5dc7d4d37b22190c473a5a0bd`;
- protocol/runtime-env correction: `7a9396a502224b02fb0037628531e4df6c9ada4d`.

Current production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Expected Alembic:
`0046`

## Important corrected root cause

The two earlier `M4BR1_BLOCKED=local_production_ref` attempts were caused directly by the verifier containing a 39-character release constant missing the final `b`.

That defect is fixed. The full expected release is now:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`.

Git trust-order and explicit canonical-URL checks were also hardened and remain accepted.

## Authorization state

FINAL LIVE READ-ONLY RUN IS NOT YET AUTHORIZED.

Acceptable explicit authorization text:

`Разрешаю финальный live read-only Stage C acceptance после M4BU1`

After explicit authorization, execute exactly once:

`bash ops/production/verify_telegram_bot_stage_c.sh`

## Expected accepted behavior

The verifier is read-only and must prove:
- validated canonical target/origin before authoritative branch lookup;
- authoritative main and production refs through explicit canonical URL;
- exact production HEAD and clean worktree;
- DB/API/worker running, DB healthy;
- Alembic exact `0046 (head)`;
- application health;
- retired Bot keys absent from Compose/API/worker runtime env;
- production `.env` Bot legacy lines absent or empty only;
- MTProto credentials preserved;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- retired Bot routes absent;
- required MTProto route present;
- Bot Settings model fields absent;
- exactly one MTProto account;
- active scope count 28;
- legacy non-MTProto Telegram objects preserved;
- at least one historical Bot-derived object readable through canonical Inbox eligibility.

The strict parser is now end-to-end tested against actual `remote_main()` output.

## Hard prohibitions

Must remain:
- Telegram/provider calls = 0;
- DB writes = 0;
- env writes = 0;
- service restart/recreate = 0;
- deploy/ref movement = 0;
- no object/account/peer/message identifiers or message content emitted.

## Failure handling

If verifier blocks or fails:
- do not retry;
- do not bypass;
- do not use direct SSH;
- do not restart/recreate services;
- do not modify DB/env;
- return complete sanitized output and STOP.

`CURRENT_TASK.md` is the source of active authorization.
