# Current task — HOLD

## State

- PP1-HG3-R1 schema-neutral production rollout: SUCCESS.
- Production application/runtime and `origin/production`: `9aaeb8db1a04851bcae17aa50f9a4d185c2753bb`.
- Rollback SHA, unused: `07bd8bafdb2f53a6a8475fc2d792687fa373a149`.
- Health: PASS.
- Alembic: `0051`.
- DB container unchanged, DB volume unchanged, `.env` unchanged.
- Only `api` and `worker` were recreated.
- No production Person writes were made.
- HG3 human semantic acceptance is still pending on the existing HG3 bundle.

## Stop

Do not deploy again. Do not start Person Knowledge, Organization, relationships, task-creation promotion prompts, scan-cap changes, MCP, G3B, or S3. Wait for the next explicit authorization.
