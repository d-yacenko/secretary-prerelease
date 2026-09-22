# Current task — Telegram Bot API M4BN1: live read-only post-retirement verification awaiting explicit human authorization

## Status

M4BM1R post-retirement verifier is ARCHITECT ACCEPTED.

Accepted verifier commit:
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

The only unconfirmed item is final application health after recreate.

## Authorization state

LIVE READ-ONLY VERIFIER IS NOT YET AUTHORIZED.

Acceptable explicit authorization text:

`Разрешаю live read-only post-retirement verification`

After explicit authorization, run exactly once:

`bash ops/production/verify_telegram_bot_retirement.sh`

## Verifier guarantees

The accepted verifier:
- makes zero Telegram/Bot API/provider calls;
- performs zero DB writes;
- performs zero env writes;
- performs zero service restarts/recreates;
- does not deploy or move refs;
- uses bounded health retry up to 30 attempts with 2-second spacing;
- checks exact production ref/HEAD/worktree;
- checks DB/API/worker running state and DB health;
- checks Bot settings empty in .env, Compose, and actual containers;
- checks MTProto/protected credentials preserved;
- checks AI=false;
- checks exact Alembic 0046.

## Failure handling

If verifier blocks or fails:
- do not retry;
- do not use direct SSH;
- do not restart/recreate services;
- do not restore Bot webhook/secrets;
- return the complete sanitized output and STOP.

## Not authorized

- any mutation;
- BotFather/account destruction;
- Stage C cleanup;
- MTProto behavior/config changes;
- AI enablement.

`CURRENT_TASK.md` is the source of active authorization.
