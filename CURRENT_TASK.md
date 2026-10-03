# Current task — ACTIVE

## REL1-R0 — prepare fail-closed 0052 -> 0054 production rollout harness

The user explicitly authorized the controlled REL1A production rollout on 2026-10-03.

This task is the mandatory source-only rollout-harness preparation gate before live production mutation. It does **not** itself move production, SSH to production, migrate the production database, deploy API/worker, build/install the human client, or perform human acceptance.

The user's rollout authorization remains the governing authorization for the later controlled rollout stages, provided the exact release/rollback contract below remains unchanged and Architect accepts this harness first.

## Exact authorized later rollout contract

- exact product release SHA: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- exact current production / rollback SHA: `2314bf72101fbd83d50a7b264154d73740e28db1`
- production Alembic before rollout: `0052`
- target Alembic after rollout: `0054`
- exact additive migration files:
  - `backend/alembic/versions/0053_person_role_vocabulary.py`
  - `backend/alembic/versions/0054_person_role_key_width.py`
- exact revision chain:
  - `0053 -> 0052`
  - `0054 -> 0053`

Architect verified before this task:

- release is ahead-only from rollback;
- rollback is the current production runtime/source;
- repository Alembic head at the release is `0054`;
- rollback -> release Alembic delta is exactly the two added files above;
- no earlier Alembic revision or Alembic infrastructure file is part of that delta;
- REL1A / REL1A.1 / REL1A.2 / REL1A.2.1 are source-accepted.

Do not silently substitute a newer `main` SHA as the product release.

## Goal

Add and test one dedicated fail-closed production migration/deploy harness for the exact `0052 -> 0054` REL1A transition, following the existing exact-migration harness pattern used by `migrate_task_layout_0052.py`.

Do not generalize historical migration harnesses and do not weaken `ops/production/deploy.py`.

Preferred local entrypoint:

- `ops/production/migrate_person_roles_0054.py`

Preferred streamed remote helper:

- `ops/production/remote_migrate_person_roles_0054.py`

Equivalent narrowly named files are acceptable.

## Local preflight contract

Before any remote action, the local helper must fail closed unless all are true:

1. it runs from the clean canonical local `main` checkout and `HEAD == origin/main`;
2. exact release and rollback SHAs resolve locally;
3. rollback is an ancestor of release;
4. supplied release/rollback/from/to arguments equal the hard-coded authorized contract;
5. compare rollback -> release changes `backend/alembic` only by **adding exactly** the authorized `0053` and `0054` files;
6. Alembic infrastructure is unchanged:
   - `backend/alembic/env.py`
   - `backend/alembic.ini`
   - `backend/alembic/script.py.mako`
7. migration source at the exact release proves:
   - `0053` revision with down revision `0052`;
   - `0054` revision with down revision `0053`;
8. pinned production target and host-key verification reuse the existing shared production helpers;
9. no host discovery, alternate host probing, guessed credentials, or new private-key material.

The harness source may live on newer `main`; the **production release checkout** later remains the exact product release SHA above.

## Remote rollout behavior to encode

The remote helper is preparation for a later live task. It must accept only:

- rollback runtime SHA + DB Alembic `0052` -> migrate/cut over;
- exact release runtime SHA + DB Alembic `0054` -> idempotent verification;
- every other runtime/revision pair -> fail closed.

For the migrate path encode the established pattern:

1. verify production Git identity/cleanliness and require `origin/production` already equals the exact authorized release;
2. require DB, API, and worker healthy/running;
3. capture and later preserve:
   - DB container identity;
   - DB volume identity;
   - production `.env` checksum;
   - required DB/credential environment equality between API and worker;
4. authenticate to DB and require current revision exactly `0052`;
5. switch production checkout to the exact release SHA;
6. require the release Compose environment not to change DB/credential settings;
7. build release `api` and `worker` images while old app containers continue serving;
8. stop only `api` and `worker`;
9. require them stopped and DB still healthy/unchanged;
10. run exactly `alembic upgrade 0054` through the release API image with `--rm --no-deps`;
11. require DB revision exactly `0054`;
12. verify the exact role schema structure and pre-runtime emptiness below;
13. recreate only `api` and `worker`;
14. require both to be newly recreated, running, and healthy;
15. require exact release checkout + Alembic `0054`;
16. require DB container, DB volume, and `.env` unchanged throughout.

Never include `db` in an `up` or recreate operation.

## Required 0054 structure verification

After migration and before starting the release runtime, deterministically prove at least:

### `person_role_terms`

- table exists;
- required columns exist:
  - `id`
  - `user_id`
  - `display_text`
  - `normalized_key`
  - `created_at`
  - `updated_at`
- `display_text` remains VARCHAR(120);
- `normalized_key` is VARCHAR(360);
- named checks exist:
  - `ck_person_role_terms_display_text`
  - `ck_person_role_terms_normalized_key`
- unique constraint `uq_person_role_terms_user_key` exists;
- index `ix_person_role_terms_user_id` exists;
- user FK exists with the expected RESTRICT behavior or an equivalently strong deterministic FK check.

### `person_role_assignments`

- table exists;
- required columns exist:
  - `id`
  - `user_id`
  - `person_object_id`
  - `role_term_id`
  - `context_text`
  - `context_key`
  - `origin`
  - `state`
  - `provenance_kind`
  - `provenance_key`
  - `source_object_id`
  - `created_at`
  - `updated_at`
  - `retracted_at`
- `context_text` remains VARCHAR(200);
- `context_key` is VARCHAR(600);
- named checks exist:
  - `ck_person_role_assignments_state`
  - `ck_person_role_assignments_origin`
  - `ck_person_role_assignments_provenance`
  - `ck_person_role_assignments_context_text`
  - `ck_person_role_assignments_context_key`
  - `ck_person_role_assignments_context_pair`
  - `ck_person_role_assignments_retracted_at`
- FKs to user/person/role term/source object exist with expected RESTRICT behavior or equivalently strong deterministic checks;
- partial unique active-assignment index `uq_person_role_assignments_active` exists and is still scoped to `state = 'active'`;
- index `ix_person_role_assignments_person` exists.

### Pre-runtime emptiness

Immediately after migration and before the new runtime starts require:

- `person_role_terms` row count = 0;
- `person_role_assignments` row count = 0.

This rollout must not seed or manufacture role data.

Do not call the role product endpoints during migration verification.

## Automatic recovery contract

Protect real user data.

If failure occurs after applications are stopped:

### Before 0054 is applied

Restore the exact rollback checkout/runtime with DB still at `0052`. No schema downgrade is needed.

### After `0052 -> 0054` migration but before release runtime is accepted live

Automatic downgrade to `0052` is allowed only after directly proving BOTH role tables are empty.

Then:

- run exact Alembic downgrade to `0052`;
- require DB revision `0052`;
- restore exact rollback application runtime;
- verify health and preserved DB container/volume/`.env`.

### After release runtime starts

Before automatic downgrade:

1. stop API/worker;
2. prove revision is still `0054`;
3. directly prove BOTH:
   - `person_role_terms` empty;
   - `person_role_assignments` empty.

Only then may the harness downgrade to `0052` and restore rollback runtime.

If either table has rows, emptiness cannot be proven, revision is uncertain, or any safety query fails:

- automatic schema downgrade is forbidden;
- do not delete/retract/edit role rows;
- do not drop role tables manually;
- do not truncate;
- keep the application in the safest known stopped state;
- emit an explicit rollback-blocked marker and `BREAK_GLASS_REQUIRED=true`;
- STOP.

No automatic recovery path may lose role facts.

## Idempotent verification path

If production is already exact release + Alembic `0054`:

- perform non-mutating verification only;
- verify release/ref identity;
- verify DB container/volume/`.env` identity;
- verify exact role schema structure and key widths;
- verify Alembic `0054`;
- verify API health;
- later role rows are allowed in this idempotent path;
- do not re-run migration;
- do not recreate containers just for verification.

## Output and credential safety

Preserve existing production harness secrecy rules.

Never print or commit:

- DB password;
- `SECRETARY_CREDENTIAL_KEY`;
- tokens/API keys;
- private SSH material;
- provider credentials;
- raw sensitive environment;
- user role text or Person data.

Only sanitized booleans, counts, revision values, Git/container identity facts, and non-secret paths are allowed.

## Required focused tests

Add a dedicated test module for the new harness, preferably:

- `backend/tests/test_person_roles_0054_migration_harness.py`

Cover at least:

1. exact authorized release/rollback/from/to constants;
2. wrong release rejected;
3. wrong rollback rejected;
4. wrong revision pair rejected;
5. rollback must be ancestor of release;
6. exact two-file additive Alembic delta accepted;
7. extra migration rejected;
8. modified pre-existing migration rejected;
9. Alembic infrastructure change rejected;
10. exact `0053 -> 0052 -> 0054` chain validation, meaning:
    - `0053.down_revision == 0052`;
    - `0054.down_revision == 0053`;
11. pinned target/host-key contract preserved;
12. production ref must equal exact release before remote migration;
13. build occurs before downtime;
14. API/worker are stopped before Alembic migration;
15. structure verification occurs before new runtime start;
16. structure check includes both tables, required columns, indexes/constraints, and 360/600 widths;
17. initial role tables must both be empty before release runtime;
18. pre-cutover empty tables allow safe downgrade;
19. either non-empty table blocks downgrade;
20. unreadable/uncertain emptiness blocks downgrade;
21. post-cutover empty tables allow safe downgrade after app stop;
22. post-cutover non-empty/unreadable tables require break-glass;
23. rollout state machine accepts only rollback+0052 and release+0054;
24. idempotent path is non-mutating and does not require empty role tables;
25. sensitive command failures do not leak secrets;
26. schema-neutral `deploy.py` remains guarded and is not weakened/generalized.

## Additional verification

Run without touching production:

- new migration-harness test module;
- `backend/tests/test_rel1a_person_roles.py`;
- focused migration tests needed to prove `0052 -> 0053 -> 0054` upgrade/downgrade behavior;
- focused role/consolidation regressions if shared migration/model code is touched unexpectedly;
- Ruff for changed Python files;
- Python syntax/compile checks for new ops helpers;
- `git diff --check`.

Update `docs/deploy.md` with a concise dedicated `0052 -> 0054` Person-role migration section. Do not remove or loosen historical rollout contracts.

## Explicitly out of scope in REL1-R0

Do not:

- move `refs/heads/production`;
- SSH to production;
- run production Alembic;
- deploy or recreate production services;
- alter DB/container/volume/`.env`;
- build/install/replace the local Linux client;
- interact with role product APIs in production;
- create Person/role data;
- run real model/provider calls;
- start REL1B, REL1C, REL1D, Organization, or Scheduled Activity.

## Completion protocol

When source preparation is complete:

1. append a compact REL1-R0 result to `PROJECT_STATE.md` with:
   - harness implementation SHA;
   - exact authorized release/rollback/revision contract;
   - changed files;
   - rollback/break-glass semantics;
   - exact tests/lint results;
   - explicit confirmation no production/client/provider action occurred;
2. replace `CURRENT_TASK.md` with HOLD containing:
   - harness implementation SHA;
   - exact product release SHA `6f802d6959aca40758376a83d5bdfcbbd77fc537`;
   - rollback SHA `2314bf72101fbd83d50a7b264154d73740e28db1`;
   - `0052 -> 0054`;
   - tests/checks;
   - no production mutation;
3. commit + push to `main`;
4. STOP.

Do not execute the live rollout from the same task.

After HOLD, Architect must source-review the harness before issuing REL1-R1 live execution.
