# Current task — PP1-D1: exact 0050 -> 0051 production migration harness

## State

- People PP1-H1 source is ACCEPTED / SOURCE READY at `07bd8bafdb2f53a6a8475fc2d792687fa373a149`.
- Current `main` before this authorization: `0ca7346ad3dfa39c467954ef7d055221e798f5f6`.
- Production/runtime/origin-production remain exactly `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa`.
- Production Alembic is `0050`.
- Repository Alembic head is `0051`.
- PP1 human acceptance is pending because production does not yet have the corrected backend/schema.
- Normal `ops/production/deploy.py` MUST NOT be used for PP1 because the release adds migration `0051`.

## Goal

Prepare and fully test a dedicated fail-closed production migration harness for exactly:

`application 9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa / Alembic 0050`
→
`application 07bd8bafdb2f53a6a8475fc2d792687fa373a149 / Alembic 0051`

This task prepares the harness only.

**DO NOT perform a live production deployment in PP1-D1.**

## Required files

Add a dedicated pair, named clearly for this transition, for example:

- `ops/production/migrate_person_promotion_0051.py`
- `ops/production/remote_migrate_person_promotion_0051.py`

Add focused tests under `backend/tests/`.

Update `docs/deploy.md` with the exact PP1 `0050 -> 0051` migration contract.

Do not weaken or generalize the existing schema-neutral `deploy.py`.
Do not modify the historical 0047->0050 harness semantics except shared refactoring that is demonstrably behavior-preserving and necessary; prefer no refactor.

## Exact local authorization contract

The new local harness must fail closed unless all of these hold:

- rollback SHA is exactly `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa`;
- release SHA is exactly `07bd8bafdb2f53a6a8475fc2d792687fa373a149`;
- from Alembic is exactly `0050`;
- to Alembic is exactly `0051`;
- rollback is an ancestor of release;
- the Alembic delta between rollback and release is exactly one added migration file:
  `backend/alembic/versions/0051_person_promotion_feedback.py`;
- no earlier migration, Alembic env, ini, or script template changed;
- the 0051 revision declares `revision = "0051"` and `down_revision = "0050"`;
- canonical local checkout/bootstrap invariants pass;
- production target and pinned host key are taken only from `ops/production/target.json`.

The harness must reuse the existing strict host-key / canonical target contract and stream the committed remote helper over SSH. No host discovery, fallback host, alternate repo path, alternate env, or direct ad-hoc production commands.

## Remote preflight contract

Before downtime, require:

- cwd exactly `/opt/secretary`;
- canonical Git origin;
- clean tracked worktree;
- `origin/production` equals the exact authorized PP1 release SHA;
- runtime checkout is either:
  - rollback SHA with DB revision exactly `0050`, or
  - release SHA with DB revision exactly `0051` for idempotent verification;
- existing `db`, `api`, `worker` containers;
- DB running/healthy;
- current API health PASS in the first-rollout state;
- `.env` exists;
- explicit Compose resolution via the canonical compose files + env file;
- API/worker DB credentials and `SECRETARY_CREDENTIAL_KEY` are non-empty and equal;
- read-only DB TCP auth `SELECT 1` succeeds.

Record internally before mutation:

- DB container identity;
- DB volume identity;
- `.env` checksum;
- current api/worker container identities.

Never print credentials, account IDs, emails, message bodies, or raw provider errors.

## Forward migration sequence

For first rollout state only:

1. Check out the exact authorized release SHA.
2. Resolve the release Compose environment and prove DB/credential settings are unchanged from rollback.
3. Build **only api and worker while the old containers are still serving**.
4. Stop only `api` and `worker`.
5. Prove both are stopped.
6. Run exactly `alembic upgrade 0051` using the release application image with `--rm --no-deps`.
7. Read the DB revision directly and require exactly `0051`.
8. Verify the new schema directly before starting the release application.
9. Recreate only `api` and `worker` with `--no-deps --force-recreate`.
10. Require both application container identities to change.
11. Require DB container, DB volume, and `.env` unchanged.
12. Require health PASS.
13. Require DB revision still exactly `0051`.
14. Print only sanitized PASS facts.

Never include `db` in an `up` command.

## Required post-migration structure verification

Before release runtime starts, directly prove at minimum:

- `person_promotion_feedback` exists;
- required columns exist: `user_id`, `provider`, `identity_type`, `realm`, `canonical_value`, `display_value`, `feedback_kind`, `state`, `origin`, `provenance_key`, `created_at`, `updated_at`, `retracted_at`;
- the active exact-identity unique index exists;
- the migration-created table has zero rows immediately after migration and before release runtime starts.

Do not print row content.

## Idempotent rerun

If checkout is already the exact release SHA and DB revision is exactly `0051`:

- do not run the migration again;
- verify DB/app/env/container invariants and the 0051 structure;
- require health PASS;
- report idempotent PASS.

Any mixed state such as rollback app + 0051 DB or release app + 0050 DB must fail closed.

## Rollback semantics

### Failure before release runtime starts

If migration has started but the release application has **not** been started:

- api/worker must already be stopped;
- because no release runtime could have written the new table, prove `person_promotion_feedback` is empty;
- downgrade exactly `0051 -> 0050`;
- verify DB revision exactly `0050`;
- restore the rollback application SHA;
- rebuild/recreate only api/worker;
- preserve DB container, DB volume, and `.env`;
- require rollback health PASS.

If table emptiness cannot be proven, do not downgrade.

### Failure after release runtime has started

A post-cutover downgrade may drop `person_promotion_feedback`, so it is destructive if suppression feedback has been written.

Before any `0051 -> 0050` downgrade after release runtime has started:

1. stop api/worker;
2. require DB revision `0051`;
3. directly prove `person_promotion_feedback` row count is exactly zero.

Only then may downgrade and restore the rollback application.

If the count is non-zero, cannot be read, or any safety proof fails:

- leave api/worker stopped;
- do NOT downgrade;
- do NOT delete/truncate/edit the table;
- emit sanitized `BREAK_GLASS_REQUIRED=true`;
- return failure.

Rows created by PP1 approval in existing `objects`, `person_identities`, or `person_identity_evidence` are 0050-compatible and are NOT grounds for destructive cleanup. Do not delete them.

## Tests

Add focused tests covering at minimum:

1. only exact rollback/release SHAs are accepted;
2. only `0050 -> 0051` is accepted;
3. rollback must be ancestor of release;
4. Alembic delta must be exactly the one added 0051 migration;
5. changed Alembic infra or earlier migrations are rejected;
6. revision/down_revision are exactly 0051/0050;
7. pinned target / strict host-key contract is preserved;
8. remote requires `origin/production == release`;
9. valid first-rollout state is rollback SHA + 0050;
10. valid idempotent state is release SHA + 0051;
11. all mixed app/schema states fail closed;
12. build occurs before downtime;
13. api/worker are stopped before migration;
14. DB is never recreated;
15. structure check must pass before app start;
16. initial new-table row count must be zero before app start;
17. pre-cutover failure can downgrade only after proving the table empty;
18. post-cutover empty table can downgrade;
19. post-cutover non-empty table blocks downgrade and emits `BREAK_GLASS_REQUIRED=true`;
20. post-cutover safety-query failure blocks downgrade;
21. sensitive command failures do not leak secrets;
22. schema-neutral `deploy.py` still rejects migration-bearing releases;
23. historical 0047->0050 migration harness tests remain green.

Run the new harness tests plus existing deployment harness regression tests relevant to 0047->0050 and schema-neutral deploy guards.

Run Ruff/formatting and `git diff --check`.

## Documentation

Update `docs/deploy.md` with a new narrow section for PP1 0050->0051. It must state:

- exact release and rollback SHA;
- exact revision pair;
- exact new table;
- build-before-downtime;
- DB/env preservation;
- guarded post-cutover downgrade semantics;
- normal `deploy.py` remains forbidden for this release.

## Explicitly out of scope

- No live production deploy.
- No moving `production` ref.
- No DB mutation in production.
- No provider/network/model call.
- No PP1 product-code change unless a harness test proves a blocker in the accepted release contract; if so STOP and report.
- No new migration.
- No client change.
- No human UI acceptance.
- No contextual task prompts.
- No Person Knowledge.
- No Organization/social graph work.
- No unrelated deploy-harness cleanup/refactor.

## Completion

1. Commit the harness, tests, and deploy documentation.
2. Record the exact implementation SHA and test results in `PROJECT_STATE.md`.
3. Return `CURRENT_TASK.md` to HOLD.
4. Production/runtime must still be `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa`, Alembic `0050`.
5. Report implementation/HOLD SHAs and test results, then STOP.

Do not deploy. The Architect will separately review PP1-D1 and authorize the live migration-bearing rollout only after this harness is accepted.
