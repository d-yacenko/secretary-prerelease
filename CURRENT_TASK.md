# Current task — Production D1: prepare exact 0047 -> 0050 migration rollout

The user has accepted moving the current Task/People work toward production/preprod validation on real data.

Production is currently:
- runtime/ref: `296b4735f9473ea60ef22f1827ed94260603128e`;
- Alembic: `0047 / 0047`.

Current main requires:
- `0048_person_identities`;
- `0049_person_identity_evidence`;
- `0050_task_completion_mode`.

The normal `ops/production/deploy.py` is schema-neutral and MUST NOT be used for this transition.

D1 is preparation/rehearsal only.

DO NOT mutate production in D1.
DO NOT move `origin/production`.
DO NOT SSH to production except if a local harness test explicitly mocks/fixtures it; no live production connection is authorized.
DO NOT deploy.

## Goal

Implement one dedicated migration deployment harness for the exact release transition:

`0047 -> 0048 -> 0049 -> 0050`

from rollback application:

`296b4735f9473ea60ef22f1827ed94260603128e`

to an explicitly supplied release SHA.

The harness must be fail-closed and reusable for the next D2 live rollout after Architect review.

Prefer the existing style of:
- `migrate_assistant_0047.py`;
- `remote_migrate_assistant_0047.py`;

but create a new exact-purpose entrypoint rather than weakening/generalizing old migration harnesses.

Suggested names:
- `ops/production/migrate_people_tasks_0050.py`;
- `ops/production/remote_migrate_people_tasks_0050.py`.

Names may differ slightly if repository conventions strongly prefer another exact name.

## Exact accepted migration delta

The local harness must verify that between rollback SHA and release SHA the Alembic migration infrastructure change is exactly the addition of:

- `backend/alembic/versions/0048_person_identities.py`
- `backend/alembic/versions/0049_person_identity_evidence.py`
- `backend/alembic/versions/0050_task_completion_mode.py`

and that:
- existing prior migration files are unchanged;
- `backend/alembic/env.py` is unchanged;
- `backend/alembic.ini` is unchanged;
- `backend/alembic/script.py.mako` is unchanged;
- the revision chain is exactly 0047 -> 0048 -> 0049 -> 0050.

Reject any extra migration-file or Alembic-infrastructure change.

Do not hard-code current main SHA into the harness implementation. The harness should accept a literal release SHA argument, but only allow rollback SHA `296b4735f9473ea60ef22f1827ed94260603128e`, `from-alembic 0047`, and `to-alembic 0050`.

## Canonical production safety

Reuse:
- committed `ops/production/target.json`;
- strict pinned host-key handling;
- canonical repo/path checks;
- existing SSH credential contract;
- exact Compose invocation with `/opt/secretary/.env`;
- DB container/volume/.env preservation invariants.

Do not discover alternate hosts/paths.
Do not add fallback SSH behavior.
Do not print secrets.

## Remote rollout order

The remote helper for D2 must implement this exact high-level sequence:

1. preflight canonical production path/origin/clean tree;
2. require current checkout is rollback SHA or already release SHA;
3. require `origin/production == release SHA`;
4. require current DB revision exactly 0047 before first rollout, or exactly 0050 if already release;
5. capture DB container identity, DB volume identity, env checksum, api/worker identities;
6. resolve Compose with the committed production env;
7. verify DB credentials/credential key presence and cross-service consistency;
8. verify DB TCP `SELECT 1`;
9. build release api/worker BEFORE downtime;
10. stop only api and worker;
11. switch checkout to exact release SHA;
12. run `alembic upgrade 0050` using one-shot api image/container, no db recreate;
13. directly verify DB revision is exactly 0050;
14. run bounded post-migration structural checks listed below;
15. recreate only api and worker;
16. verify db container/volume/env unchanged;
17. verify api/worker container identities changed;
18. health PASS;
19. verify runtime checkout exact release SHA;
20. verify Alembic exact 0050.

Never include `db` in `up`.
Never recreate DB.
Never rewrite `.env`.

## Post-migration structural checks before app start

After upgrading to 0050 and before starting release runtime, directly verify:

- table `person_identities` exists;
- table `person_identity_evidence` exists;
- column `objects.completion_mode` exists;
- every existing `kind='task'` row has completion_mode `finite` or `ongoing`;
- no Task has NULL completion_mode;
- no non-Task row is forced to a non-null completion_mode by the migration itself;
- DB revision is exactly 0050.

These checks must output only counts/booleans, no titles, bodies, identities, addresses, messages, or other PII.

## Rollback semantics

### Before release runtime has started

If failure occurs after migration but BEFORE release api/worker have successfully started, automatic rollback may:

1. run `alembic downgrade 0047`;
2. verify revision exactly 0047;
3. restore rollback checkout;
4. rebuild/recreate only api and worker;
5. preserve DB container/volume/env;
6. verify health.

This is allowed because release code has not had an opportunity to create data in 0048/0049/0050 fields.

### After release runtime has started

Automatic downgrade to 0047 is destructive unless directly proven safe.

Before any post-cutover downgrade, prove all of:

- `person_identities` row count == 0;
- `person_identity_evidence` row count == 0;
- Task rows with `completion_mode='ongoing'` == 0;
- no other explicitly identified 0050-only user state would be lost.

If ALL are proven zero/safe, downgrade may proceed.

If any count is nonzero OR any safety query fails/uncertain:
- DO NOT downgrade schema;
- DO NOT delete rows;
- DO NOT drop columns/tables;
- preserve DB at 0050;
- stop or leave stopped api/worker as safest;
- emit a sanitized marker such as:
  `BREAK_GLASS_REQUIRED=true`;
- report exact stage only, no PII.

Do not invent an automatic data-conversion rollback for ongoing Directions or People identities.

## Idempotency

If rerun and production is already at:
- release SHA;
- Alembic 0050;
- health PASS;

the harness should verify invariants and return success without repeating migration.

If checkout/revision combinations are inconsistent, fail closed.

## Release client artifact

D1 does NOT deploy client binaries.

However, record in the task report whether current main client already has a successful Linux debug build for the release candidate and whether a separate client distribution/update step is required for the user's production workstation.

Do not package or install the client in D1 unless an existing production runbook already mandates it for server rollout.

## Tests

Add focused local tests for the new harness/remote helper covering at minimum:

1. accepts exact 0047->0050 migration delta;
2. rejects extra migration file;
3. rejects modified pre-existing migration;
4. rejects changed alembic env/config/template;
5. rejects wrong rollback SHA;
6. rejects wrong from/to revisions;
7. requires origin/production == release;
8. preserves pinned host-key contract;
9. builds before downtime;
10. migration runs only with api/worker stopped;
11. db is never recreated;
12. structural post-migration checks run before app start;
13. pre-cutover failure can downgrade to 0047;
14. post-cutover safe-empty rollback can downgrade;
15. post-cutover Person identity row blocks downgrade;
16. post-cutover Person evidence row blocks downgrade;
17. post-cutover ongoing Task blocks downgrade;
18. rollback safety-query failure blocks downgrade;
19. blocked downgrade emits break-glass marker and does not delete data;
20. rerun on already-release/0050 is idempotent;
21. inconsistent release/revision state fails closed;
22. no secret-bearing Compose/env material is printed.

Prefer unit/subprocess tests with mocked SSH/remote execution.
No production network access in tests.

## Rehearsal

Run a local disposable PostgreSQL rehearsal if practical:

- initialize schema at 0047;
- insert representative existing finite Task rows plus non-Task rows;
- run upgrade to 0050;
- prove existing Tasks backfilled finite;
- prove non-Tasks remain NULL;
- prove both Person tables exist empty;
- downgrade back to 0047 before any release-only writes and prove schema returns cleanly.

Then separately rehearse post-cutover rollback blocking by inserting:
- one ongoing Task, OR
- one Person identity/evidence row,
and prove the harness refuses downgrade.

No production data copy is needed in D1.

## Documentation

Update `docs/deploy.md` with one exact section for this migration path:
- exact rollback SHA;
- exact revision pair 0047 -> 0050;
- entrypoint syntax;
- pre-cutover vs post-cutover rollback distinction;
- break-glass behavior.

Do not weaken the generic schema-neutral limitation.

## Validation

Run at minimum:

- focused new production harness tests;
- existing production deploy contract tests relevant to target/pin/secret safety;
- migration chain/unit tests if present;
- Ruff check/format touched Python;
- `git diff --check`.

No Flutter UI work.
No manual GUI work.

## Scope guard

Do NOT:
- access production;
- move `origin/production`;
- deploy;
- run live migrations;
- change 0048/0049/0050 semantics;
- add migration 0051;
- change People/Task product behavior;
- fix unrelated client tests;
- start S3/H2D;
- create screenshots/manual UI flows.

## Completion

Record in `PROJECT_STATE.md`:
- implementation SHA;
- exact local/remote harness names;
- accepted migration delta verification;
- rollout order;
- pre-cutover rollback behavior;
- post-cutover rollback guard conditions;
- rehearsal result;
- exact test counts;
- confirmation that production was not contacted or mutated;
- whether a separate client update step remains necessary.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not execute D2 production rollout.
