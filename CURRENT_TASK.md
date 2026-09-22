# Current task — Telegram Bot API M4BK1: Stage B live retirement awaiting explicit human authorization

## Status

M4BJ1R retirement harness is ARCHITECT ACCEPTED.

Accepted harness commit:
`e7cbef5bac1a13a3dd56cd2eb3201e42f3b1b3f0`

Current production runtime/ref:
`fe151f12f64886505253e765b82458710a949e34`

Alembic:
`0046`

The live Stage B operation is intentionally not yet authorized.

## What the future live run will do

Exactly one execution of:

`bash ops/production/retire_telegram_bot.sh`

The accepted harness will:
1. verify canonical checkout/target/host pin;
2. fetch and verify exact production ref/runtime;
3. verify DB/API/worker/health/Alembic and required credential presence;
4. call Bot API `deleteWebhook(drop_pending_updates=true)` exactly once;
5. verify webhook is empty with exactly one `getWebhookInfo`;
6. atomically clear only:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_BOT_USERNAME`
   - `TELEGRAM_WEBHOOK_SECRET`
   - `TELEGRAM_WEBHOOK_URL`
7. recreate only API + worker;
8. verify DB container/volume and all protected settings are unchanged;
9. verify MTProto credentials remain present;
10. verify `TELEGRAM_MTPROTO_AI_ENABLED=false`;
11. verify health PASS and Alembic `0046`.

The bot account itself is NOT deleted by this harness.

## Authorization state

LIVE STAGE B IS NOT YET AUTHORIZED.

Do not run the harness until the human explicitly authorizes the irreversible retirement action.

Acceptable explicit authorization text:

`Разрешаю live Stage B retirement Telegram Bot API`

After that authorization, run the accepted wrapper exactly once and return the complete sanitized output.

## Failure handling

If the wrapper/harness blocks or returns failure:
- do not retry;
- do not use direct SSH;
- do not call Bot API manually;
- do not restore/reconfigure the webhook;
- do not restore Bot secrets;
- return the sanitized output and STOP.

## Not authorized

- BotFather/account destruction;
- Stage C source/schema cleanup;
- MTProto changes;
- AI enablement;
- deploy/rollback/ref changes unrelated to this harness.

`CURRENT_TASK.md` is the source of active authorization.
