# Current task — Deploy bidirectional communication feed parity

## Human authorization

Human explicitly authorized production deployment of exact commit:

`d22c6cf78945c8f92934a46431b2bcc1887fd8c8`

This authorization covers only the normal schema-neutral deployment of that exact release.

It does NOT authorize:
- switching `TELEGRAM_MTPROTO_AI_ENABLED` to true;
- live Telegram/provider testing;
- manual Telegram sync;
- manual job enqueue;
- historical catch-up/backlog;
- old E2E harness execution;
- direct production SSH;
- manual Docker/Compose;
- environment changes;
- production DB writes;
- any code change.

The canonical `production` branch has already been fast-forwarded non-force to the exact authorized release SHA.

## Exact deployment parameters

Release SHA:

`d22c6cf78945c8f92934a46431b2bcc1887fd8c8`

Rollback SHA / current production runtime:

`681c0e04df5881124ab8d72a4c05e5a2c7977296`

Expected Alembic:

`0046`

This is a schema-neutral application-only release.

## Required execution

Use the normal committed deployment harness only.

From the canonical clean local checkout:

```bash
cd ~/work/secretary-prerelease
git switch main
git pull --ff-only
git fetch --prune origin main production
python3 ops/production/deploy.py \
  --release-sha d22c6cf78945c8f92934a46431b2bcc1887fd8c8 \
  --rollback-sha 681c0e04df5881124ab8d72a4c05e5a2c7977296 \
  --expected-alembic 0046
```

Do not substitute another deploy path.
Do not use direct SSH or manual Docker/Compose.

## Expected success evidence

Successful deployment must report:

- `RELEASE_HEAD=d22c6cf78945c8f92934a46431b2bcc1887fd8c8`
- `HEALTH=PASS`
- `ALEMBIC=0046`
- `DB_CONTAINER_UNCHANGED=true`
- `DB_VOLUME_UNCHANGED=true`
- `ENV_FILE_UNCHANGED=true`
- `API_RECREATED=true`
- `WORKER_RECREATED=true`
- `DEPLOYMENT=PASS`

The harness may automatically rollback to exact `681c0e04df5881124ab8d72a4c05e5a2c7977296` if a post-recreate invariant fails.

## Failure handling

On any:
- `DEPLOYMENT_BLOCKED=...`;
- `DEPLOYMENT=FAILED:...`;
- nonzero exit;
- `ROLLBACK=FAILED`;
- missing required success evidence;

STOP.

Do not retry.
Do not repair production.
Do not run direct SSH.
Do not run manual Docker/Compose.
Do not change env.
Do not move refs again.

Return complete sanitized stdout/stderr and exact exit status.

## Post-deploy boundary

Even after `DEPLOYMENT=PASS`, STOP.

Do not:
- switch Telegram AI true;
- run live Telegram/provider tests;
- manually trigger sync;
- manually enqueue jobs;
- run old E2E harness.

The deployed change is only presentation/feed parity. Future activation of full Telegram AI remains a separate explicit authorization boundary.

Update `PROJECT_STATE.md` factually with deployment result only, then STOP.
