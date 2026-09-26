# Current task — People P1R2: one-shot read-only production Person census

People P1R1 is accepted.

This task explicitly authorizes ONE bounded read-only production runtime check against the existing production application/database.

Production must remain:
- application/runtime ref: `296b4735f9473ea60ef22f1827ed94260603128e`;
- `origin/production`: the same exact SHA;
- Alembic: `0047 / 0047`.

This is NOT a deploy, migration, backup/copy, enrichment run, or provider diagnostic.

## Purpose

Answer only:

> Does production already contain enough canonical `kind=person` graph material to justify a real-data P1 review path?

The result must be aggregate counts only.

## Bootstrap / trust contract

Follow `docs/executor_bootstrap.md` exactly.

Use:
- canonical repository only;
- fresh clean checkout when required;
- `ops/production/target.json` only;
- pinned SSH host key;
- public-key-only authentication;
- existing Executor/workstation credential integration only.

Do not:
- probe alternate hosts/aliases;
- enumerate or copy private keys;
- ask for credentials;
- repair unrelated dirty checkouts.

A pre-SSH/bootstrap/authentication failure does not consume the one-shot census authorization. Report one sanitized blocker and STOP.

## Implementation

Prefer a tiny committed verification pair modeled after the existing read-only production verifiers:

- local entrypoint, e.g. `ops/production/people_p1_person_census.py`;
- remote helper, e.g. `ops/production/remote_people_p1_person_census.py`;
- focused tests under `ops/production/tests/`.

Do not reuse or modify a provider-specific verifier.

The local entrypoint must:

1. require canonical local repo;
2. require exact release SHA `296b4735f9473ea60ef22f1827ed94260603128e`;
3. require `origin/production` equals that SHA;
4. load only committed `ops/production/target.json`;
5. verify the pinned host key;
6. stream the committed remote helper over one SSH execution;
7. print only sanitized census facts.

The remote helper must fail closed unless:

- cwd is exactly `/opt/secretary`;
- Git origin is exactly the canonical prerelease repo;
- tracked worktree is clean;
- HEAD is exact production SHA;
- `origin/production` is exact production SHA;
- DB/API/worker containers exist and are running;
- DB is healthy;
- API health passes;
- Alembic is exactly `0047 (head)`;
- DB TCP authentication succeeds using the already-resolved application DB credentials.

Do not print resolved environment values.

## Authorized SQL

Only aggregate read-only `SELECT` statements are authorized.

Return exactly these logical facts, as non-negative integers:

1. `PERSON_TOTAL`
   - all Objects where `kind='person'`.

2. `PERSON_VISIBLE`
   - Person Objects not tombstoned/deleted under the 0047 visibility convention:
     `deleted_at IS NULL` and `status IS NULL OR status <> 'deleted'`.

3. `PERSON_WITH_EDGES`
   - distinct visible Person Objects incident to at least one Edge.

4. `PERSON_INCIDENT_EDGES`
   - distinct Edges incident to at least one visible Person.

5. `PERSON_TASK_EDGES`
   - distinct incident Edges where the opposite endpoint is a `kind='task'` Object.

6. `PERSON_FLOW_EDGES`
   - distinct incident Edges where the opposite endpoint is neither `person` nor `task`.
   - This is only a coarse grounded-context count; do not output per-kind/provider breakdown.

It is acceptable to compute these with a small number of SQL queries or one aggregate CTE.

Do not output:
- Person titles;
- UUIDs;
- emails/handles/routes;
- provider names;
- edge types;
- object kinds beyond the coarse Task/Flow buckets above;
- message/file/event content;
- timestamps;
- user/account identifiers;
- raw SQL rows.

## Read-only guard

The remote helper must use a read-only transaction for the census, e.g. PostgreSQL transaction read-only semantics, and fail if it cannot establish that mode.

No `INSERT`, `UPDATE`, `DELETE`, DDL, Alembic command that mutates, queue/job action, enrichment call, provider API call, application write endpoint, or filesystem mutation is authorized.

No service restart/recreate.
No worker pause/change.
No DB snapshot/copy.
No migration.
No ref promotion.

## One-shot execution marker

The one-shot production census authorization is consumed only after the remote census helper has started past its invariant preflight and begins the read-only DB census transaction.

If bootstrap/SSH fails before that marker:
- do not retry by changing credentials/hosts;
- report the sanitized blocker;
- STOP.

Once the read-only census transaction begins:
- execute it once;
- do not rerun merely because the result is surprising;
- record the returned aggregate facts;
- STOP after repository bookkeeping.

## Decision rule

Do NOT start any follow-on action automatically.

Record only the census result and one of:

### `P1_REAL_DATA_NOT_USEFUL_YET`
Use when:
- `PERSON_VISIBLE == 0`, or
- there is no grounded graph context sufficient for a meaningful People review (for example both Task and Flow incident-edge counts are zero).

This does NOT authorize migration or enrichment.

### `P1_REAL_DATA_CANDIDATE_EXISTS`
Use when:
- visible Person Objects exist;
- and at least some grounded Task or Flow incident context exists.

This still does NOT authorize copying the DB, migration, isolated API, enrichment, or deploy.

The Architect will choose the next step.

## Tests

Before live execution run focused local tests proving:

1. wrong release SHA fails closed;
2. wrong `origin/production` fails closed;
3. remote wrong cwd/origin/HEAD/Alembic fail closed;
4. query output accepts only the six expected integer facts;
5. no raw row/title/id field can be emitted by the parser/output path;
6. SQL is read-only and no mutation method/path exists in the helper;
7. malformed DB output fails closed;
8. `git diff --check`.

No Flutter build.
No application production-code change should be needed.

## Completion

If census executes, record in `PROJECT_STATE.md`:

- implementation SHA;
- exact production ref and Alembic verified;
- the six aggregate integer census facts;
- final classification `P1_REAL_DATA_NOT_USEFUL_YET` or `P1_REAL_DATA_CANDIDATE_EXISTS`;
- exact verifier tests;
- explicit confirmation: no migration, no DB write, no provider call, no service restart, no ref move.

If bootstrap blocks before the census marker, record only the sanitized bootstrap blocker and confirm census authorization was not consumed.

Return `CURRENT_TASK.md` to HOLD.

Push bookkeeping to `origin/main` and STOP.

Do not start a DB copy.
Do not start a migration.
Do not start P2.
Do not start H2.
Do not deploy.
