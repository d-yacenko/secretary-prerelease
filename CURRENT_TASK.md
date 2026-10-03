# Current task — ACTIVE

## REL1-R0.1 — correct failed-migration recovery classification before live rollout

REL1-R0 harness implementation `ed287ed115dda037f94b509b79f76c8ffba2e2ea` is directionally accepted, but live REL1-R1 is NOT authorized to execute yet because Architect review found one narrow fail-closed recovery defect.

This task is source-only. Do not move `production`, SSH to production, run Alembic in production, deploy services, install the client, or start REL1B/REL1C/REL1D.

The user's existing controlled-rollout authorization remains valid for the later exact live rollout after this corrective is Architect-reviewed.

## Exact rollout contract remains unchanged

- release: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- rollback: `2314bf72101fbd83d50a7b264154d73740e28db1`
- production before rollout: Alembic `0052`
- target: Alembic `0054`
- exact migration chain:
  - `0053_person_role_vocabulary.py`: `0053 -> 0052`
  - `0054_person_role_key_width.py`: `0054 -> 0053`
- `deploy.py` remains schema-neutral.

Do not change these constants or broaden the harness.

## Verified defect

In `ops/production/remote_migrate_person_roles_0054.py`, the migrate path sets `migration_started = True` immediately before:

`alembic upgrade 0054`

Any exception after that enters recovery and, when `live == False`, currently calls `prove_role_tables_empty(...)` before inspecting the actual DB revision.

If the Alembic command fails before `0053` is applied, the correct production state can still be:

- DB revision exactly `0052`;
- `person_role_terms` absent;
- `person_role_assignments` absent.

In that safe state, querying row counts from the absent tables fails, so the current code emits `BREAK_GLASS_REQUIRED=true` instead of restoring the rollback runtime without a schema downgrade.

This contradicts the authorized recovery contract:

> Before the role migration is applied, a failed rollout with DB still at 0052 must restore the rollback runtime without attempting a downgrade.

The recovery must distinguish an untouched `0052` database from a partially/fully migrated `0053` or `0054` database.

## Required correction

Change only the failed-migration recovery classification needed for this gap.

### 1. Classify the actual DB state after a failed migration attempt

For the pre-cutover recovery path after `alembic upgrade 0054` was attempted but release runtime has not been accepted:

Read the Alembic revision directly and fail closed unless it is one of:

- `0052`;
- `0053`;
- `0054`.

Do not infer revision only from table existence.

### 2. Safe untouched-0052 path

If actual revision is exactly `0052`:

- deterministically prove both role tables are absent;
- do NOT run `alembic downgrade`;
- restore exact rollback checkout/runtime;
- verify health;
- verify revision remains `0052`;
- verify DB container, DB volume, and `.env` remain unchanged.

If revision is `0052` but either role table unexpectedly exists, treat the schema as inconsistent:

- do not drop tables;
- do not edit Alembic revision;
- do not start an improvised repair;
- emit rollback-blocked + `BREAK_GLASS_REQUIRED=true`;
- STOP.

### 3. Safe intermediate/final migrated path

If actual revision is `0053` or `0054` before release runtime acceptance:

- deterministically prove BOTH role tables exist;
- directly prove BOTH role tables are empty;
- only then run exact `alembic downgrade 0052`;
- require revision exactly `0052`;
- require both role tables are absent after downgrade;
- restore rollback runtime and verify health + preserved DB/container/volume/`.env`.

If either role table is non-empty, missing in an inconsistent migrated state, unreadable, or the checks cannot be proven:

- no downgrade;
- no delete/truncate/drop;
- emit rollback-blocked + `BREAK_GLASS_REQUIRED=true`;
- STOP.

### 4. Unknown/unreadable revision is break-glass

If Alembic revision cannot be read, is multiple/ambiguous, or is anything other than `0052`, `0053`, `0054` during this failed-attempt recovery:

- do not downgrade;
- do not restore/start an application against an uncertain schema;
- emit `BREAK_GLASS_REQUIRED=true`;
- STOP.

### 5. Preserve post-cutover safety

Do not weaken the existing post-cutover path.

Once release runtime has started:

- stop API/worker first;
- require Alembic exactly `0054`;
- prove both role tables empty;
- only then downgrade to `0052`;
- any non-empty/unreadable/inconsistent state remains break-glass.

### 6. Preserve the idempotent path

Exact release + Alembic `0054` idempotent verification remains non-mutating and may contain real role rows.

Do not require role-table emptiness on idempotent verification.

## Preferred implementation shape

A small explicit helper/state classifier is preferred over scattered exception handling.

For example, conceptually:

- read revision;
- inspect role-table presence;
- classify `untouched_0052` / `migrated_empty` / unsafe;
- act according to that classification.

Naming is up to the implementation.

Do not make recovery permissive. Every uncertainty must stop.

## Required deterministic tests

Extend `backend/tests/test_person_roles_0054_migration_harness.py` to prove at minimum:

1. failed migration attempt + revision `0052` + both role tables absent:
   - no Alembic downgrade;
   - rollback runtime restore is attempted;
   - expected revision remains `0052`.

2. revision `0052` + either role table present:
   - no downgrade;
   - no restore/start against inconsistent schema;
   - `BREAK_GLASS_REQUIRED=true`.

3. revision `0053` + both role tables present and empty:
   - downgrade to `0052` allowed;
   - post-downgrade tables proven absent;
   - rollback runtime restore allowed.

4. revision `0054` before cutover + both role tables present and empty:
   - downgrade to `0052` allowed;
   - post-downgrade tables proven absent.

5. revision `0053` or `0054` + either role table non-empty:
   - no downgrade;
   - break-glass.

6. revision `0053` or `0054` + table-presence/count query failure:
   - no downgrade;
   - break-glass.

7. unreadable/ambiguous/unknown Alembic revision:
   - no downgrade;
   - no runtime restore;
   - break-glass.

8. a failed `alembic upgrade` call itself is covered at the recovery-boundary level so the code path cannot regress to “migration attempted implies tables exist”.

9. existing post-cutover non-empty protection remains green.

10. existing idempotent `release + 0054` path remains non-mutating and allows later role rows.

11. no `DELETE`, `TRUNCATE`, manual `DROP TABLE`, or Alembic-version edit is introduced.

12. sensitive failures still do not print secrets.

## Required checks

Run source-only:

- `backend/tests/test_person_roles_0054_migration_harness.py`;
- `backend/tests/test_rel1a_person_roles.py`;
- Ruff on changed Python files;
- `py_compile` on both role rollout helpers;
- `git diff --check`.

If no product/schema source is changed, do not broaden testing unnecessarily.

Update `docs/deploy.md` only if the documented recovery behavior needs clarification.

## Explicit non-goals

Do not:

- change migrations `0053` or `0054`;
- add `0055`;
- change RoleTerm/assignment semantics;
- change app/backend/client product code;
- move `refs/heads/production`;
- SSH to production;
- run production migration;
- deploy/recreate production services;
- install/replace client;
- call model/provider;
- create role/Person data;
- start REL1B/REL1C/REL1D.

## Completion protocol

When complete:

1. append a compact REL1-R0.1 result to `PROJECT_STATE.md`;
2. return `CURRENT_TASK.md` to HOLD with:
   - corrective implementation SHA;
   - exact recovery classification semantics;
   - exact test/check evidence;
   - unchanged release/rollback/revision contract;
   - explicit confirmation production remains `2314bf72101fbd83d50a7b264154d73740e28db1`, Alembic `0052 / 0052`;
   - no SSH/deploy/migration/client/model/provider action;
3. commit + push to `main`;
4. STOP.

Do not execute REL1-R1 from the same task.

Architect must source-review this corrective before live rollout.
