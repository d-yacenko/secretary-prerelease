# Current task — Production Migration Rollout M1 harness + local proof

## Status

- Telegram A4.1–A4.4: ACCEPTED.
- Telegram Integration Gate I1: ACCEPTED.
- Production Line Reconciliation R1: ACCEPTED at exact merge SHA `f55bc1f9360384f403e9791f863b9b104d9c6d42`.
- R1 merge parents are exact prior main `1ff97b66d96ec7a82eb62cb9e1c813e1ebdd4866` and production `5cce4b57b14e0052a038acae1354a2821a2bb77b`; Architect independently verified merge stats `0 additions / 0 deletions / no files`, so production hotfix lineage is now in `main` ancestry without changing the already-tested tree.
- Current `main` contains the accepted release code and Alembic head `0046`.
- Production runtime/branch is still `5cce4b57b14e0052a038acae1354a2821a2bb77b`, production DB Alembic `0041 / 0041`.
- **No production deployment or production migration is authorized in M1.**

## Why a separate harness is required

Normal `ops/production/deploy.py` is intentionally schema-neutral and must continue to reject this release because migration infrastructure differs between rollback and release.

Current Compose starts API with `alembic upgrade head`, while worker starts independently. A migration-bearing rollout must not recreate api+worker concurrently and rely on API startup to win a race against worker startup.

The accepted migration chain is:

`0041 -> 0042 -> 0043 -> 0044 -> 0045 -> 0046`

All new schema belongs to Telegram MTProto:

- `0042`: creates MTProto accounts + auth challenges;
- `0043`: creates chat selections;
- `0044`: adds history cursors to selections;
- `0045`: creates sync folders;
- `0046`: adds `manual_selected` / `scope_active` and allows `private` peer kind.

Important rollback invariant: `0046` downgrade restores the old check constraint allowing only `group/supergroup`. Automatic schema downgrade after live cutover is therefore forbidden if any new MTProto data exists; it could fail or destroy newly-created Telegram state.

## Objective

Implement and test a separate fail-closed migration-bearing production deployment harness for this release family.

The harness must:

1. preserve the existing production identity/SSH/.env/DB container/DB volume/credential-key contract;
2. require exact rollback and release SHAs and exact Alembic from/to revisions;
3. prove rollback SHA is an ancestor of release SHA;
4. prove the migration delta is exactly the authorized contiguous `0042..0046` chain with no Alembic infrastructure mutation beyond those revision files;
5. build release api/worker before downtime;
6. stop both api and worker before the schema write/cutover window;
7. run the schema migration explicitly to `0046` using the release image and explicit production Compose env-file/files;
8. verify DB revision directly before starting worker;
9. only then recreate/start api + worker;
10. verify health, exact schema, DB identity/volume, `.env` checksum, and recreated app containers;
11. implement safe automatic rollback only while it is provably non-destructive;
12. never rotate or replace `SECRETARY_CREDENTIAL_KEY`.

## Branch

Create and work only on:

`review/production-migration-rollout-m1`

starting from exact current `origin/main` after this authorization bookkeeping.

Do not work directly on `main` or `production`.

## Authorized implementation scope

Expected files:

- `ops/production/migrate_deploy.py` — local migration deployment entrypoint;
- `ops/production/remote_migrate_deploy.py` — streamed remote helper;
- production-deployment contract tests (place with the existing pytest suite, e.g. `backend/tests/test_production_migration_deploy.py`);
- `docs/deploy.md` — document the separate migration path and rollback semantics.

Small test-support-only files are allowed if necessary.

Do NOT change:

- `backend/alembic/versions/0042...0046`;
- any other migration file;
- application/domain/service logic;
- Telegram feature behavior;
- `infra/compose.yaml` / `infra/compose.deploy.yaml` unless Architect separately authorizes a concrete blocker;
- normal `ops/production/deploy.py` schema-neutral rejection semantics.

If implementation truly requires modifying an existing production helper for shared, behavior-preserving utility extraction, keep it minimal and report it explicitly. No broad refactor.

## Local entrypoint contract

`ops/production/migrate_deploy.py` must reuse the canonical committed target and strict SSH host-key contract from the normal deployment harness rather than inventing new host discovery.

Required literal arguments:

- `--release-sha` exact 40-char SHA;
- `--rollback-sha` exact 40-char SHA;
- `--from-alembic 0041`;
- `--to-alembic 0046`.

For this M1 implementation, values other than exact `0041 -> 0046` must fail closed. Do not make an open-ended arbitrary migration runner.

Local preflight must require:

- canonical clean local repository;
- local branch `main` and `HEAD == origin/main` when the harness is actually executed;
- both SHAs resolve;
- rollback SHA `5cce4b57b14e0052a038acae1354a2821a2bb77b` is an ancestor of the authorized release SHA;
- migration delta from rollback to release contains exactly these new revision paths:
  - `backend/alembic/versions/0042_telegram_mtproto_foundation.py`
  - `backend/alembic/versions/0043_telegram_mtproto_chat_selections.py`
  - `backend/alembic/versions/0044_telegram_mtproto_history_state.py`
  - `backend/alembic/versions/0045_telegram_mtproto_sync_folders.py`
  - `backend/alembic/versions/0046_telegram_mtproto_active_scope.py`
- no changes to `backend/alembic/env.py`, `backend/alembic.ini`, `backend/alembic/script.py.mako`, or any other migration revision between rollback and release;
- strict SSH fingerprint match before remote execution.

The normal `deploy.py` must still reject the same release as migration-bearing.

## Remote preflight contract

Before any service stop or schema write, require:

- cwd exactly `/opt/secretary`;
- canonical Git origin;
- clean tracked worktree;
- `/opt/secretary/.env` exists;
- `origin/production` equals the exact Architect-authorized release SHA at execution time;
- current checkout is exact rollback SHA or already exact release SHA;
- existing `db`, `api`, `worker` services exist;
- DB running + healthy;
- current API health PASS while still on old runtime;
- explicit Compose config uses `/opt/secretary/.env` plus both canonical compose files;
- `POSTGRES_PASSWORD` and `SECRETARY_CREDENTIAL_KEY` non-empty for api+worker;
- api/worker DB credentials and credential key match;
- DB TCP auth `SELECT 1` succeeds;
- direct DB Alembic version is exactly `0041` before migration;
- current DB/api/worker container IDs, DB volume identity, and `.env` checksum captured internally;
- Telegram API credential presence is checked without printing values: `TELEGRAM_API_ID > 0` and `TELEGRAM_API_HASH` nonblank for both api and worker. Missing Telegram runtime credentials must fail closed before downtime. Never print the API hash or credential key.

## Cutover sequence

Use the exact production Compose prefix on every compose command:

`docker compose --env-file /opt/secretary/.env -f infra/compose.yaml -f infra/compose.deploy.yaml`

Required order:

1. fetch refs and switch checkout to exact release SHA;
2. build only `api` and `worker` while old production api/worker are still running;
3. verify DB container/volume and `.env` are still unchanged;
4. stop **both** `api` and `worker`;
5. verify both are stopped and DB remains running/healthy/unchanged;
6. run one-off release-image migration with no DB recreate and no dependency startup, targeting **exactly `0046`**, not an unconstrained future `head`;
7. query DB directly and require Alembic exactly `0046`;
8. recreate/start `api` and `worker` with `--no-deps --force-recreate`;
9. verify DB container identity unchanged;
10. verify DB volume identity unchanged;
11. verify `.env` checksum unchanged;
12. verify both api and worker container identities changed from the pre-cutover identities;
13. verify both are running;
14. verify API health;
15. verify direct DB Alembic exactly `0046`;
16. report only sanitized non-secret facts.

The DB service must never be part of an `up`/recreate command.

## Safe rollback semantics

### Failure before live release containers start

If failure occurs after writers were stopped but before live release api/worker have started, automatic rollback MAY:

1. keep api+worker stopped;
2. use the release image/migration code to downgrade database back to exact `0041`;
3. verify DB revision directly equals `0041`;
4. switch checkout to rollback SHA;
5. rebuild/recreate old api+worker only;
6. verify DB container/volume and `.env` unchanged;
7. verify old API health and direct DB revision `0041`.

This path is safe because no release application writers have run against the new MTProto schema.

### Failure after live release containers have started

Immediately stop api+worker before evaluating schema rollback.

Automatic schema downgrade is allowed ONLY if a direct DB guard proves there is **zero persisted MTProto rollout data**. At minimum, require zero rows in all new data-bearing MTProto tables that can exist by `0046`:

- `telegram_mtproto_accounts`;
- `telegram_mtproto_auth_challenges`;
- `telegram_mtproto_chat_selections`;
- `telegram_mtproto_sync_folders`.

Handle a missing table conservatively according to the current Alembic revision; do not treat an unexpected query error as “empty”.

If all relevant tables are present/empty and DB revision is within authorized `0042..0046`, the harness may downgrade to `0041` with writers stopped and restore rollback api/worker.

If ANY new MTProto row exists, or emptiness cannot be proven, the harness MUST NOT run destructive schema downgrade and MUST NOT silently discard data. It must:

- leave api/worker stopped;
- leave DB container/volume and `.env` untouched;
- emit a sanitized explicit marker such as `MIGRATION_ROLLBACK_BLOCKED=post_cutover_mtproto_data`;
- emit `BREAK_GLASS_REQUIRED=true`;
- return failure.

Do not auto-restore a database backup and do not delete/truncate Telegram data.

## Security/output rules

Never print or persist in logs:

- PostgreSQL password;
- `SECRETARY_CREDENTIAL_KEY`;
- Telegram API hash;
- API/OAuth secrets;
- Telegram sessions/auth challenge contents;
- account IDs, user IDs, Telegram IDs, emails;
- raw Compose config;
- raw provider errors containing sensitive text;
- hashes/prefixes of credentials.

Allowed output: exact Git SHAs, Alembic revisions, health PASS/FAIL, boolean invariant markers, non-sensitive container-change booleans, stage names, sanitized exception class/reason.

## Required tests

Implement behavioral tests for at least:

1. malformed SHA/from/to rejected locally;
2. non-ancestor rollback rejected;
3. migration allowlist exactness — extra/missing migration or Alembic infra change rejected;
4. normal `deploy.py` still rejects migration-bearing release;
5. strict target/fingerprint path reused, no host discovery/fallback;
6. remote preflight fails before stop when current DB revision != `0041`;
7. remote preflight fails before stop when Telegram API credentials are absent/unusable;
8. build happens before service stop;
9. both api+worker stop before migration command;
10. migration command targets exact `0046` and cannot recreate DB;
11. worker is not started until direct DB revision check proves `0046`;
12. successful path preserves DB container, DB volume, `.env`, credential-key contract and recreates api+worker;
13. pre-live failure safely downgrades to `0041` and restores rollback app;
14. post-live failure with all MTProto tables empty may safely downgrade + restore;
15. post-live failure with any MTProto data refuses downgrade and emits break-glass marker;
16. query/error uncertainty in rollback guard refuses downgrade;
17. no sensitive values appear in success or failure output.

Tests must not contact production or real SSH hosts.

## Local migration proof

Using only disposable/local development PostgreSQL, prove the exact schema chain:

1. start from a clean/disposable DB at `0041`;
2. `alembic upgrade 0046` -> PASS;
3. verify single head/current `0046`;
4. with new MTProto tables empty, `alembic downgrade 0041` -> PASS;
5. verify current `0041`;
6. upgrade again `0041 -> 0046` -> PASS;
7. verify current/head `0046`.

Also demonstrate the rollback guard rationale without damaging repository state: after inserting minimal valid local-only MTProto data at `0046`, the harness guard must report unsafe/nonempty and refuse downgrade. Do not rely on an actual destructive failing downgrade as the guard implementation.

## Regression verification

From backend/local environment:

- production migration harness tests: all PASS;
- existing production deploy/rollback contract tests if present: PASS;
- Telegram A1-A4.4 suite: PASS (current baseline 137);
- production hotfix suites for Yandex/Google: PASS;
- focused scheduler/queue/worker/source-preference suites: PASS;
- full `pytest -q` with failure/error identity attribution against accepted pre-M1 baseline; M1-only identities must be zero;
- `ruff check app tests --output-format concise` with M1-only violations zero;
- `git diff --check` PASS;
- clean worktree.

Do not fix unrelated baseline pytest/Ruff debt.

## Documentation

Update `docs/deploy.md` to clearly distinguish:

- normal schema-neutral `deploy.py`;
- migration-bearing `migrate_deploy.py`;
- exact M1 from/to guard;
- stop/migrate/verify/start ordering;
- rollback guard and break-glass condition;
- the fact that this documentation defines HOW only and does not authorize execution.

## Scope prohibitions

M1 does NOT authorize:

- SSH to production;
- moving `origin/production`;
- production Compose;
- production Alembic;
- changing `/opt/secretary/.env`;
- generating/rotating Telegram API credentials;
- DB backup/restore on production;
- actual deployment;
- A4.5;
- UI/Flutter;
- Telegram Bot API removal;
- application feature changes;
- new migration `0047`.

## Completion report

Commit and push only to `review/production-migration-rollout-m1` and report:

- starting main SHA;
- implementation commit SHA(s);
- final remote M1 HEAD;
- changed files;
- exact harness sequence implemented;
- exact rollback/break-glass semantics implemented;
- migration files unchanged confirmation;
- harness test result;
- local `0041 -> 0046 -> 0041 -> 0046` proof results;
- nonempty MTProto rollback-guard test result;
- Telegram suite result;
- production hotfix suite result;
- shared queue/worker suite result;
- full pytest counts + M1-only identity count;
- Ruff baseline/M1-only attribution;
- `git diff --check`;
- final clean worktree;
- confirmation no production action occurred;
- final marker exactly:

`PRODUCTION_MIGRATION_ROLLOUT_M1_READY`

Then STOP.

## After M1

Architect will independently review exact code/tests. Only after M1 acceptance will Architect authorize the actual production migration/deployment execution as a separate phase with exact release SHA, rollback SHA, from/to revisions, production ref move, and post-deployment runtime verification.
