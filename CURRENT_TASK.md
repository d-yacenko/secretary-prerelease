# Current task — PC1-R1: schema-neutral production rollout

## State

- Accepted PC1-H1 source release: `a3d546b069e7e05d68fd42906c662c3ba34caef5`.
- Current production/runtime/origin-production: `9aaeb8db1a04851bcae17aa50f9a4d185c2753bb`.
- Alembic is `0051` in both release and production.
- Git compare: release is 17 commits ahead / 0 behind; merge-base is current production.
- No Alembic-path changes exist between production and release.
- Canonical `ops/production/deploy.py` is byte-identical between production and release.
- PC1 source + H1 preservation correction are accepted. Human merge/undo gate is pending after rollout.

## Goal

Perform the one authorized **schema-neutral** production rollout of exact release:

`a3d546b069e7e05d68fd42906c662c3ba34caef5`

from rollback/base:

`9aaeb8db1a04851bcae17aa50f9a4d185c2753bb`

using only:

`ops/production/deploy.py`

No migration is authorized or required.

## Preflight

Before changing production:

1. Read `AGENTS.md`, `docs/executor_bootstrap.md`, and `docs/deploy.md`.
2. Verify current `origin/production` is exactly the rollback SHA above.
3. Verify exact release is a normal fast-forward descendant of rollback.
4. Verify there are no Alembic-path changes and repository/runtime expected Alembic is exactly `0051`.
5. Verify canonical `ops/production/deploy.py` still matches the accepted release contract and has not diverged from production.
6. Verify bootstrap/pinned-host-key readiness.

If any fact differs, STOP without changing production.

## Production ref

Move `origin/production` only by normal non-force fast-forward to exact release `a3d546b069e7e05d68fd42906c662c3ba34caef5`.

Immediately verify the ref equals that exact SHA.

Never force-push.

## Deployment

Run only the canonical `ops/production/deploy.py` with:

- release SHA = `a3d546b069e7e05d68fd42906c662c3ba34caef5`;
- rollback SHA = `9aaeb8db1a04851bcae17aa50f9a4d185c2753bb`;
- expected Alembic = `0051`.

Success requires:

- `DEPLOYMENT=PASS`;
- production checkout/runtime exact release SHA;
- health PASS;
- Alembic exactly `0051`;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- only api/worker recreated as required by the harness;
- rollback unused.

## Production data safety

Do not exercise Person merge/undo during deployment verification.

Do not:

- create/approve/suppress/restore Person candidates;
- rename Person;
- merge or undo Person;
- create/remove Task-Person actor roles;
- create test Person data;
- call providers/models for test purposes;
- install or replace the client.

The user will run the human PC1 merge/undo gate afterward with the already built PC1 client bundle.

## Failure handling

Use only the canonical deploy harness result/rollback behavior.

Do not improvise direct SSH/Compose repair, DB edits, identity rewrites, merge-audit edits, or force ref changes.

On failure, record sanitized facts and STOP.

## Completion

1. Record exact deployment result in `PROJECT_STATE.md`.
2. Return `CURRENT_TASK.md` to HOLD with:
   - exact production/runtime SHA;
   - Alembic `0051`;
   - health result;
   - DB/container/env preservation facts;
   - rollback status;
   - PC1 human merge/undo gate still pending.
3. Commit/push documentation to `main`.
4. Report exact refs/result and STOP.

Do not start Task↔Person visualization, People Landscape, Secretary Person context, Organization/social roles, graph stabilization, MCP, G3B, or S3.
