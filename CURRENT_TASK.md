# Current task — Prepare production migration harness for Assistant conversations 0046 -> 0047

The user has explicitly authorized production deployment of the accepted persistent/resumable Assistant conversations stage.

This task is ONLY the safety preparation step. Do not connect to production, do not move `origin/production`, do not run a production migration, and do not deploy in this task.

Accepted application release SHA to be deployed later: `296b4735f9473ea60ef22f1827ed94260603128e`.
Current production / rollback SHA: `42db393be50a4c3f20ce86dadc280d77bada3959`.
Current production Alembic: `0046`.
Target Alembic: `0047`.

## Why a dedicated harness is required

`ops/production/deploy.py` intentionally rejects schema-changing releases.
The existing `migrate_deploy.py` / `remote_migrate_deploy.py` are intentionally restricted to the historical Telegram `0041 -> 0046` rollout and contain MTProto-specific rollback guards. Do not weaken or repurpose that historical contract.

Create a dedicated, narrowly-scoped production migration entrypoint for exactly this rollout, preferably:
- `ops/production/migrate_assistant_0047.py`
- `ops/production/remote_migrate_assistant_0047.py`

Reuse shared safe helpers from `deploy.py` where appropriate. Do not add a generic migration override.

## Local harness invariants

The new local entrypoint must fail closed unless all are true:
- canonical clean `main` checkout and canonical origin;
- exact authorized release SHA is `296b4735f9473ea60ef22f1827ed94260603128e`;
- exact rollback SHA is `42db393be50a4c3f20ce86dadc280d77bada3959`;
- rollback is an ancestor of release;
- transition is exactly `0046 -> 0047`;
- Alembic delta between rollback and release is exactly one added file:
  `backend/alembic/versions/0047_assistant_conversations.py`;
- no Alembic env/config/template changes are present;
- existing pinned production target / host-key contract is reused unchanged.

## Remote rollout semantics

The remote helper must be fail closed and preserve the existing production identity contract.

Preflight before downtime:
- exact `/opt/secretary` path and canonical Git origin;
- clean tracked production checkout;
- `origin/production` equals the authorized release SHA;
- runtime HEAD equals the rollback SHA;
- `.env` exists;
- db/api/worker exist; DB healthy; api/worker running; current health passes;
- DB container identity, DB volume identity, and `.env` hash recorded;
- api/worker resolve matching non-empty DB credentials and `SECRETARY_CREDENTIAL_KEY`;
- direct DB TCP auth succeeds;
- DB Alembic revision is exactly `0046`;
- no new Telegram/provider environment requirement is introduced.

Rollout:
1. switch checkout to exact release SHA;
2. resolve release Compose environment and prove DB/credential settings are unchanged;
3. build only api/worker before downtime;
4. stop api/worker and prove stopped;
5. preserve DB container/volume/env identity;
6. run exactly `alembic upgrade 0047` using the release api image with `--rm --no-deps`;
7. verify DB revision directly is exactly `0047`;
8. recreate only api/worker with `--no-deps --force-recreate`;
9. verify DB container/volume/env unchanged and api/worker recreated/running;
10. verify health and Alembic `0047`;
11. print only sanitized deployment facts.

## Rollback semantics

Before release runtime has started, a failed rollout may downgrade `0047 -> 0046` and restore the rollback application.

After the release application has started, a downgrade is allowed ONLY when BOTH new tables are directly proven empty:
- `assistant_messages`
- `assistant_conversations`

If either table is non-empty, the emptiness query fails, or safety cannot be proven:
- stop/keep api and worker stopped;
- do not downgrade or delete Assistant conversation data;
- emit a sanitized `BREAK_GLASS_REQUIRED=true` style marker;
- return failure.

If safe downgrade is allowed:
- run exactly `alembic downgrade 0046`;
- verify DB revision `0046`;
- restore exact rollback SHA application;
- preserve DB container/volume/env identity;
- require health PASS.

Never recreate DB, never change the DB volume, never edit production `.env`, never delete conversation rows to make rollback possible.

## Proof

Add focused tests for the new harness covering at minimum:
- exact authorized SHAs and `0046 -> 0047` only;
- exact one-file migration delta;
- rejection of extra/modified Alembic infrastructure;
- pre-cutover downgrade path;
- post-cutover rollback allowed only with both Assistant tables empty;
- non-empty/unknown Assistant table state blocks destructive downgrade;
- DB/container/env preservation checks remain enforced.

Update `docs/deploy.md` with the dedicated Assistant `0046 -> 0047` command/contract, without altering the historical Telegram migration path.

Run the focused ops/production harness tests, Python compile/Ruff for touched files, and `git diff --check`.

When complete:
- record exact checks/results and implementation SHA in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- DO NOT deploy or touch production in this task.
