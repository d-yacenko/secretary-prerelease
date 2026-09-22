# Current task — Telegram Bot API M4BP1R: close Stage C compatibility regressions

## Status

M4BP1 implementation commit:
`0789fc1c21b643667be0e20e328d14d14f32438f`

Architect review: CODE DIRECTION ACCEPTED, but NOT YET ACCEPTED FOR DEPLOY.

Current production runtime/ref remains:
`fe151f12f64886505253e765b82458710a949e34`

Alembic:
`0046`

No migration exists in the candidate.

## Goal

Make a narrow compatibility/test/documentation correction. Do not broaden product behavior.

## Required corrections

### 1. Historical Bot-derived Inbox/read regression

Add a focused DB-independent regression proving a legacy Bot-derived canonical Telegram object remains consumable by the generic Inbox/read presentation path after Stage C.

Use an in-memory/model-level object or existing pure helper where possible.

At minimum prove for a legacy object with:
- `provider="telegram"`;
- `kind="chat_message"`;
- `origin="source"`;
- legacy Bot metadata with no `transport="mtproto"`;

that:
- the generic Inbox presentation/projection path can produce the expected source item without importing any retired Bot runtime module;
- the MTProto visibility predicate is explicitly non-restrictive for non-MTProto Telegram objects (a compile/static assertion is acceptable for this part if a DB is unavailable).

Do not reintroduce Bot runtime code.

### 2. Strengthen active-config regression

In the Stage C test:
- assert lowercase Python fields are absent from `app/core/config.py`:
  - `telegram_bot_token`
  - `telegram_bot_username`
  - `telegram_webhook_secret`
  - `telegram_webhook_url`;
- assert uppercase env names are absent from Compose and `.env.example`;
- retain positive assertions that MTProto config remains.

### 3. Mark retained Bot stores as legacy-only

The retained Bot-only persistence helpers are historical compatibility artifacts, not live integration surfaces.

Add clear module/class documentation to:
- `backend/app/connectors/telegram/account_store.py`;
- `backend/app/connectors/telegram/link_state.py`;

stating they are legacy Bot API persistence helpers retained only for historical/schema compatibility and must not be used to re-enable live Bot linking/ingress.

No behavior change and no schema change.

### 4. Clean duplicate MTProto comment

Remove the duplicated adjacent Telegram MTProto comment in `.env.example`.

No other config change.

## Preserve

Do not change:
- historical Bot-derived objects;
- legacy DB models/tables/migrations;
- `TelegramSendRoute` compatibility parsing;
- fail-closed historical Bot send behavior;
- MTProto send/reply/edit/delete/mark-read;
- MTProto scope/session/sync;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- production `.env`.

No migration / no `0047`.

## Validation

Run:
- focused M4BP1 tests;
- any new historical-read regression;
- Python compile;
- Ruff on touched Python;
- relevant Flutter focused tests only if client files change;
- `git diff --check`.

DB-backed tests remain optional if the known local PostgreSQL hostname is unavailable; do not use production DB.

## Authorization

AUTHORIZED:
- local test/documentation/cosmetic corrections above;
- update `PROJECT_STATE.md`;
- commit/push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- deploy/ref movement;
- provider calls;
- production env changes;
- schema/data mutation;
- Stage C destructive cleanup;
- MTProto behavior changes.

## Required report

Return:
- corrective commit SHA;
- files changed;
- historical Bot generic-read regression description/result;
- strengthened config assertions;
- legacy-only store marking;
- validation results;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BP1R_STAGE_C_COMPAT_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
