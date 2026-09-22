# Current task — Telegram Bot API M4BO1: human BotFather bot-account destruction

## Status

Human explicitly authorized destruction of the retired Telegram bot account through @BotFather.

Secretary Stage B retirement is already COMPLETE / PRODUCTION ACCEPTED.

Current production runtime/ref:
`fe151f12f64886505253e765b82458710a949e34`

Alembic:
`0046`

## Authorized human action

Using Telegram's official @BotFather only:

1. Open the verified `@BotFather` chat.
2. Send `/deletebot` (or use `/mybots` -> select the retired Secretary bot -> delete bot).
3. Select exactly the retired Secretary Bot API bot.
4. Review BotFather's irreversible deletion warning.
5. Confirm deletion only for that bot.

Telegram documents `/deletebot` as deleting the bot and freeing its username; the action cannot be undone.

## Critical boundary

Do NOT:
- delete the human Telegram account;
- delete or log out the MTProto user account/session;
- change Secretary production `.env`;
- restore Bot credentials/webhook;
- deploy/rollback/move refs;
- delete historical Bot-derived objects;
- delete legacy Bot tables/migrations;
- change MTProto scope/sync;
- enable MTProto AI.

## Required report

After BotFather confirms deletion, report only:

`TELEGRAM_BOT_ACCOUNT_DELETED`

If BotFather does not confirm deletion or presents an unexpected blocker, do not improvise; report the blocker text without secrets and STOP.

Then Architect will record M4BO1 completion and open Stage C cleanup separately.

`CURRENT_TASK.md` is the source of active authorization.
