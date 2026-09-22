# Current task — Telegram Bot API M4BK1: execute one-shot live Stage B retirement

## Status

Human explicitly authorized the live Stage B Telegram Bot API retirement.

Accepted harness commit:
`e7cbef5bac1a13a3dd56cd2eb3201e42f3b1b3f0`

Current production runtime/ref:
`fe151f12f64886505253e765b82458710a949e34`

Expected Alembic:
`0046`

## Authorization

Authorize exactly ONE execution of:

`bash ops/production/retire_telegram_bot.sh`

The accepted harness may:
1. verify canonical checkout/target/host pin and fresh production ref;
2. verify DB/API/worker/health/Alembic and credential presence;
3. call Telegram Bot API `deleteWebhook(drop_pending_updates=true)` exactly once;
4. call `getWebhookInfo` exactly once to verify empty webhook;
5. atomically clear only:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_BOT_USERNAME`
   - `TELEGRAM_WEBHOOK_SECRET`
   - `TELEGRAM_WEBHOOK_URL`
6. recreate only API + worker;
7. verify DB container/volume unchanged;
8. verify protected DB/credential/MTProto settings preserved;
9. verify `TELEGRAM_MTPROTO_AI_ENABLED=false`;
10. verify health PASS and Alembic exact `0046`.

## Failure handling

If the wrapper/harness blocks or fails:
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

## Required report

Return the complete sanitized wrapper output including:
- all preflight PASS markers;
- provider deletion/read-back markers;
- env/service/postflight markers;
- `TELEGRAM_NETWORK_CALLS`;
- terminal success/failure marker.

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
