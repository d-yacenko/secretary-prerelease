# Current task — AUTHORIZED production deploy of Quick UX bugfix pack

## Human authorization

Human explicitly authorized deployment of exact commit:

`2a5d76ae80d53c13a6581852ef1a0362ad1a3e38`

to production.

This authorization is ONLY for the normal schema-neutral application deploy described below.

## Exact release parameters

Release SHA:

`2a5d76ae80d53c13a6581852ef1a0362ad1a3e38`

Rollback SHA:

`d22c6cf78945c8f92934a46431b2bcc1887fd8c8`

Expected Alembic:

`0046`

Canonical `production` ref has already been fast-forwarded non-force to the exact release SHA.

The release is schema-neutral relative to rollback:
- no Alembic migration file changes;
- expected DB schema remains 0046.

## Required execution

Bootstrap exactly per `docs/executor_bootstrap.md`.

Then execute the normal production deployment only through:

```bash
python3 ops/production/deploy.py \
  --release-sha 2a5d76ae80d53c13a6581852ef1a0362ad1a3e38 \
  --rollback-sha d22c6cf78945c8f92934a46431b2bcc1887fd8c8 \
  --expected-alembic 0046
```

Do not substitute another deploy path.

## Acceptance requirements

Report the sanitized terminal deployment evidence from the harness, including:
- RELEASE_HEAD
- HEALTH
- ALEMBIC
- DB_CONTAINER_UNCHANGED
- DB_VOLUME_UNCHANGED
- ENV_FILE_UNCHANGED
- API_RECREATED
- WORKER_RECREATED
- DEPLOYMENT
- exit status
- whether rollback was used

Expected success:
- release head = exact authorized SHA;
- health PASS;
- Alembic 0046;
- DB container unchanged;
- DB volume unchanged;
- .env unchanged;
- API recreated;
- worker recreated;
- deployment PASS;
- rollback unused.

## Authorization boundaries

This deploy does NOT authorize:
- changing Google Cloud OAuth publishing status;
- real Google OAuth reauthorization;
- provider calls/diagnostics;
- changing TELEGRAM_MTPROTO_AI_ENABLED;
- changing production env;
- direct SSH;
- direct/manual Docker or Compose;
- DB writes outside the deploy harness;
- schema migration;
- any follow-up repair if the harness fails.

If any preflight/invariant fails, STOP and report the sanitized blocker.

If the deploy succeeds, update `PROJECT_STATE.md` with factual deployment evidence, commit + push, and STOP.

Google OAuth publishing-mode correction and one-time Google reconnect remain separate human/operator steps after deployment.
