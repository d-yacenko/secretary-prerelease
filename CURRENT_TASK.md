# Current task — Production Migration Rollout M2 readiness gate

## Status

- Telegram A4.1–A4.4: ACCEPTED.
- Telegram Integration Gate I1: ACCEPTED.
- Production Line Reconciliation R1: ACCEPTED.
- Production Migration Rollout M1: **ACCEPTED** at exact final SHA `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`.
- M1 is integrated into `main`.
- Production branch/runtime remains exact rollback SHA `5cce4b57b14e0052a038acae1354a2821a2bb77b`.
- Production DB Alembic remains `0041`.
- Accepted release schema target is exact `0046`.
- **M2 authorizes production readiness inspection only. It does NOT authorize moving `production`, stopping/recreating services, running production Alembic, or deploying.**

## Objective

Prove that production is ready for the separately authorized migration cutover without creating branch/runtime divergence if readiness fails.

The migration-bearing release includes accepted Telegram MTProto code and exact migration chain:

`0041 -> 0042 -> 0043 -> 0044 -> 0045 -> 0046`.

The accepted M1 harness is:

- `ops/production/migrate_deploy.py`
- `ops/production/remote_migrate_deploy.py`

M2 must not modify their runtime semantics unless a concrete readiness blocker is discovered and Architect separately authorizes a correction.

## Exact release candidate

For this readiness phase, the candidate release code SHA is:

`917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`

Rollback/runtime SHA:

`5cce4b57b14e0052a038acae1354a2821a2bb77b`

Schema transition:

`0041 -> 0046`

Do not substitute another SHA.

## Authorized production actions

M2 may use strict verified SSH to the canonical production target from `ops/production/target.json` for **read-only/readiness inspection**.

Allowed:

1. verify SSH host key using the committed exact fingerprint;
2. inspect canonical production checkout/origin/cleanliness;
3. run non-mutating Git fetch;
4. inspect current production branch/ref/runtime facts;
5. inspect Docker service/container state;
6. perform health probes;
7. perform DB TCP `SELECT 1`;
8. query `alembic_version`;
9. hash `/opt/secretary/.env` internally without printing the hash;
10. resolve candidate release Compose configuration against the existing production `.env` without printing raw Compose config or secret values;
11. verify required release runtime environment values by presence/validity only;
12. use a temporary detached Git worktree or equivalent non-runtime-affecting checkout to inspect candidate release Compose, then remove it cleanly.

## Forbidden production actions

M2 MUST NOT:

- move `origin/production`;
- change local production checkout persistently;
- stop/restart/recreate api, worker, or db;
- run `docker compose up`, `stop`, `restart`, `rm`, or destructive service commands;
- run production Alembic upgrade/downgrade;
- change DB schema or rows;
- change `/opt/secretary/.env`;
- rotate/change `SECRETARY_CREDENTIAL_KEY`;
- create/replace Telegram credentials;
- expose any secret value;
- run the migration deployment harness;
- deploy application code.

Any accidental mutation is a failure and must be reported immediately.

## Required readiness checks

Before reporting READY, prove all of the following:

### Git/runtime identity

- production repository path is exactly `/opt/secretary`;
- origin URL is canonical;
- tracked worktree is clean;
- current checkout is exact rollback/runtime SHA `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- `origin/production` is still exact rollback SHA;
- candidate release SHA `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb` resolves after fetch;
- rollback SHA is an ancestor of release SHA.

### Existing runtime

- db/api/worker all exist;
- db is running and healthy;
- api and worker are running;
- health endpoint `http://127.0.0.1:18080/health` PASS;
- DB TCP auth `SELECT 1` PASS;
- direct DB Alembic revision is exactly `0041`.

### Current environment invariant

Resolve the **current rollback Compose** with explicit:

`--env-file /opt/secretary/.env -f infra/compose.yaml -f infra/compose.deploy.yaml`

Require for api+worker:

- non-empty `POSTGRES_PASSWORD`;
- non-empty `SECRETARY_CREDENTIAL_KEY`;
- matching DB connection fields;
- matching credential key.

Do NOT require Telegram vars from rollback Compose because the deployed rollback Compose does not expose them.

### Candidate release Compose readiness

Without moving `origin/production` and without changing running services, resolve the candidate release Compose against the same exact `/opt/secretary/.env`.

Require for both release api and release worker:

- `TELEGRAM_API_ID` exists, is numeric, and > 0;
- `TELEGRAM_API_HASH` is nonblank;
- api/worker Telegram API ID values match;
- api/worker Telegram API hash values match;
- release DB connection settings exactly equal the rollback-resolved values;
- release `SECRETARY_CREDENTIAL_KEY` exactly equals rollback-resolved value;
- no secret values are printed.

If Telegram runtime credentials are absent/unusable, report NOT READY. Do not modify `.env`.

### No-mutation proof

Capture before/after:

- current checkout SHA;
- `origin/production` SHA;
- db/api/worker container IDs;
- DB volume identity;
- `.env` checksum internally;
- DB Alembic revision.

All must remain unchanged after readiness inspection.

Temporary worktree/path used only for candidate Compose resolution must be removed before completion.

## Output security

Never output:

- PostgreSQL password;
- `SECRETARY_CREDENTIAL_KEY`;
- Telegram API hash;
- raw `TELEGRAM_API_ID` if it would identify the production credential;
- OAuth/API secrets;
- raw Compose config;
- credential hashes/prefixes;
- Telegram/user/account identifiers.

Allowed output is booleans, PASS/FAIL markers, exact Git SHAs, Alembic revision, health status, and non-sensitive invariant facts.

## Completion report

Return:

- exact starting local main SHA;
- exact candidate release SHA;
- exact production runtime/checkout SHA observed;
- exact `origin/production` SHA observed;
- SSH fingerprint verification PASS;
- health PASS/FAIL;
- DB TCP auth PASS/FAIL;
- DB Alembic revision;
- rollback Compose environment invariant PASS/FAIL;
- release Compose Telegram readiness PASS/FAIL without values;
- release-vs-rollback DB/key equality PASS/FAIL;
- before/after no-mutation invariant PASS/FAIL;
- confirmation temporary worktree removed;
- confirmation no service stop/restart/recreate, no Alembic write, no DB write, no ref move, no env modification;
- final clean local worktree.

Final marker if all checks pass:

`PRODUCTION_MIGRATION_ROLLOUT_M2_READINESS_READY`

If any required check fails, use:

`PRODUCTION_MIGRATION_ROLLOUT_M2_READINESS_BLOCKED`

and STOP.

## After M2 readiness

Only after Architect independently reviews the exact readiness evidence will a separate M3 authorize:

- exact `production` ref move;
- exact release/rollback/from/to arguments;
- execution of the accepted migration harness;
- post-deployment runtime verification;
- break-glass handling if required.
