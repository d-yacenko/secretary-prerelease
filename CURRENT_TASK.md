# CURRENT_TASK

HOLD

## REL1D-HG5C — schema-neutral production rollout for shared Task/People semantic windows

Result: `DEPLOYMENT=PASS`

Release / runtime SHA:
`0031f531d1215970093bea7add44fcd2259ec71b`

Rollback SHA:
`50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

Alembic:
`0054 (head)`

Harness: `python3 ops/production/deploy.py --release-sha 0031f531d1215970093bea7add44fcd2259ec71b --rollback-sha 50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f --expected-alembic 0054`

Checks: `HEALTH=PASS`, DB container/volume unchanged, environment file unchanged, API and worker recreated, exit 0. GitHub `production`, runtime HEAD, and runtime `origin/production` equal the release SHA. OpenAPI keeps optional `window_index` on `GET /graph/workspace` and `GET /graph/people-workspace`, and `PATCH /graph/people/{person_id}` with title-only body.

No live Person/Task mutation and no second deploy.

Production remains:
`0031f531d1215970093bea7add44fcd2259ec71b`

Alembic remains:
`0054 / 0054`
