# CURRENT_TASK

ACTIVE

## REL1D-HG4D — schema-neutral production rollout for accepted People fixes

### Context

The following People work is Architect-accepted on `main`:

- HG4B: immediate Task-actor feedback for an unrooted selected Person;
- HG4C: complete bounded People overview windowing.

HG4B is client-only. HG4C includes a small backend/API delta and therefore real People paging cannot work against the current production backend until a schema-neutral backend rollout is completed.

Accepted release baseline:

`a9221699b4b725888213ff38e6673495a512042c`

Current production / rollback:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic remains:

`0054 / 0054`

Architect comparison confirms the release is a fast-forward from production and contains no Alembic/migration-file changes. Runtime backend delta is limited to the accepted People workspace/API implementation; client/tests/docs/ops changes in the Git release do not alter server schema.

### Goal

Roll the accepted schema-neutral release to canonical production using the committed production deployment contract, verify health/revision, record the exact runtime result, and stop.

A separate Person-rename issue was observed after this rollout task was authorized: rename currently uses the generic object PATCH/embedding path and may fail silently in the client. That issue is **not** part of this deploy. Do not investigate, fix, test, or include any rename code in the release. The release SHA remains exactly pinned below.

### Authorization

This task explicitly authorizes only:

1. deterministic production bootstrap per `AGENTS.md` / `docs/executor_bootstrap.md`;
2. fast-forwarding the canonical GitHub `production` branch from the exact rollback SHA to the exact release SHA;
3. one normal production deployment invocation through `ops/production/deploy.py`;
4. the deploy harness's built-in health/Alembic/rollback behavior;
5. read-only post-deploy inspection needed to report the harness result.

No product coding is authorized.

### Exact refs

Release SHA:

`a9221699b4b725888213ff38e6673495a512042c`

Rollback SHA:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Expected Alembic:

`0054`

Before any production ref movement:

- fetch canonical `origin/main` and `origin/production`;
- verify `origin/main` contains the release SHA;
- verify `origin/production` is exactly the rollback SHA;
- verify release is a descendant/fast-forward of rollback;
- verify the Alembic migration infrastructure delta is empty;
- verify the local bootstrap/runtime prerequisites required by the committed deploy contract.

If any exact-ref/preflight invariant differs, STOP. Do not repair or choose another release.

### Production ref movement

Fast-forward the canonical GitHub `production` branch exactly from:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

to:

`a9221699b4b725888213ff38e6673495a512042c`

No force push.

Immediately re-fetch and require `origin/production` to equal the release SHA before invoking the deploy harness.

If the ref update fails or is not an exact fast-forward, STOP. Do not use GitHub UI, alternate refs, or force.

### Deployment

Read `docs/deploy.md` and use only the committed normal deployment entrypoint:

`ops/production/deploy.py`

Invoke exactly with:

- `--release-sha a9221699b4b725888213ff38e6673495a512042c`
- `--rollback-sha f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`
- `--expected-alembic 0054`

Do not use direct SSH/Compose for deployment.

Do not modify the deploy harness.

Do not restart or recreate the database.

Do not alter `.env`, credentials, provider configuration, volumes, schema, or schedules.

### Required successful result

A successful rollout must prove, through the committed harness:

- canonical target/path/origin checks pass;
- pinned SSH host-key contract passes;
- `origin/production` equals the exact release SHA;
- pre-existing DB health/read-only connectivity checks pass;
- only application services are rebuilt/recreated;
- DB container and volume identities remain unchanged;
- environment checksum remains unchanged;
- API health succeeds;
- Alembic remains exactly `0054`;
- remote runtime checkout after success is the exact release SHA.

If the harness triggers its built-in rollback, report that result exactly and STOP. Do not attempt a second deployment in this task.

If preflight or deployment fails, do not manually repair production. Record one sanitized blocker/result and STOP.

### Post-deploy read-only verification

After `DEPLOYMENT=PASS`, perform only non-sensitive read-only verification allowed by the normal contract:

1. confirm production branch/ref remains the exact release SHA;
2. confirm API health is still OK;
3. confirm Alembic is still `0054`;
4. confirm the deployed OpenAPI description for `GET /graph/people-workspace` exposes optional query parameter `window_index`.

Do not authenticate as the user, read Person records, or run another People DB census in this task. Human product verification will happen from the rebuilt client.

### Explicitly out of scope

Do NOT:

- change backend/client product code;
- investigate or fix Person rename / generic object PATCH / embedding behavior;
- change People paging semantics;
- change salience;
- change Task actor semantics;
- create or alter schema/Alembic;
- run provider/model calls;
- run historical repair/backfill;
- modify role-import extraction;
- build/install the user's Flutter client;
- run a second production deploy attempt after a consumed live failure/rollback;
- perform BREAK-GLASS recovery.

### Completion protocol

On successful rollout:

1. update `PROJECT_STATE.md` with exact release/rollback SHA, deploy result, health, Alembic, and OpenAPI `window_index` verification only;
2. replace this file with `HOLD`, recording the production runtime SHA and checks;
3. commit + push the ledger changes to canonical `main`;
4. STOP.

On blocked/failed/rolled-back rollout:

1. record only sanitized factual outcome;
2. replace this file with `HOLD`;
3. commit + push;
4. STOP.

Do not start client build, human acceptance, raster role-import work, or any other phase automatically.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
