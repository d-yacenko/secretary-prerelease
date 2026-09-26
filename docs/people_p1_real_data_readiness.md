# People P1 real-data review readiness

Local repository and disposable-database audit. Production was not contacted: no SSH, no production HTTP, no production database, no provider call, no ref promotion, and no deploy.

Production application ref remains `296b4735f9473ea60ef22f1827ed94260603128e`. Production Alembic remains `0047 / 0047`. Current main Alembic head is `0050`.

## A. Version skew that blocks the People screen

The current client People mode calls `GET /graph/people-workspace` (`SecretaryApiClient.getPeopleWorkspace`). Identity correction, only after an explicit user action, calls `POST /graph/people/{person_id}/identity-correction`.

That GET exists on current main in `backend/app/api/routes/graph_workspace.py` and is served by `PersonGraphWorkspaceService`. It reads `objects`, `edges`, `person_identities`, and `person_identity_evidence`.

The production ref has `GET /graph/workspace` only. It has no People workspace route and no Person identity service. A current client against that API receives 404. That matches the observed review failure.

`0048_person_identities` creates `person_identities`. The workspace and identity attach path query that table.

`0049_person_identity_evidence` creates `person_identity_evidence`, including the checks and partial unique index used by correction and conflict detection. The workspace presentation queries it. `0048` alone is not enough for the current People service.

`0050_task_completion_mode` adds nullable `objects.completion_mode`, backfills existing `kind=task` rows to `finite`, and adds `ck_objects_completion_mode`. Current `Object.completion_mode` is a mapped column, so every current-main object read, including People nodes, selects it.

Disposable rehearsal on Postgres 16 with pgvector:

| Schema | Current-main `Object` read | `completion_mode` column |
| --- | --- | --- |
| 0047 | fails, missing column | absent |
| 0049 | fails, missing column | absent |
| 0050 | succeeds | present |

Minimum schema for the current-main People API is **0050**. Head is exactly `0050` (`alembic_heads=['0050']`). There is no later revision in the tree.

`/health` is `SELECT 1`. It does not require 0050. Ordinary `GraphWorkspaceService.get_workspace` succeeded on the 0050 rehearsal database.

A read-only visual review needs the current-main **api** process. It does not need the worker. `app.worker.run` runs source sync, the proactive scheduler, the job queue, and trace cleanup. It does not call `PersonEnrichmentService`. Source sync and queued jobs still write objects and provider state, so a current-main worker against a review database is not read-only. Leave it stopped.

The People screen itself does not require other post-0047 endpoints. The shell may still call `/notifications`, `/today`, and, when switching back to Tasks, `/graph/workspace`. Those routes exist on the production ref. Editing a Task from the current client can send `completion_mode`, which the production API does not accept. That edit is outside the People overview.

## B. Migration compatibility

None of `0048`, `0049`, or `0050` renames, drops, or retypes an existing column or table. `0048` and `0049` add tables, foreign keys, and indexes. `0050` adds one nullable column, one check, and a data backfill.

### Old runtime `296b…` on schema 0050

The production-ref `Object` mapping has the same columns as current main except `completion_mode`. Planned start/end, `occurred_at`, `deleted_at`, and the embedding columns are already in that mapping, so they are already in the 0047 schema.

On the disposable database after upgrade to 0050:

- an INSERT that lists only the production-ref object columns succeeded;
- the new task's `completion_mode` stayed NULL;
- a SELECT of the production-ref column list succeeded (`Later task`);
- the migration backfill had already set the pre-existing task to `finite`;
- the person row stayed NULL, because the backfill is `kind = 'task'` only.

NULL is allowed by `ck_objects_completion_mode`. The new tables are not referenced by the old mapping. Extra tables and a nullable column are therefore harmless to old ORM reads and to old inserts that omit `completion_mode`.

This smoke did not boot the `296b…` application process. It used that ref's mapped object and edge columns through SQL, then the current services after 0050. A full old-process boot was not required to prove the column contract.

Changed constraints that old writes can meet: the new check allows NULL, `finite`, and `ongoing`. No old column default was altered.

### Current-main minimum

Proven on the disposable database: current-main ORM and People services need **0050**. At 0049 the ORM cannot load `Object`. After 0050:

- `SELECT 1` succeeded;
- `GraphWorkspaceService.get_workspace` returned nodes;
- People overview before any identity row returned the person with an empty identity list;
- `PersonIdentityService.attach` plus a second overview returned provider `email` and `open_task_count` 1;
- a rooted request returned the person and the linked task (`Ada`, `Reply`).

### Rollback boundary

| Revision | Downgrade removes | Data loss if current-main has written |
| --- | --- | --- |
| 0050 | `ck_objects_completion_mode` and `objects.completion_mode` | every stored finite/ongoing value, including the task backfill |
| 0049 | `person_identity_evidence` | correction, conflict, and route evidence |
| 0048 | `person_identities` | canonical provider identities |

The rehearsal downgraded 0050 to 0049. The column was gone afterward. That was a disposable database.

Do not use downgrade as a casual production rollback. After current-main has written identities or completion modes, the safe application rollback is to put the old `296b…` runtime back and **leave the database at 0050**. The old mapping does not require the new column and does not read the new tables.

## C. Disposable rehearsal

Container `pgvector/pgvector:pg16`, database `secretary_p1_rehearsal`, host port 55432, then removed. No production data.

`ops/local/people_p1_readiness_rehearsal.py` upgraded an empty database to 0047, inserted a user, a person, a task, an email, and one confirmed `related_to` edge using 0047-valid columns, then upgraded `0047 -> 0048 -> 0049 -> 0050`. Results are in section B. The script refuses the default `secretary` database on port 5432.

Existing local tests, not run against that container: `tests/test_person_graph_workspace.py`, `tests/test_person_identity.py`, `tests/test_person_evidence_ledger.py` — 25 passed.

## D. Review topologies

### Option A — current main plus a local synthetic database

Safe and already rehearsed. It does not show production contacts. Enough to confirm the client against a current API. Not enough for the human real-data gate.

### Option B — isolated current-main API plus a copy of the production database, upgraded to 0050

The repository has no disposable snapshot/restore harness and no second-host compose contract for a review API. A future authorization would need its own copy step, a non-production port, the copy upgraded only to 0050, api without worker, and the current client pointed at that API. The copy is confidential production data and must stay off laptops and logs that are not already approved for production data. P1R1 did not create a copy.

This does not mutate the production database.

### Option C — upgrade the production database to 0050 and leave the old app running

Technically the old runtime can read and insert against 0050, from the column proof above. It still mutates the only production database: new tables, a check, and a task backfill to `finite`. Rollback by downgrade destroys those values once current-main writes them. This needs a separate migration authorization. It is a larger production change than a copy.

### Option D — deploy current main to production

Disproportionate for a visual review. It would ship the People API together with every other main change since `296b…`, and it still needs the 0047 to 0050 migration. `deploy.py` cannot do that migration.

### Recommended next authorization

Do not migrate or deploy production yet.

The next authorization should be a **read-only census** of production: count `objects.kind = 'person'`, and count edges whose endpoints are those objects. The production ref has no Person writer and no identity tables, so the likely result is zero person objects. That count is `REQUIRES AUTHORIZED RUNTIME CHECK`.

If the count is zero, a schema upgrade cannot produce a useful People review. Identities are empty after 0048 until something writes them. There is no worker backfill. `PersonEnrichmentService.plan` can attach an identity while it scans stored messages, but nothing in `app.worker.run` calls it, and calling it writes. That write needs its own authorization and is not a review step.

If the census finds person objects, the smallest real-data review is **Option B**: a copy, upgraded to 0050, with an isolated current-main API and the worker stopped. Option C and Option D stay unnecessary for P1.

Until that census, the only safe visual path is Option A.

## E. Deployment contract gap

`ops/production/deploy.py` refuses a release whose Alembic tree differs from the rollback commit (`release changes migration infrastructure`). It cannot authorize 0047 to 0050.

`ops/production/migrate_deploy.py` is hard-coded to `0041 -> 0046` and to specific migration filenames. `ops/production/migrate_assistant_0047.py` is hard-coded to release `296b…`, rollback `42db393…`, and `0046 -> 0047`. Changing those constants is not a 0047 to 0050 plan.

Any production-database option needs a new harness. It should require:

- production app ref exactly `296b4735f9473ea60ef22f1827ed94260603128e` and Alembic exactly 0047 before it starts;
- Alembic delta exactly `0048`, `0049`, and `0050`, with env, ini, and template unchanged;
- api and worker stopped before upgrade, and the worker left stopped for a review;
- upgrade to exactly 0050 and a direct `alembic_version` check;
- no downgrade after `person_identities`, `person_identity_evidence`, or non-null `completion_mode` values exist beyond the task backfill, unless a counted empty-table proof is part of that same authorization;
- no provider calls and no use of `deploy.py`.

P1R1 does not add that harness. The local script is disposable and contains no production target.

## P1R2 postmortem and P1R2R verifier repair

P1R2 produced no usable Person counts. The one-shot production authorization was consumed after `CENSUS_MARKER=started`. The six integers are not stored anywhere in the repository and cannot be reconstructed.

The verifier rejected a successful read. `psql -v ON_ERROR_STOP=1 -At` prints command tags around the data row. A disposable Postgres 16, queried with local psql 18.6, emitted:

```
BEGIN
on|3|2|1|4|1|2
COMMIT
```

The old helper required exactly one non-empty stdout line, so that shape became `CENSUS_BLOCKED=census_output`. The local parser treated `CENSUS_MARKER=started` plus that blocked line as generic `malformed`.

P1R2R is local only. It does not rerun production and does not infer production counts. `psql` is now invoked with `-X -q -v ON_ERROR_STOP=1 -At`. On the same disposable server those flags emitted only the data row. The parser still accepts exactly two shapes: the data row alone, or `BEGIN`, the data row, and `COMMIT`. Any other line fails. A post-marker `CENSUS_BLOCKED=<known stage>` stays that stage with the authorization marked consumed.

A second production census needs a new explicit authorization. The repaired verifier is ready for that authorization; this task does not grant it.
