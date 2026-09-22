# Current task — Telegram Bot API M4BM1: build read-only post-retirement verifier

## Status

M4BL1 second live Stage B retirement completed all irreversible retirement actions and failed only on the immediate final application health check.

Confirmed live effects:
- exact production runtime/ref remained
  `fe151f12f64886505253e765b82458710a949e34`;
- Alembic preflight `0046`;
- Bot webhook deleted;
- webhook read-back confirmed empty;
- exactly two Telegram network calls total;
- four Bot env settings cleared;
- API + worker recreated;
- DB container unchanged;
- DB volume unchanged;
- non-Bot env unchanged;
- Bot settings empty;
- MTProto credentials preserved;
- credential key preserved;
- DB credential preserved;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`.

Final result:
`FAILURE_STAGE=STAGE_6_APP_HEALTH`

Do NOT rerun the retirement harness and do NOT restore webhook/Bot secrets.

## Goal

Build a production-compatible READ-ONLY post-retirement verifier that determines whether the final health failure was only startup timing and proves the final Stage B state without any provider call or mutation.

This task is CODE/TEST ONLY. Do not run it against production in M4BM1.

## Required verifier

Add a committed verifier under `ops/production/` following the established target/pin/SSH pattern.

It must perform NO Telegram provider calls and NO production writes.

It must verify:

1. exact production target/host pin;
2. canonical origin/path;
3. fresh `origin/production` exact
   `fe151f12f64886505253e765b82458710a949e34`;
4. current HEAD exact same release;
5. clean tracked worktree;
6. DB/API/worker containers exist and are running;
7. DB container health is healthy;
8. DB container identity and DB volume are only inspected, never changed;
9. the four Bot settings are empty in production `.env`;
10. the four Bot settings are empty in resolved Compose env for API+worker;
11. the four Bot settings are empty in the actual running API+worker container environments;
12. `TELEGRAM_API_ID` is positive and `TELEGRAM_API_HASH` is nonempty;
13. API and worker actual/resolved MTProto credentials match the `.env` snapshot;
14. `SECRETARY_CREDENTIAL_KEY` and DB credential invariants are present/consistent without printing values;
15. `TELEGRAM_MTPROTO_AI_ENABLED=false`;
16. application health with bounded retry equivalent to canonical deploy semantics: up to 30 attempts with 2-second spacing;
17. Alembic exact `0046 (head)`;
18. no provider/network call to Telegram;
19. no DB write;
20. no env write;
21. no service recreation/restart.

## Protocol

Emit sanitized aggregate/status markers only. Include at minimum:

```
M4BM1_BEGIN=true
REMOTE_HEAD_PASS=true
REMOTE_PRODUCTION_REF_PASS=true
REMOTE_WORKTREE_CLEAN=true
DB_RUNNING_PASS=true
API_RUNNING_PASS=true
WORKER_RUNNING_PASS=true
DB_HEALTH_PASS=true
BOT_ENV_EMPTY_PASS=true
BOT_COMPOSE_ENV_EMPTY_PASS=true
BOT_CONTAINER_ENV_EMPTY_PASS=true
MTPROTO_CREDENTIALS_PRESERVED_PASS=true
CREDENTIAL_KEY_PRESERVED_PASS=true
DB_CREDENTIAL_PRESERVED_PASS=true
TELEGRAM_MTPROTO_AI_DISABLED_PASS=true
HEALTH_PASS=true
ALEMBIC_0046_PASS=true
TELEGRAM_NETWORK_CALLS=0
DB_WRITES=0
ENV_WRITES=0
SERVICE_RECREATIONS=0
M4BM1_TERMINAL=success
M4BM1_END=true
```

On failure emit a deterministic sanitized `FAILURE_STAGE`, exception class, zero mutation/provider counters, and terminal failure.

## Health semantics

Reuse the canonical deploy health retry behavior:
- up to 30 attempts;
- 2 seconds between attempts;
- no service restart/recreate during retry;
- do not print HTTP body or raw errors.

The verifier is observational only.

## Required tests

Add focused tests covering at minimum:
- target/ref/HEAD/worktree fail-closed;
- Bot env nonempty -> failure;
- actual API/worker container Bot env nonempty -> failure;
- missing/mismatched MTProto credentials -> failure;
- AI flag true -> failure;
- health succeeds after several mocked failures without any mutation;
- health exhausts 30 attempts -> deterministic failure;
- exact `alembic current` contract;
- source/static assertion that no `deleteWebhook`, `getWebhookInfo`, provider URL, Compose `up`, restart, or env write path exists;
- protocol parser accepts only sanitized bounded output.

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
- live verifier execution;
- Telegram/Bot API/provider calls;
- env mutation;
- DB mutation;
- service restart/recreate;
- deploy/rollback/ref movement;
- webhook/Bot secret restoration;
- BotFather/account destruction;
- Stage C cleanup;
- MTProto behavior changes;
- AI enablement.

## Required report

Return:
- commit SHA;
- files changed;
- verifier protocol;
- health retry mechanism;
- proof of zero provider/write/recreate capabilities;
- focused tests/compile/Ruff/Bash/diff-check results;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BM1_POST_RETIREMENT_VERIFIER_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
