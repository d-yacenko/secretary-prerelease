# CURRENT_TASK

HOLD

## REL1D-HG4F — schema-neutral production rollout for accepted Person rename

Production runtime SHA: `50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

Rollback SHA: `a9221699b4b725888213ff38e6673495a512042c`

Canonical `production` was non-force fast-forwarded from the rollback SHA to the release SHA. `python3 ops/production/deploy.py --release-sha 50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f --rollback-sha a9221699b4b725888213ff38e6673495a512042c --expected-alembic 0054` returned exit 0:

- `DEPLOYMENT=PASS`
- `RELEASE_HEAD=50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`
- `HEALTH=PASS`
- `ALEMBIC=0054`
- `DB_CONTAINER_UNCHANGED=true`
- `DB_VOLUME_UNCHANGED=true`
- `ENV_FILE_UNCHANGED=true`
- `API_RECREATED=true`
- `WORKER_RECREATED=true`

Post-deploy read-only checks: GitHub `production`, runtime HEAD, and runtime `origin/production` equal the release SHA; health is `{"status":"ok"}`; Alembic is `0054 (head)`; OpenAPI `PATCH /graph/people/{person_id}` accepts only `title` (`additionalProperties` false); `GET /graph/people-workspace` still has optional `window_index`.

No live Person rename was performed. Human acceptance from a rebuilt client remains separate.

Alembic remains:
`0054 / 0054`
