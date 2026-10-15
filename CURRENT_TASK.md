# CURRENT_TASK

ACTIVE

## REL1D-HG5C — schema-neutral production rollout for shared Task/People semantic windows

### Context

REL1D-HG5B / HG5B.1 are Architect-accepted.

Accepted release baseline:

`0031f531d1215970093bea7add44fcd2259ec71b`

Current production / rollback:

`50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

Alembic remains:

`0054 / 0054`

Architect comparison confirms:

- release is a fast-forward descendant of current production;
- no migration/Alembic files are changed;
- backend runtime delta is limited to accepted shared semantic-window helpers/projection in:
  - `backend/app/services/graph_workspace_service.py`;
  - `backend/app/services/person_graph_workspace_service.py`;
- remaining delta is client/tests/ledger/read-only HG5A audit tooling.

### Goal

Roll the accepted schema-neutral shared Task/People semantic-window release to canonical production using only the committed production deployment contract, verify runtime/health/Alembic/API compatibility, record the exact result, and stop.

No new product coding is authorized.

### Exact refs

Release SHA:

`0031f531d1215970093bea7add44fcd2259ec71b`

Rollback SHA:

`50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

Expected Alembic:

`0054`

Before any production ref movement:

- fetch canonical `origin/main` and `origin/production`;
- verify `origin/main` contains the exact release SHA;
- verify `origin/production` is exactly the rollback SHA;
- verify release is a descendant/fast-forward of rollback;
- verify migration/Alembic delta is empty;
- verify committed deploy bootstrap/runtime prerequisites.

If any invariant differs, STOP. Do not choose another release or repair production.

### Production ref movement

Fast-forward canonical GitHub `production` exactly:

from:
`50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

to:
`0031f531d1215970093bea7add44fcd2259ec71b`

No force push.

Re-fetch and require `origin/production` to equal the release SHA before deploy.

### Deployment

Use only:

`ops/production/deploy.py`

with exactly:

- `--release-sha 0031f531d1215970093bea7add44fcd2259ec71b`
- `--rollback-sha 50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`
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

If harness rollback triggers, report and STOP. No second deployment attempt in this task.

### Post-deploy read-only verification

After `DEPLOYMENT=PASS`, verify only:

1. GitHub `production`, runtime HEAD, and runtime `origin/production` equal the exact release SHA.
2. API health remains OK.
3. Alembic remains `0054`.
4. OpenAPI still exposes:
   - `GET /graph/workspace` with optional `window_index`;
   - `GET /graph/people-workspace` with optional `window_index`;
   - `PATCH /graph/people/{person_id}`.
5. No schema/API-shape regression is visible from OpenAPI.

Do not perform live Person/Task mutations or authenticated topology acceptance in this deploy task. Human acceptance will use a rebuilt client.

### Explicitly out of scope

Do NOT:

- change backend/client product code;
- alter Task semantic packing or coordinates;
- alter People semantic membership policy;
- add a home-window policy;
- change identity-candidate/email discovery;
- change Task actor semantics;
- change salience;
- add schema/Alembic changes;
- call providers/models;
- run historical repair/backfill;
- modify role-import extraction;
- build/install the user's client;
- start the email-candidate phase;
- perform a second deploy after a consumed live failure/rollback;
- perform BREAK-GLASS recovery.

### Completion protocol

On success:

1. update `PROJECT_STATE.md` with exact release/rollback SHA, deploy result, health, Alembic, and OpenAPI verification;
2. replace this file with `HOLD`, recording production runtime SHA and checks;
3. commit + push ledger changes to canonical `main`;
4. STOP.

On blocked/failed/rolled-back rollout:

1. record only sanitized factual outcome;
2. replace this file with `HOLD`;
3. commit + push;
4. STOP.

No next coding phase without fresh Architect authorization.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
