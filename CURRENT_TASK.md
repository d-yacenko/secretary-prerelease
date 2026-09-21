# Current task — Telegram Bot API M4BH1: Stage A behavioral isolation

## Status

M4BG1 dependency audit is COMPLETE / ACCEPTED.

Human product direction:
- no cross-transport deduplication;
- Bot API will be retired;
- historical Bot-derived objects remain preserved;
- MTProto is the canonical live Telegram transport.

Current production runtime/ref:
`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

Alembic:
`0046`

## Goal

Implement Stage A application-level retirement so new Bot API ingress/link/send behavior is disabled in code, while MTProto behavior and historical Bot-derived data remain intact.

This task is CODE ONLY. No deploy or production mutation.

## Required behavior

### 1. Legacy link route

`POST /telegram/link` must no longer create `TelegramLinkState` or return a live bot deep-link.

It must fail closed with a stable retired/unavailable response.

Preferred semantics:
- HTTP 410 Gone or a stable explicit retirement error;
- no DB write;
- no Bot config dependency.

### 2. Bot webhook ingress

`POST /integrations/telegram/webhook` must no longer materialize or mutate Bot-derived data.

It must:
- perform no `TelegramWebhookService.handle_update`;
- perform no account/link/message mutation;
- fail closed in a way compatible with safe retirement.

Choose one stable behavior and test it:
- HTTP 410 Gone, or
- HTTP 200 ignored/retired with zero side effects.

Do not require live Bot credentials for the retired behavior.

### 3. Legacy Bot send/reply

In `CommunicationExternalActionService`:
- MTProto Telegram objects must continue to route through `TelegramMtprotoSendRoute` exactly as today;
- Bot-derived Telegram objects must no longer prepare or execute a Bot API send/reply;
- fail closed with a stable `ToolError` before opening `TelegramHttpTransport`;
- do not create provider-side writes;
- do not silently reroute Bot-derived historical objects through MTProto because there is no cross-transport ID mapping.

### 4. Legacy connection status/UI

The old Business Bot connection UX must no longer appear as an actionable connection flow.

Backend:
- `/connections` must not advertise the Bot transport as configured/connected/can-reply for active use.
- Preserve response compatibility if needed, but return an explicitly retired/inactive Bot status rather than live configured state.

Flutter:
- remove/hide the old Telegram Bot connect button/help/business-status workflow from the generic Connections section;
- keep `TelegramMtprotoAccountSection` intact and unchanged in behavior;
- remove dead client call sites such as `linkTelegram()` if no longer used by live UI, but do not broaden into unrelated API model cleanup unless required by compilation/tests.

### 5. Preserve historical compatibility

Do NOT:
- delete Bot-derived `objects`;
- rewrite Bot external IDs;
- delete `telegram_accounts` or `telegram_link_states`;
- add migration `0047`;
- delete historical materializer/normalizer code merely for cleanup if it is not necessary for Stage A isolation.

Historical Bot-derived objects must remain readable in Inbox/object surfaces under existing generic read behavior.

### 6. MTProto invariants

Must remain unchanged:
- MTProto auth;
- MTProto folder/scope configuration;
- recurring sync;
- shallow bootstrap;
- send/reply/edit/delete/mark-read;
- ordinary Inbox visibility;
- `TELEGRAM_MTPROTO_AI_ENABLED=false` quarantine behavior.

## Testing requirements

Add focused tests proving at minimum:

1. `POST /telegram/link` retired behavior and zero link-state creation.
2. Webhook endpoint retired behavior with zero materialization/account/link mutation.
3. Bot-derived historical Telegram anchor cannot prepare/send through Bot API.
4. MTProto Telegram anchor still prepares and sends through MTProto path.
5. No `TelegramHttpTransport` construction/call occurs for retired Bot send path.
6. `/connections` does not advertise an active Bot connection.
7. Flutter generic Connections section no longer renders Bot connect workflow.
8. MTProto account section remains present.
9. Existing MTProto focused tests continue to pass.

Also run:
- Python compile;
- Ruff;
- relevant backend focused tests;
- relevant Flutter tests / analyzer for changed client code;
- `git diff --check`.

## Scope discipline

This task does NOT remove:
- Bot config fields from `Settings` / Compose / `.env.example`;
- Bot-only connector files;
- Bot-only DB models/tables;
- Bot CLI webhook utility;
- old migrations.

Those are Stage B/C concerns.

## Authorization

AUTHORIZED:
- local code/test changes required for Stage A behavioral isolation;
- update `PROJECT_STATE.md`;
- commit and push to canonical `main`.

NOT AUTHORIZED:
- production SSH;
- Bot API/provider calls;
- webhook deletion at Telegram;
- production env/config changes;
- deployment;
- production ref movement;
- DB migration;
- deleting historical Bot-derived objects;
- schema/table deletion;
- enabling MTProto AI.

## Required report

Return:
- implementation commit SHA;
- files changed;
- exact retired semantics for link/webhook/send/status/UI;
- evidence that MTProto path is unchanged;
- backend/client test results;
- compile/Ruff/analyzer/diff-check results;
- production SSH=0;
- Bot API/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BH1_STAGE_A_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
