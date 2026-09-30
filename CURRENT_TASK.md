# Current task — PL1-R0 prepare fail-closed 0052 production rollout harness

Authorized base: `86b40fe8cf367dcbb0487b46bfed7794e0dc0c3f`.
Authorized product release for the later rollout: `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.
Current production/runtime and rollback base: `666683134797948871266e84fd105f0ca0c43476`.
Authorized schema transition for the later rollout: `0051 -> 0052`.

PL1-G4.1 source is accepted. This task prepares and tests the exact production migration harness only. It does **not** deploy, move the production ref, migrate the production database, build a client bundle, or perform human acceptance.

## Goal

Add one dedicated fail-closed production rollout harness for the exact PL1 single-world release and the single additive migration `0052_task_layout_positions.py`, following the repository’s existing exact-migration harness pattern.

Do not generalize the old historical migration harnesses and do not weaken their contracts.

## Exact release contract

The new local and streamed remote helpers must hard-code and reject anything outside:

- release SHA: `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`;
- rollback SHA: `666683134797948871266e84fd105f0ca0c43476`;
- from Alembic: `0051`;
- to Alembic: `0052`;
- exact migration file: `backend/alembic/versions/0052_task_layout_positions.py`;
- revision chain exactly `0052 -> 0051`;
- canonical origin / target / host-key rules already enforced by the production harness infrastructure.

The local helper may live at `ops/production/migrate_task_layout_0052.py` and stream a dedicated helper such as `ops/production/remote_migrate_task_layout_0052.py`.

## Local preflight

Before any remote action, the local helper must fail closed unless all are true:

1. running from the clean canonical local `main` checkout and `HEAD == origin/main`;
2. exact release and rollback SHAs resolve locally;
3. rollback is an ancestor of release;
4. compare rollback -> release changes Alembic only by **adding exactly** `0052_task_layout_positions.py`;
5. Alembic infra files are unchanged;
6. the migration source at the release has `revision = "0052"` and `down_revision = "0051"`;
7. supplied release/rollback/from/to arguments equal the hard-coded authorized contract;
8. pinned production SSH target/host-key verification uses the existing shared production helpers.

No host discovery and no guessed credentials.

## Remote rollout behavior to encode

The remote helper is preparation for a later separately authorized execution. It must support only these states:

- rollback runtime + DB at 0051 -> migrate/cut over;
- exact release runtime + DB at 0052 -> idempotent verification;
- every other checkout/revision combination -> fail closed.

For the migrate path, preserve the proven migration pattern:

1. verify production checkout identity/cleanliness and that `origin/production` already equals the authorized release;
2. verify DB/API/worker are healthy/running and capture DB container identity, DB volume identity, `.env` hash, required DB/credential environment, and current Alembic revision = 0051;
3. switch the production checkout to the exact release;
4. verify release Compose environment does not change DB/credential settings;
5. build release API/worker images while old app containers still run;
6. stop API/worker before migration;
7. run exactly `alembic upgrade 0052` from the release image;
8. verify Alembic = 0052 and exact migration structure before starting the new runtime;
9. recreate API/worker only; DB container, DB volume, and `.env` must remain unchanged;
10. wait for health and verify exact release checkout + Alembic 0052.

## 0052 structure checks

Post-migration verification must prove at least:

- table `task_layout_states` exists;
- table `task_layout_positions` exists;
- expected required columns are present for both tables;
- the expected `ix_task_layout_positions_user_snapshot` index exists;
- named PK/FK/check constraints created by 0052 are present, or an equivalently strong deterministic structural check is performed;
- immediately after migration and before new app runtime starts: `task_layout_states` row count = 0 and `task_layout_positions` row count = 0.

Do not call `GET/PUT /graph/task-layout` during rollout verification because that contract is product behavior and must not create layout state during migration safety checks.

## Automatic recovery contract

The rollout helper must protect real data.

If failure occurs after applications are stopped:

- if 0052 was not applied, restore the rollback checkout/runtime;
- if 0052 was applied but the new runtime has not been accepted live, automatically downgrade to 0051 **only after proving both new layout tables are empty**;
- if failure occurs after new runtime start, first stop API/worker and prove both layout tables are still empty before automatic downgrade;
- if either table contains rows or emptiness cannot be proved, automatic schema rollback is forbidden: do not drop layout data; print an explicit rollback-blocked / BREAK-GLASS-required result; STOP.

The automatic rollback may lose no semantic application data. Task layout rows are presentation state, but do not silently destroy even that state once written.

After a safe downgrade, restore the exact rollback application runtime and verify health + Alembic 0051.

## Idempotent verification

If production is already at the exact release and DB 0052, the remote helper must perform non-mutating verification of release checkout/ref identity, DB container/volume/`.env` identity, migration structure, Alembic 0052, and API health.

It must not re-run migration or recreate containers merely for the idempotent path.

## Tests

Add focused tests for the new harness without touching production. Cover at least:

- exact authorized constants;
- wrong release / rollback / revision pair rejected;
- exact migration delta accepted and extra/modified Alembic files rejected;
- exact revision-chain parsing;
- rollout state machine accepts only rollback+0051 and release+0052;
- structure verification expectations include both tables and required index/constraints;
- rollback safety refuses downgrade if either new table is non-empty or cannot be proven empty;
- idempotent path is non-mutating by contract.

Also run focused backend migration/task-layout tests relevant to 0052, the new ops harness tests, Ruff / syntax checks for changed Python files, and `git diff --check`.

## Explicitly out of scope

- Do not move `refs/heads/production`.
- Do not SSH to production.
- Do not run Alembic on production.
- Do not deploy API/worker.
- Do not build or replace the installed client.
- Do not create Task layout rows in production.
- Do not start PL1-R1 or the human-gate bundle.

## Completion contract

When complete:

- record harness implementation SHA, files, exact authorized release/rollback/revisions, tests/lint results, and known limitations in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-R0 summary;
- commit and push to `main`;
- STOP.

No production mutation is authorized by this task.
