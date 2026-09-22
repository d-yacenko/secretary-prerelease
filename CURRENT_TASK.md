# Current task — Telegram Bot API M4BI1: Stage A deploy awaiting explicit human authorization

## Status

M4BH1 Stage A behavioral isolation is CODE ACCEPTED.

Accepted release candidate:
`fe151f12f64886505253e765b82458710a949e34`

Current production / rollback:
`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

Expected Alembic:
`0046`

The production -> candidate comparison is a fast-forward and contains no Alembic/migration changes.

## Accepted Stage A semantics

- legacy `POST /telegram/link` returns HTTP 410 before DB/provider work;
- legacy Telegram webhook returns HTTP 410 before auth/DB/provider dispatch;
- Bot-derived Telegram send/reply fails closed before Bot transport/provider/idempotency writes;
- MTProto send/reply routing remains live and unchanged;
- `/connections` reports legacy Bot transport inactive;
- generic Flutter Bot connection UX is retired;
- MTProto account UX remains;
- historical Bot-derived objects and legacy Bot tables remain preserved;
- Bot credential/config fields remain present for now;
- no schema change / no `0047`;
- `TELEGRAM_MTPROTO_AI_ENABLED=false` behavior remains unchanged.

## Authorization state

PRODUCTION DEPLOY IS NOT YET AUTHORIZED.

Do not:
- move `production` ref;
- run `ops/production/deploy.py`;
- change production env;
- delete/change the Telegram webhook at Telegram;
- call Bot API/provider;
- remove Bot credentials;
- perform Stage B cleanup.

Await explicit human authorization such as:

`Разрешаю production deploy M4BH1`

After explicit authorization, Architect will promote the exact accepted release to `production` and authorize one normal schema-neutral deploy through the canonical harness.

`CURRENT_TASK.md` is the source of active authorization.
