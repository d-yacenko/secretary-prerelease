# Current task — PP1-HG3-R1: schema-neutral production rollout

## State

- Accepted HG3 source release: `9aaeb8db1a04851bcae17aa50f9a4d185c2753bb`.
- Current production/runtime/origin-production: `07bd8bafdb2f53a6a8475fc2d792687fa373a149`.
- Alembic is `0051` in both release and production.
- Git compare: release is 24 commits ahead / 0 behind; merge-base is current production.
- No Alembic-path changes exist between production and release.
- Human HG3 visual direction is promising, but semantic acceptance is invalid until this backend rollout is complete.

## Goal

Perform the one authorized **schema-neutral** production rollout of exact release:

`9aaeb8db1a04851bcae17aa50f9a4d185c2753bb`

from rollback/base:

`07bd8bafdb2f53a6a8475fc2d792687fa373a149`

using only the canonical production deploy harness:

`ops/production/deploy.py`

No migration is authorized or required.

## Preflight

Before changing production:

1. Read `AGENTS.md`, `docs/executor_bootstrap.md`, and `docs/deploy.md`.
2. Verify current `origin/production` is exactly the rollback SHA above.
3. Verify release is a non-force fast-forward descendant of rollback.
4. Verify there are no Alembic-path changes and expected Alembic remains exactly `0051`.
5. Verify the canonical deployment harness and target contract are intact.
6. Verify canonical bootstrap/pinned-host-key readiness.

If any fact differs, STOP without changing production.

## Production ref

Move `origin/production` only by normal non-force fast-forward to exact release `9aaeb8db1a04851bcae17aa50f9a4d185c2753bb`.

Immediately verify the ref equals that exact SHA.

Never force-push.

## Deployment

Run only `ops/production/deploy.py` with:

- release SHA = `9aaeb8db1a04851bcae17aa50f9a4d185c2753bb`
- rollback SHA = `07bd8bafdb2f53a6a8475fc2d792687fa373a149`
- expected Alembic = `0051`

The canonical harness owns remote checkout, build/recreate, health checks, and rollback behavior.

Success requires:

- deployment PASS;
- production checkout/runtime exact release SHA;
- health PASS;
- Alembic exactly `0051`;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- only api/worker recreated as required by the harness;
- rollback unused.

## Do not exercise production Person writes

During rollout verification:

- do not approve candidates;
- do not suppress/restore candidates;
- do not rename Person objects;
- do not create test People;
- do not create Task-Person edges;
- do not call providers/models for test purposes;
- do not install/replace the client.

The user will perform the semantic human gate afterward with the existing HG3 bundle.

## Failure handling

Use only the deploy harness's canonical rollback/result. Do not improvise direct SSH/Compose recovery, data edits, or ref rewrites.

On failure, record sanitized facts and STOP.

## Completion

1. Record exact deployment result in `PROJECT_STATE.md`.
2. Return `CURRENT_TASK.md` to HOLD with:
   - exact production/runtime SHA;
   - Alembic `0051`;
   - health result;
   - DB/container/env preservation facts;
   - rollback status;
   - HG3 human semantic acceptance still pending.
3. Commit/push documentation to `main`.
4. Report exact refs/result and STOP.

Do not start Person Knowledge, Organization, relationships, task-creation promotion prompts, scan-cap changes, MCP, G3B, or S3.
