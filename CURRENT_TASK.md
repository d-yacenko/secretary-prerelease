# Current task — Telegram Bot API M4BK1R: harden Stage B preflight/postflight after safe failure

## Status

The first authorized M4BK1 live run stopped safely before any Telegram provider call.

Observed:
- `TELEGRAM_NETWORK_CALLS=0`;
- no webhook deletion;
- no Bot env mutation;
- no service recreation;
- production runtime remains
  `fe151f12f64886505253e765b82458710a949e34`.

The failure occurred between the current `DB_HEALTH_PASS` marker and
`ALEMBIC_0046_PASS`.

## Root cause

The retirement harness currently checks Alembic with `psql` inside the API
container against `127.0.0.1`. This is not the accepted production contract.

Canonical production proof is:

`docker compose ... exec -T api alembic current`

and the output must contain:

`0046 (head)`

## Goal

Correct and strengthen the retirement harness locally before any second live authorization.

This is CODE/TEST ONLY. Do not run against production.

## Required corrections

### 1. Canonical Alembic proof

Replace the custom `psql` Alembic query with the same pattern used by
`ops/production/remote_deploy.py`:

- `compose exec -T api alembic current`;
- require exact expected head marker `0046 (head)`;
- use it both preflight and postflight.

Wrap failures in explicit sanitized stages, for example:
- `STAGE_0_ALEMBIC`;
- `STAGE_6_ALEMBIC_POST`.

Do not emit `STAGE_UNKNOWN` for expected pre/postflight checks.

### 2. Real DB health

The current `DB_HEALTH_PASS` marker is emitted after an HTTP application health request.

Correct this:
- inspect the DB container state directly;
- require running;
- if Docker health metadata exists, require `healthy`;
- only then emit `DB_HEALTH_PASS=true`.

Keep an explicit application HTTP health preflight as a separate checked invariant.
Add a distinct protocol marker if necessary.

### 3. Validate the exact env transform BEFORE provider deletion

Before the first Bot API call:
- read `.env` preserving bytes/newlines;
- prove each of the four Bot keys occurs exactly once and is well formed;
- compute the exact planned neutralized content;
- prove neutralized comparison changes only those four values;
- capture file permissions;
- fail closed before provider calls for missing/duplicate/malformed Bot keys.

After provider deletion/read-back, immediately before the atomic write:
- require current `.env` bytes still equal the preflight snapshot;
- atomically write the precomputed neutralized content;
- preserve permissions.

This avoids deleting the webhook and only afterward discovering a deterministic env-format problem.

### 4. Preflight resolved environment invariants

Before provider deletion, validate the resolved Compose environment for both API and worker:
- four Bot settings are present/nonempty and consistent with the env snapshot;
- `TELEGRAM_API_ID` parses as a positive integer;
- `TELEGRAM_API_HASH` is nonempty;
- API and worker resolve identical MTProto credentials;
- `SECRETARY_CREDENTIAL_KEY` and DB credential invariants are present and consistent;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`.

Do not print values/hashes/prefixes.

### 5. Prove actual API/worker recreation

Snapshot pre-mutation API and worker container IDs.

After `compose up -d --no-deps --force-recreate api worker`:
- require both API and worker IDs changed;
- require both are running;
- require DB container ID unchanged;
- require DB volume unchanged.

Do not merely treat successful Compose exit as proof of recreation.

### 6. Prove actual running-container environment

Postflight must inspect the actual API and worker containers (Docker inspect, in memory only) and prove:
- four Bot settings are empty/absent as intended;
- MTProto credentials equal preflight values;
- protected credential/DB settings equal preflight values;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`.

Compose config may remain an additional check, but it is not sufficient by itself.

Never print secret values.

## Required regression tests

Add mocked/local tests proving at minimum:

1. canonical `alembic current` command is used and `0046 (head)` is required;
2. Alembic preflight failure -> zero provider/env/recreate effects and named stage;
3. DB unhealthy -> zero provider/env/recreate effects;
4. duplicate/malformed/missing Bot key -> zero provider calls;
5. env changes between provider verification and write -> no env overwrite/recreate, sanitized failure;
6. invalid/nonpositive MTProto API ID or API/worker credential mismatch -> zero provider calls;
7. successful path proves old/new API+worker IDs differ;
8. DB ID/volume stays identical;
9. running-container environments, not only Compose config, are checked;
10. actual postflight Bot settings are empty and protected settings preserved;
11. provider bounds remain exactly delete once + read-back once;
12. no DB recreate command exists.

Retain all prior M4BJ1/M4BJ1R tests.

## Validation

Run:
- focused retirement harness tests;
- helper compile;
- bundled helper compile;
- Bash syntax;
- Ruff;
- `git diff --check`.

## Authorization

AUTHORIZED:
- local harness/test changes only;
- update `PROJECT_STATE.md`;
- commit/push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- live harness retry;
- Bot API/provider calls;
- webhook changes;
- production env mutation;
- production service recreation;
- deploy/rollback/ref movement;
- BotFather/account destruction;
- Stage C cleanup;
- MTProto behavior changes;
- AI enablement.

## Required report

Return:
- corrective commit SHA;
- files changed;
- exact Alembic correction;
- DB health correction;
- pre-provider env validation mechanism;
- actual-container recreation/environment proof;
- regression test results;
- compile/Ruff/Bash/diff-check results;
- production SSH=0;
- Bot API/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BK1R_HARNESS_HARDENED`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
