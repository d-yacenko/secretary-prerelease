# Current task — Telegram Bot API M4BL1: execute second one-shot live Stage B retirement

## Status

Human explicitly authorized the second live Stage B Telegram Bot API retirement.

Accepted harness code:
`f2e3ef441368d52b7583f0604df127504dbffdf7`

Current production runtime/ref:
`fe151f12f64886505253e765b82458710a949e34`

Expected Alembic:
`0046`

The first live attempt stopped safely before provider work with `TELEGRAM_NETWORK_CALLS=0`; no webhook/env/service mutation occurred.

## Authorization

Authorize exactly ONE execution of:

`bash ops/production/retire_telegram_bot.sh`

The accepted harness may:
1. verify canonical checkout, committed target, host pin, fresh exact production ref, runtime, worktree, DB/API/worker, app health, and Alembic;
2. validate the exact four-key env transform and resolved protected settings before provider work;
3. call Telegram Bot API `deleteWebhook(drop_pending_updates=true)` exactly once;
4. call `getWebhookInfo` exactly once;
5. atomically clear only:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_BOT_USERNAME`
   - `TELEGRAM_WEBHOOK_SECRET`
   - `TELEGRAM_WEBHOOK_URL`
6. recreate only API + worker;
7. prove new API/worker containers are running;
8. prove DB container/volume unchanged;
9. prove non-Bot env and protected/MTProto credentials unchanged;
10. prove Bot settings absent/empty in actual API+worker container environments;
11. prove `TELEGRAM_MTPROTO_AI_ENABLED=false`;
12. prove app health PASS and Alembic exact `0046`.

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

Return the complete sanitized wrapper output including all PASS markers, any failure stage, `TELEGRAM_NETWORK_CALLS`, and terminal marker.

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
