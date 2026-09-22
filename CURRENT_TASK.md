# Current task — Telegram Bot API M4BO1: Bot account destruction awaiting explicit human authorization

## Status

Telegram Bot API Stage B retirement is COMPLETE / PRODUCTION ACCEPTED.

Current production runtime/ref:
`fe151f12f64886505253e765b82458710a949e34`

Alembic:
`0046`

Accepted final Stage B state:
- Bot webhook deleted and verified empty;
- four Bot runtime settings are empty;
- Bot ingress/link/send paths are retired in production application code;
- DB/API/worker are healthy;
- MTProto credentials are preserved;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- MTProto is the sole live Telegram transport;
- historical Bot-derived objects remain readable/preserved;
- legacy Bot DB schema remains preserved for now.

## Next product step

The remaining external Bot lifecycle step is destruction of the Telegram bot account itself through the human-controlled Telegram/BotFather flow.

This is irreversible and is separate from Stage B runtime retirement.

## Authorization state

BOT ACCOUNT DESTRUCTION IS NOT YET AUTHORIZED.

Do not delete/revoke/destroy the bot account until the human explicitly authorizes it.

Acceptable explicit authorization text:

`Разрешаю удалить Telegram bot account через BotFather`

After explicit authorization, Architect will provide the exact human-only BotFather action and required confirmation report.

## Scope boundary

Bot account destruction must NOT:
- restore or alter Secretary Bot credentials;
- change production `.env`;
- call Secretary deploy/rollback;
- delete historical Bot-derived objects;
- delete legacy Bot DB tables/migrations;
- change MTProto account/session/scope behavior;
- enable MTProto AI.

Stage C source/UI/config/schema cleanup is a separate later task.

`CURRENT_TASK.md` is the source of active authorization.
