# Current task — Telegram MTProto ordinary Inbox UX production deploy awaiting authorization

## Status

Code review ACCEPTED.

Release candidate:
`f31f8f5b704159b7ec903da4c26a590d23f86e78`

Current production / rollback:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Expected Alembic:
`0046`

The candidate is a fast-forward from production. No Alembic/migration or infra files changed.

Production runtime code delta is limited to:
- `backend/app/api/inbox.py`
- `backend/app/services/notification_service.py`
- `backend/app/services/telegram_mtproto_history_service.py`

## Accepted behavior

After deployment:

- future routine inbound MTProto `message_created` materializes only the canonical Inbox/source `chat_message`;
- it does not create a new actionable Notification;
- historical Telegram MTProto `transport_event/message_created` Notification rows remain stored but are excluded from `GET /inbox` unresolved attention;
- generic Notification API behavior remains compatible;
- `message_edited` and `message_deleted` transport notifications remain unchanged;
- ordinary active-scope MTProto source objects remain visible under `Последние входящие`;
- `TELEGRAM_MTPROTO_AI_ENABLED=false` remains unchanged.

No client rebuild is required because this correction is backend-only.

## Authorization state

PRODUCTION DEPLOY IS NOT YET AUTHORIZED.

Acceptable explicit authorization text:

`Разрешаю schema-neutral production deploy f31f8f5b для исправления Telegram Inbox UX`

## After authorization

Architect will:
1. move canonical `production` ref by fast-forward to exact release;
2. authorize canonical `ops/production/deploy.py` with exact release/rollback/Alembic;
3. require normal deployment invariants only.

Do not create another bespoke production verifier.

## Post-deploy human acceptance

Using the already-installed current clients:

1. refresh/reopen Inbox;
2. verify old routine Telegram `message_created` cards disappear from `Требует внимания` without DB cleanup;
3. send one fresh inbound message in an active configured Telegram folder;
4. wait for normal sync or use ordinary client refresh;
5. verify the fresh message appears under `Последние входящие`;
6. verify no corresponding new `Требует внимания` card appears.

No APK/Linux rebuild is necessary unless the existing client itself is unavailable.

## Hard prohibitions before authorization

No:
- production ref movement;
- deploy/rollback;
- production SSH;
- DB cleanup;
- historical Notification mutation/deletion;
- migration;
- Telegram provider test calls by executor;
- MTProto AI enablement.

`CURRENT_TASK.md` is the source of active authorization.
