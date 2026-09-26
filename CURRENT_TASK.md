# Current task — People P1R1: real-data review deployment-readiness audit

People Visual P1 is technically accepted, but human real-data review is blocked by version skew.

Observed real client behavior:
- People mode opens;
- `GET /graph/people-workspace` returns 404 / `Not Found`.

Repository facts already established:
- current `main` contains `GET /graph/people-workspace` and `PersonGraphWorkspaceService`;
- production application ref is still `296b4735f9473ea60ef22f1827ed94260603128e`;
- production Alembic is `0047 / 0047`;
- current main Alembic head is `0050`;
- migrations after production are:
  - `0048_person_identities`;
  - `0049_person_identity_evidence`;
  - `0050_task_completion_mode`.

This is a READINESS / REHEARSAL phase only.

Do NOT connect to production.
Do NOT SSH.
Do NOT inspect production DB.
Do NOT move `origin/production`.
Do NOT deploy.
Do NOT change runtime production code merely to make review easier.

## Goal

Answer, with code/tests/rehearsal evidence:

> What is the smallest safe, reversible way to run the current-main People backend/client against representative or real production-derived data for P1 human visual review?

The deliverable must clearly distinguish:
- what can be proven locally now;
- what would require a later explicit production authorization;
- what should not be attempted.

## Deliverable A — exact version-skew map

Create:

`docs/people_p1_real_data_readiness.md`

Document the exact differences relevant to People review between production ref and current main.

At minimum cover:

1. API:
   - when `/graph/people-workspace` appears;
   - required schemas/services/models.

2. Database:
   - why `0048` is required by Person identities;
   - why `0049` is required by identity evidence/correction;
   - whether current-main ORM/API can run on `0049` without `0050`;
   - whether `0050 completion_mode` is required merely because current Object ORM reads include that column, even for People endpoints;
   - exact current main head.

3. Runtime:
   - api-only requirements;
   - whether worker must run for a read-only visual review;
   - whether background jobs could mutate Person identity/salience data if a current-main worker is started.

4. Client:
   - exact endpoint(s) required by P1;
   - whether any current-main client calls besides People workspace require post-0047 backend behavior during this review.

Do not dump unrelated full production-vs-main history.

## Deliverable B — migration compatibility analysis

Audit migrations `0048 -> 0049 -> 0050` and the old production runtime at `296b...`.

Answer separately:

### Forward compatibility

If the DB schema were upgraded to 0050 while the OLD production application remained at `296b...`:

- would extra tables 0048/0049 be harmless to the old app?
- would the new nullable/backfilled `objects.completion_mode` column be harmless to old ORM reads/writes?
- are there changed constraints/defaults/indexes that could break old writes?
- does any migration rename/drop/change an existing column or table?

Do not assume. Prove from migration and old model code.

### Current-main compatibility

Prove the minimum schema revision on which current-main API can start and execute:
- `/health`;
- ordinary `/graph/workspace`;
- `/graph/people-workspace`;
- a rooted People workspace request;
- Person detail/correction dependencies needed by the current client.

### Rollback boundary

For each migration:
- what downgrade removes;
- whether downgrade would lose data after current-main runtime has written to the new tables/column;
- whether a rollback to old application code can safely leave the DB at 0050 instead of downgrading;
- whether any irreversible/readiness concern exists.

Do NOT propose destructive downgrade as a casual rollback.

## Deliverable C — disposable local rehearsal

Use only a disposable LOCAL database/container.

Rehearse at minimum:

1. create schema at exact 0047;
2. insert a small representative fixture using only 0047-valid data:
   - user;
   - Person Object(s);
   - Task Object(s);
   - communication/Flow Object(s);
   - grounded graph edges sufficient for People workspace after identity data exists;
3. prove old production-ref backend/model smoke operations still work at 0047;
4. upgrade the disposable DB through exactly 0048, 0049, 0050;
5. prove the same old production-ref smoke operations still work against schema 0050, insofar as practical from a local checkout/container;
6. run current-main API/service-level People workspace smoke against 0050;
7. create/seed minimal Person identity/evidence through canonical current-main services or fixtures;
8. prove overview and rooted People workspace return usable Person presentation;
9. prove no migration exceeds head 0050 and no uncommitted schema drift exists.

If running two application refs against one local DB is awkward, a small purpose-built compatibility test/harness is acceptable, but it must exercise actual SQLAlchemy models/services from each ref or explain the limitation precisely.

Do not use production data in this rehearsal.

## Deliverable D — review topology options

Compare these possible strategies factually:

### Option A — local disposable synthetic review
Current-main backend/client + local synthetic DB.
- safe, but not real data.

### Option B — isolated review backend against a COPY/SNAPSHOT of production DB
Current-main API on a non-production port/host/container + cloned DB upgraded to 0050.
- identify what repository/infra support exists or is missing;
- identify confidentiality/storage requirements;
- do not create the copy in P1R1.

### Option C — production DB forward-migrate to 0050 while leaving old production app runtime unchanged, then run an isolated current-main API for human review
- assess whether code/migrations support this technically;
- list exact risks;
- note that this mutates production DB and therefore requires a separate explicit migration authorization/harness.
- do NOT execute it.

### Option D — full current-main production deploy
- state why this is or is not proportionate merely to review P1.
- do NOT prepare or execute it unless the analysis shows there is no smaller safe path.

Recommend ONE smallest safe next authorization after P1R1.

Do not pick an option merely because it is easiest to code.

## Deliverable E — deployment contract gap

Inspect `docs/deploy.md` and `ops/production/*`.

State:

- normal `ops/production/deploy.py` is schema-neutral and cannot authorize 0047->0050;
- existing migration harnesses are hard-coded for earlier historical transitions and must not be reused by changing constants;
- whether a new dedicated 0047->0050 migration/review harness would be required for any production-DB option;
- what exact preflight/rollback invariants such a future harness would need.

Do NOT implement that production harness in P1R1 unless a tiny LOCAL-ONLY rehearsal helper is required.

## Important People data question

Determine whether production 0047 is expected to contain enough pre-existing `kind=person` Objects and Actor/Flow edges for People review after adding 0048/0049 tables.

Specifically distinguish:
- existing Person Objects already materialized before canonical identity tables;
- new PersonIdentity rows that would initially be empty after migration;
- whether current-main has a deterministic enrichment/backfill path that would populate identities from existing provider data;
- whether that path is automatic/background, manual, or absent;
- whether running it would mutate production and therefore require separate authorization.

This matters: a technically working endpoint with empty identity tables may still produce an unhelpful P1 review.

Do not run any enrichment against production.

## No silent production probing

P1R1 must remain local/repository-only.

Forbidden:
- SSH/key readiness checks;
- production HTTP requests;
- production DB counts;
- production logs;
- provider calls;
- copying production database;
- running migration commands on production;
- promoting refs.

If a claim cannot be proven without production access, mark it `REQUIRES AUTHORIZED RUNTIME CHECK`.

## Tests / validation

Run the relevant local tests and rehearsal.

At minimum:
- Alembic upgrade chain 0047 -> 0050 on disposable DB;
- relevant Person identity/evidence tests;
- `backend/tests/test_person_graph_workspace.py`;
- a focused compatibility smoke for old-runtime-on-0050 if implemented;
- `git diff --check`.

If production code is unchanged, no Flutter build is required.

Any helper created for disposable rehearsal must be test-only/ops-local and must not contain credentials or production target data beyond the already committed non-secret target contract.

## Completion

Record in `PROJECT_STATE.md`:

- implementation SHA;
- readiness document path;
- proven minimum schema for current-main People API;
- old-runtime-on-0050 verdict;
- Person data/backfill verdict;
- recommended next authorization;
- exact local rehearsal/tests;
- explicit confirmation that production/network/SSH were untouched.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start P2.
Do not start H2.
Do not deploy.
Do not connect to production.
