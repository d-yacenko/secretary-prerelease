# CURRENT_TASK

ACTIVE

## REL1D-HG4F — schema-neutral production rollout for accepted Person rename

### Context

REL1D-HG4E / HG4E.1 are Architect-accepted.

Accepted release baseline:

`50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

Current production / rollback:

`a9221699b4b725888213ff38e6673495a512042c`

Alembic remains:

`0054 / 0054`

Architect comparison confirms:

- release is a fast-forward descendant of current production;
- no Alembic/migration files are changed;
- backend runtime delta is limited to the accepted Person rename API/schema/service;
- remaining delta is client/tests/ledger only.

The accepted release adds dedicated:

`PATCH /graph/people/{person_id}`

for Person rename without embedding/provider/model dependency.

### Goal

Roll the accepted schema-neutral release to canonical production using only the committed production deployment contract, verify runtime/health/Alembic/OpenAPI, record the exact result, and stop.

No new product coding is authorized.

### Authorization

This task authorizes only:

1. deterministic production bootstrap per `AGENTS.md`, `docs/executor_bootstrap.md`, and `docs/deploy.md`;
2. fast-forwarding canonical GitHub `production` exactly from the rollback SHA to the release SHA;
3. one normal production deployment invocation through `ops/production/deploy.py`;
4. built-in health/Alembic/rollback behavior of the deploy harness;
5. read-only post-deploy verification described below.

### Exact refs

Release SHA:

`50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

Rollback SHA:

`a9221699b4b725888213ff38e6673495a512042c`

Expected Alembic:

`0054`

Before any production ref movement:

- fetch canonical `origin/main` and `origin/production`;
- verify `origin/main` contains the exact release SHA;
- verify `origin/production` is exactly the rollback SHA;
- verify release is a descendant/fast-forward of rollback;
- verify Alembic/migration delta is empty;
- verify local bootstrap/runtime prerequisites required by the committed deploy contract.

If any invariant differs, STOP. Do not choose another release or repair production.

### Production ref movement

Fast-forward canonical GitHub `production` exactly:

from:
`a9221699b4b725888213ff38e6673495a512042c`

to:
`50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

No force push.

Re-fetch and require `origin/production` to equal the release SHA before deploy.

If ref movement is not exact or fails, STOP.

### Deployment

Use only:

`ops/production/deploy.py`

with exactly:

- `--release-sha 50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`
- `--rollback-sha a9221699b4b725888213ff38e6673495a512042c`
- `--expected-alembic 0054`

Do not use direct SSH/Compose for deployment.

Do not modify the deploy harness.

Do not restart/recreate the database.

Do not alter environment, credentials, provider/model config, volumes, schedules, or schema.

### Required successful result

The committed harness must prove:

- canonical target/path/origin checks pass;
- pinned SSH host-key contract passes;
- `origin/production` equals the exact release SHA;
- DB health/read-only connectivity preflight passes;
- only application services are rebuilt/recreated;
- DB container/volume identities remain unchanged;
- environment checksum remains unchanged;
- API health passes;
- Alembic remains exactly `0054`;
- runtime checkout after success equals the exact release SHA.

If harness rollback triggers, report the result and STOP. No second deployment attempt in this task.

### Post-deploy read-only verification

After `DEPLOYMENT=PASS`, verify only:

1. production branch/ref is still the exact release SHA;
2. runtime HEAD is the exact release SHA;
3. API health remains OK;
4. Alembic remains `0054`;
5. deployed OpenAPI exposes:
   - `PATCH /graph/people/{person_id}`;
   - request body schema containing only the Person rename title contract;
6. existing `GET /graph/people-workspace` still exposes optional `window_index`.

Do not authenticate as the user or perform a live rename in this deploy task. Human acceptance will test the mutation from the rebuilt client.

### Explicitly out of scope

Do NOT:

- change backend/client product code;
- test rename by mutating a real Person in production;
- change generic object PATCH/embedding behavior;
- change Task actor semantics;
- change People/Task topology/window partitioning;
- change identity-candidate/email discovery;
- change salience;
- create schema/Alembic changes;
- call providers/models;
- run historical repair/backfill;
- modify role-import extraction;
- build/install the user's client;
- start shared-topology or identity-candidate work;
- perform a second deploy after a consumed live failure/rollback;
- perform BREAK-GLASS recovery.

### Completion protocol

On successful rollout:

1. update `PROJECT_STATE.md` with exact release/rollback SHA, deploy result, health, Alembic, and OpenAPI verification only;
2. replace this file with `HOLD`, recording production runtime SHA and checks;
3. commit + push ledger changes to canonical `main`;
4. STOP.

On blocked/failed/rolled-back rollout:

1. record only sanitized factual outcome;
2. replace this file with `HOLD`;
3. commit + push;
4. STOP.

Do not begin topology/email-candidate work automatically.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
