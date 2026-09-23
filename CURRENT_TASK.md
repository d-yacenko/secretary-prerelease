# Current task — Deploy accepted self-authored Telegram normal-pipeline policy

## Human authorization

Human explicitly authorized production deployment of exact commit:

`681c0e04df5881124ab8d72a4c05e5a2c7977296`

for subsequent live verification of the normal Telegram pipeline.

This authorization covers only the normal schema-neutral deployment of that exact release.

It does NOT authorize:
- running the old Telegram E2E harness;
- manually sending/provider-driving Telegram messages on behalf of the human;
- direct production SSH;
- manual Docker/Compose;
- changing production environment variables;
- setting `TELEGRAM_MTPROTO_AI_ENABLED=true`;
- manual job enqueue;
- historical catch-up/backlog;
- provider diagnostics;
- any code change.

The canonical `production` branch has been fast-forwarded non-force to the exact authorized release SHA before this task.

## Exact deployment parameters

Release SHA:

`681c0e04df5881124ab8d72a4c05e5a2c7977296`

Rollback SHA / current production runtime:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

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
  --release-sha 681c0e04df5881124ab8d72a4c05e5a2c7977296 \
  --rollback-sha 8ad52f0653f9f90e1932c49532dc4f993ea1a9cc \
  --expected-alembic 0046
```

Do not substitute any other deploy path.
Do not use direct SSH or manual Docker/Compose.

## Expected success evidence

Successful deployment must report:

- `RELEASE_HEAD=681c0e04df5881124ab8d72a4c05e5a2c7977296`
- `HEALTH=PASS`
- `ALEMBIC=0046`
- `DB_CONTAINER_UNCHANGED=true`
- `DB_VOLUME_UNCHANGED=true`
- `ENV_FILE_UNCHANGED=true`
- `API_RECREATED=true`
- `WORKER_RECREATED=true`
- `DEPLOYMENT=PASS`

The harness may automatically rollback to exact `8ad52f0653f9f90e1932c49532dc4f993ea1a9cc` if a post-recreate invariant fails.

## Failure handling

On any:
- `DEPLOYMENT_BLOCKED=...`;
- `DEPLOYMENT=FAILED:...`;
- nonzero exit;
- `ROLLBACK=FAILED`;
- missing required success evidence;

STOP.

Do not repair production.
Do not retry deployment.
Do not run direct SSH.
Do not run manual Docker/Compose.
Do not change env.
Do not move refs again.

Return complete sanitized deploy stdout/stderr and exact exit status.

## Post-deploy boundary

Even after `DEPLOYMENT=PASS`, STOP.

Do not run the old E2E harness.
Do not manually invoke Telegram sync.
Do not enqueue jobs.
Do not perform provider diagnostics.
Do not change the global Telegram AI flag.

The intended next live acceptance is a brand-new ordinary Telegram message sent by the human from the connected Telegram account in an active-scope chat, followed by separately authorized/read-only inspection of the normal backend pipeline evidence.

Update `PROJECT_STATE.md` factually with deployment result only, then STOP.
