# Current task — Telegram Bot API M4BY1: remove monolithic Stage 2 bootstrap and verify running surfaces directly

## Executor handoff

Continue as implementation executor in the canonical repo.

Read:
- `AGENTS.md`
- `CURRENT_TASK.md`
- latest `PROJECT_STATE.md`
- `DECISIONS.md`
- current Stage C verifier/wrapper/tests
- production release code at
  `bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

CODE/TEST ONLY. No production SSH or live verifier.

## Live fact

M4BX1 produced a clean sanitized:

`FAILURE_STAGE=STAGE_2_BOOTSTRAP`

All Stage 0/1 checks passed again and all mutation/provider counters were zero.

Repository review confirms the production release contains:
- `app.core.config.Settings`;
- `app.db.session.SessionLocal`;
- `Object`;
- `TelegramMtprotoAccount`;
- `TelegramMtprotoChatSelection`;
- `RecentSourceService`;
- running `app.main:app`.

Do not guess which import failed.

## Architectural problem

The Stage 2 child still performs too much bootstrap in one fresh Python process:
- SQLAlchemy imports;
- Settings import;
- model imports;
- DB session import;
- full `app.main` import;
- RecentSourceService import;
- route enumeration.

This makes acceptance depend on recreating the whole FastAPI import graph inside a diagnostic subprocess even though the API is already running and healthy.

The verifier should inspect the running surface directly where possible and use narrow children for code/DB checks.

## Goal

Eliminate the monolithic Stage 2 bootstrap so any remaining failure identifies a concrete narrow check in one live run.

Keep the verifier strictly read-only.

## Required design

### A. Runtime route surface: query the running API, do not import `app.main` in DB child

After `APP_HEALTH_PASS`, inspect the running API's read-only route schema, preferably:

`GET http://127.0.0.1:18080/openapi.json`

Requirements:
- bounded timeout/retry consistent with existing local health conventions;
- HTTP GET only;
- require valid JSON object with `paths` mapping;
- prove legacy routes absent:
  - `/telegram/link`
  - `/integrations/telegram/webhook`;
- prove required MTProto route present:
  - `/telegram/mtproto/status`;
- emit no route dump;
- fixed sanitized failure stages for schema fetch/protocol, legacy route presence, and missing MTProto route.

Do not make provider calls.

### B. Active Settings check: separate minimal code check

Check that active `Settings.model_fields` does not contain:
- `telegram_bot_token`
- `telegram_bot_username`
- `telegram_webhook_secret`
- `telegram_webhook_url`.

Use a minimal isolated Python child/import, not `app.main`.

Give import/execution/protocol/Bot-field failures distinct sanitized stages.

No env values printed.

### C. DB/read-state child: narrow imports only

The DB child should import only what its DB/read work actually needs:
- SQLAlchemy query helpers;
- models;
- `SessionLocal`;
- `RecentSourceService`.

Do not import `app.main`.
Do not import `Settings`.

Split import/bootstrap failures at least into useful fixed classes, e.g.:
- SQLAlchemy/import primitives;
- models;
- session/engine;
- RecentSourceService.

Exact names may vary, but one generic `STAGE_2_BOOTSTRAP` must no longer exist on the normal path.

Then preserve the existing fixed read substages:
- account;
- scope;
- legacy aggregate;
- legacy candidates;
- Inbox read;
- candidate bound;
- child execution/protocol.

### D. Prefer actual-package smoke tests over synthetic module mocks

The previous tests installed fake modules into `sys.modules`, which proved protocol behavior but not that the real production import graph is usable.

Add at least one test/subprocess smoke check against the **actual repo backend package** that:
- imports the minimal Settings checker dependencies;
- imports the narrow DB child dependencies;
- does not connect to DB or call providers;
- proves `app.main` is not needed by the DB child.

Keep synthetic fault-injection tests for precise stage mapping, but add actual-package coverage.

If running the exact production image locally is available without production access, an image-level import smoke check is welcome but not required.

### E. Protocol/order

Integrate the new route/settings PASS markers into one canonical emission order.

End-to-end tests must capture real `remote_main()` stdout and prove:
- success transcript parses;
- each new route/settings failure transcript parses;
- DB child failure transcript parses;
- unknown/out-of-order fields still fail closed.

Do not weaken strict parsing.

## Preserve exactly

- production release:
  `bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`;
- Alembic `0046`;
- canonical Git bootstrap;
- Bot runtime env absence contract;
- account count = 1;
- active scope = 28;
- historical Bot aggregate >= 1;
- existential Inbox readability;
- bounded candidate behavior;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- zero Telegram/provider calls;
- zero DB writes;
- zero env writes;
- zero service restart/recreate;
- no identifiers/content/SQL/exception text/env values in output.

## Required regressions

At minimum:
1. running OpenAPI route check succeeds for expected path set;
2. invalid/unavailable OpenAPI is fixed sanitized failure;
3. legacy Bot route present => route-specific failure;
4. MTProto status route absent => MTProto-route-specific failure;
5. Settings minimal import succeeds using actual package;
6. Bot Settings field => settings-specific failure;
7. DB child actual-package imports succeed without `app.main`;
8. DB child source/static assertion contains no `from app.main import app` and no Settings import;
9. each narrow DB import failure maps to fixed sanitized stage;
10. all account/scope/legacy/read/bound substages remain covered;
11. success `remote_main -> parse_output` remains end-to-end green;
12. valid remote failure remains distinct from SSH transport failure;
13. zero-mutation/provider safety tests remain green.

## Validation

Run:
- all focused Stage C verifier tests;
- actual-package import smoke tests;
- Python compile;
- bundled helper compile;
- Bash syntax;
- Ruff;
- `git diff --check`.

Self-review that no normal Stage 2 path can still emit generic `STAGE_2_BOOTSTRAP`.

## Authorization

AUTHORIZED:
- local verifier/wrapper/test redesign described above;
- update `PROJECT_STATE.md`;
- commit/push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- live verifier retry;
- provider calls;
- DB/env writes;
- service restart/recreate;
- deploy/rollback/ref movement;
- schema/data cleanup;
- MTProto product behavior/config changes;
- AI enablement.

## Required report

Return:
- commit SHA;
- files changed;
- new Stage 2 architecture;
- runtime route-check mechanism;
- Settings-check mechanism;
- narrow DB child import map;
- actual-package smoke proof;
- end-to-end protocol proof;
- focused/compile/Ruff/Bash/diff-check results;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BY1_STAGE2_BOOTSTRAP_REMOVED`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
