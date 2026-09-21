# Current task — Telegram Bot API M4BG1: retirement dependency audit

## Status

Telegram MTProto ordinary transport, folder-derived scope onboarding, shallow bootstrap, recurring sync, and Inbox visibility are COMPLETE / PRODUCTION ACCEPTED.

Human product direction:
- no cross-transport deduplication work;
- temporary Bot API + MTProto coexistence is acceptable;
- Telegram Bot API will be retired.

Current production runtime/ref:
`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

Alembic:
`0046`

## Goal

Produce an exact dependency inventory and staged removal plan for retiring Telegram Bot API without changing production or deleting code in this task.

This is an AUDIT-ONLY task.

## Required audit

Inspect canonical main and identify every active Bot API dependency, including at minimum:

1. Backend REST routes:
   - legacy Telegram link flow;
   - webhook endpoint;
   - any Bot API-specific send/reply/action endpoint or service.
2. Backend connector/service code:
   - Bot API HTTP transport;
   - webhook handling;
   - business-connection/account/link-state stores;
   - Bot API normalization/materialization paths;
   - mutation/send paths that still depend on Bot API.
3. Configuration:
   - `TELEGRAM_BOT_TOKEN`;
   - `TELEGRAM_BOT_USERNAME`;
   - `TELEGRAM_WEBHOOK_SECRET`;
   - `TELEGRAM_WEBHOOK_URL`;
   - Compose/.env/example/deploy assumptions.
4. Database/schema:
   - Bot API account/link-state tables/models and migrations;
   - whether MTProto or any non-Bot feature references them;
   - whether rows can safely remain historical after runtime retirement.
5. Client/UI:
   - any old Bot link/business-connect controls still reachable;
   - any source/account UI that assumes Bot API.
6. Worker/jobs/assistant/MCP:
   - any Bot API transport calls or Bot-specific object assumptions.
7. Tests/docs/ops:
   - tests that exclusively cover Bot API;
   - webhook registration/setup scripts if any;
   - deployment/runtime checks that require Bot credentials.
8. Canonical persisted objects:
   - confirm Bot-derived and MTProto-derived objects use distinct external IDs;
   - determine whether historical Bot-derived objects can remain readable after Bot API retirement with no live Bot runtime.

## Required output

Write a concise retirement plan in `PROJECT_STATE.md` covering these stages:

### Stage A — code/runtime isolation
What must change so Secretary no longer accepts new Bot API ingress or sends through Bot API, while MTProto remains functional.

### Stage B — production disable
What external/runtime action is required to stop Telegram delivering webhook updates and remove Bot credentials/config safely.

### Stage C — cleanup
Which dead Bot-only code, UI, tests, config, schema/models/migrations can be removed later, and which historical data/schema should be retained for compatibility.

Explicitly identify any blocker that would make immediate Bot API runtime disable unsafe.

## Important architectural constraints

- Do NOT build cross-transport deduplication.
- Do NOT migrate historical Bot-derived objects to MTProto IDs.
- Do NOT delete historical Bot-derived objects.
- Do NOT change MTProto semantics.
- Keep `TELEGRAM_MTPROTO_AI_ENABLED=false`.
- No schema migration / no `0047` in this audit.
- If full schema deletion would require destructive migration, defer it; runtime retirement does not require immediate physical schema removal.

## Authorization

AUTHORIZED:
- repository inspection;
- local static analysis;
- local read-only tests/grep/import tracing as needed;
- update `PROJECT_STATE.md`;
- commit and push the audit result to canonical `main`.

NOT AUTHORIZED:
- production SSH;
- Bot API calls;
- webhook deletion/change;
- Telegram provider calls;
- production env changes;
- code deletion/refactor;
- client behavior changes;
- DB migration;
- deploy/rollback/ref changes;
- Sync/Apply Scope;
- MTProto AI enablement.

## Required report

Return:
- commit SHA;
- exact Bot API dependency inventory;
- retirement stages A/B/C;
- blockers/risks;
- explicit statement whether immediate runtime disable appears safe after a future code-isolation release;
- confirmation production SSH=0;
- provider/Bot API calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BG1_RETIREMENT_AUDIT_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
