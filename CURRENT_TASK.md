# Current task — Telegram Bot API M4BP1: Stage C non-destructive code/config cleanup

## Status

Telegram Bot API retirement is COMPLETE through external/runtime lifecycle:

- Bot ingress/link/send behavior retired in production;
- webhook deleted and verified empty;
- Bot runtime credentials cleared;
- production health and Alembic 0046 verified;
- Telegram bot account destroyed through BotFather;
- MTProto is the sole live Telegram transport.

Historical Bot-derived canonical objects and legacy Bot DB schema remain intentionally preserved.

## Goal

Remove dead Bot-only application/config/UI surfaces now that the bot no longer exists, without deleting historical data or performing destructive schema changes.

This is CODE ONLY. No deploy or production mutation.

## Required cleanup

### Backend routes and live services

Remove dead live Bot API surfaces, including as applicable:

- legacy `POST /telegram/link`;
- legacy `POST /integrations/telegram/webhook`;
- Bot-only router registration that is now unused;
- Bot-only `TelegramHttpTransport`;
- Bot-only webhook/link runtime services;
- Bot-only CLI webhook registration utility;
- legacy Bot send/reply branches that can no longer execute.

Do not remove generic historical-read behavior required to display old Bot-derived canonical objects.

### Configuration

Remove live Bot runtime configuration dependencies from application/config and Compose:

- `TELEGRAM_BOT_TOKEN`;
- `TELEGRAM_BOT_USERNAME`;
- `TELEGRAM_WEBHOOK_SECRET`;
- `TELEGRAM_WEBHOOK_URL`.

Remove them from:
- Settings/config declarations;
- `.env.example`;
- Compose API/worker environment declarations;
- any active runtime readiness/config checks.

Do not mutate production `.env` in this task. Empty legacy lines may remain there until a separately authorized environment hygiene step if desired.

### Client

Remove remaining dead Bot API client models/calls/tests that survived Stage A, such as:
- `linkTelegram()`;
- legacy Bot connection DTO/state if no longer used;
- obsolete Bot help/status text or tests.

Keep the MTProto account section and all MTProto behavior unchanged.

### Historical compatibility

Preserve:
- historical Bot-derived objects;
- their existing provider/external IDs;
- `telegram_accounts` and `telegram_link_states` tables/models if removing them would require migration or could break historical compatibility;
- Alembic migration `0039_telegram_accounts.py`;
- all old migrations;
- any pure normalization/data-reading code demonstrably required for historical objects.

No migration `0047`.

If a Bot-only model/store is provably unreferenced after cleanup but removing the model would imply schema semantics or complicate historical inspection, leave it in place and mark it legacy rather than deleting it.

### Communication behavior

For historical Bot-derived Telegram objects:
- do not silently reroute through MTProto;
- mutation/send/reply must remain unavailable/fail closed;
- ordinary Inbox/object reading must remain functional.

MTProto send/reply/edit/delete/mark-read remains unchanged.

## Required tests

Add/update focused tests proving:

1. legacy Bot link route no longer exists / is not registered;
2. legacy Bot webhook route no longer exists / is not registered;
3. no active runtime code can construct/use Bot HTTP transport;
4. historical Bot-derived Telegram objects remain readable through generic object/Inbox paths;
5. historical Bot-derived mutation/send remains unavailable and never routes to MTProto;
6. MTProto send path still works;
7. Bot config fields are absent from active Settings/Compose/.env.example;
8. MTProto config remains present;
9. Flutter has no Bot link/connection client path;
10. MTProto account UI remains present.

Run:
- relevant backend focused tests;
- relevant MTProto tests;
- Python compile;
- Ruff;
- Flutter focused tests;
- Flutter analyzer for changed client code;
- `git diff --check`.

## Scope discipline

Do NOT:
- delete historical Bot-derived canonical objects;
- rewrite external IDs;
- drop `telegram_accounts` / `telegram_link_states`;
- add migration `0047`;
- edit old migration files;
- change production `.env`;
- deploy;
- move production ref;
- call Telegram/Bot API;
- modify MTProto scope/session/sync;
- enable MTProto AI.

## Authorization

AUTHORIZED:
- local Stage C code/config/UI/test cleanup;
- update `PROJECT_STATE.md`;
- commit and push canonical `main`.

NOT AUTHORIZED:
- any production action;
- destructive DB/schema cleanup.

## Required report

Return:
- implementation commit SHA;
- files removed/changed;
- exact dead Bot surfaces removed;
- exact legacy schema/data pieces intentionally retained;
- historical-read / mutation-fail-closed evidence;
- MTProto regression evidence;
- backend/client test results;
- compile/Ruff/analyzer/diff-check results;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BP1_STAGE_C_CODE_CLEANUP_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
