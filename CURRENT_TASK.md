# Current task — Telegram Bot API M4BR1: build read-only Stage C post-deploy acceptance verifier

## Status

M4BQ1 Stage C schema-neutral production deploy is COMPLETE / PASS.

Current production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Alembic:
`0046`

Confirmed deploy invariants:
- health PASS;
- DB container unchanged;
- DB volume unchanged;
- production `.env` unchanged;
- API recreated;
- worker recreated;
- no migration / no `0047`.

## Goal

Build a production-compatible READ-ONLY verifier for final Stage C acceptance.

This task is CODE/TEST ONLY. Do not run it against production in M4BR1.

## Required verifier

Add a committed verifier under `ops/production/` following the established target/pin/SSH/read-only patterns.

It must make zero Telegram/provider calls and zero production writes.

Verify:

1. exact production target/host pin;
2. canonical repository/path and fresh exact `origin/production`;
3. current HEAD exact
   `bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`;
4. tracked worktree clean;
5. DB/API/worker containers running and DB healthy;
6. application health PASS with bounded retry;
7. Alembic exact `0046 (head)`;
8. runtime route table does NOT contain:
   - `/telegram/link`
   - `/integrations/telegram/webhook`;
9. runtime route table DOES contain the MTProto routes needed for the live account flow, including at minimum:
   - `/telegram/mtproto/status`;
10. active Settings model has no Bot runtime fields:
   - `telegram_bot_token`
   - `telegram_bot_username`
   - `telegram_webhook_secret`
   - `telegram_webhook_url`;
11. actual API and worker container environments do not contain the four Bot variables;
12. MTProto installation credentials remain present/consistent and `TELEGRAM_MTPROTO_AI_ENABLED=false`;
13. exactly one MTProto account still exists;
14. active MTProto scope remains 28;
15. historical Bot-derived canonical objects still exist, counted only in aggregate:
   - provider `telegram`;
   - kind `chat_message`;
   - metadata transport absent/not `mtproto`;
16. at least one historical Bot-derived object can be resolved through the generic Inbox eligibility/read path without revealing its id/content;
17. historical Bot-derived objects remain ordinary read data only; no provider/send/mutation call is executed by the verifier.

## Sanitized protocol

Include fields equivalent to:

```
M4BR1_BEGIN=true
REMOTE_HEAD_PASS=true
REMOTE_PRODUCTION_REF_PASS=true
REMOTE_WORKTREE_CLEAN=true
DB_RUNNING_PASS=true
API_RUNNING_PASS=true
WORKER_RUNNING_PASS=true
DB_HEALTH_PASS=true
APP_HEALTH_PASS=true
ALEMBIC_0046_PASS=true
LEGACY_BOT_ROUTES_ABSENT_PASS=true
MTPROTO_ROUTE_PRESENT_PASS=true
BOT_SETTINGS_MODEL_ABSENT_PASS=true
BOT_CONTAINER_ENV_ABSENT_PASS=true
MTPROTO_CREDENTIALS_PRESERVED_PASS=true
TELEGRAM_MTPROTO_AI_DISABLED_PASS=true
MTPROTO_ACCOUNT_COUNT=1
ACTIVE_SCOPE_COUNT=28
LEGACY_BOT_OBJECT_COUNT=...
LEGACY_BOT_INBOX_READABLE=true
TELEGRAM_NETWORK_CALLS=0
DB_WRITES=0
ENV_WRITES=0
SERVICE_RECREATIONS=0
M4BR1_TERMINAL=success
M4BR1_END=true
```

Do not print:
- Telegram peer/chat/message/account IDs;
- titles/bodies;
- secret values/hashes/prefixes;
- raw environment;
- raw SQL rows.

## Historical read check

Prefer selecting one legacy Bot-derived object internally, then invoking the same generic Inbox eligibility/read service used by production and outputting only a boolean.

If no legacy Bot-derived object exists, report a deterministic sanitized failure because Stage C preservation cannot then be verified from production state.

Do not construct or execute send/reply/mutation actions.

## Required tests

Add focused tests proving:
- exact ref/HEAD/worktree fail-closed;
- legacy Bot routes absent and MTProto route present;
- Bot Settings fields absent;
- Bot vars absent from actual API/worker env;
- aggregate historical Bot object query excludes `transport="mtproto"`;
- generic Inbox eligibility/read check emits boolean only;
- zero provider/write/recreate capabilities;
- health bounded retry;
- exact Alembic contract;
- strict sanitized output parser rejects unknown lines/fields.

Run:
- focused verifier tests;
- Python compile;
- bundled helper compile if applicable;
- Bash syntax;
- Ruff;
- `git diff --check`.

## Authorization

AUTHORIZED:
- local verifier/test code only;
- update `PROJECT_STATE.md`;
- commit/push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- live verifier;
- Telegram/provider calls;
- DB/env writes;
- service restart/recreate;
- deploy/rollback/ref movement;
- schema/data cleanup;
- MTProto behavior/config changes;
- AI enablement.

## Required report

Return:
- commit SHA;
- files changed;
- verifier protocol;
- historical Bot read-verification mechanism;
- zero-mutation/provider proof;
- test/compile/Ruff/Bash/diff-check results;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BR1_STAGE_C_VERIFIER_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
