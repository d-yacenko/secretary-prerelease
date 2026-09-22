# Current task — Telegram Bot API M4BL1: second live Stage B retirement awaiting explicit human authorization

## Status

M4BK1R2 retirement harness is ARCHITECT ACCEPTED.

Accepted harness commit:
`f2e3ef441368d52b7583f0604df127504dbffdf7`

Current production runtime/ref:
`fe151f12f64886505253e765b82458710a949e34`

Expected Alembic:
`0046`

The first live Stage B authorization was consumed by a safe preflight failure with `TELEGRAM_NETWORK_CALLS=0`. No webhook/env/service mutation occurred.

A second live run is NOT yet authorized.

## Future authorized action

Exactly one execution of:

`bash ops/production/retire_telegram_bot.sh`

The accepted harness may:
- verify canonical target/host pin and fresh exact production ref;
- verify DB/API/worker/health/Alembic;
- validate deterministic four-key env transform before provider work;
- call `deleteWebhook(drop_pending_updates=true)` exactly once;
- call `getWebhookInfo` exactly once;
- clear only the four Bot settings;
- recreate only API + worker;
- verify actual new container IDs/environments;
- verify DB container/volume unchanged;
- verify MTProto/protected settings preserved;
- verify `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- verify health and Alembic 0046.

## Authorization state

SECOND LIVE RUN IS NOT YET AUTHORIZED.

Acceptable explicit authorization text:

`Разрешаю второй live Stage B retirement Telegram Bot API`

After that authorization, run the accepted wrapper exactly once and return the complete sanitized output.

## Failure handling

If wrapper/harness blocks or fails:
- do not retry;
- do not bypass;
- do not use direct SSH;
- do not call Bot API manually;
- do not restore/reconfigure webhook;
- do not restore Bot secrets;
- return the complete sanitized output and STOP.

## Not authorized

- BotFather/account destruction;
- Stage C source/schema cleanup;
- deploy/rollback/ref movement;
- MTProto behavior/config changes;
- AI enablement.

`CURRENT_TASK.md` is the source of active authorization.
