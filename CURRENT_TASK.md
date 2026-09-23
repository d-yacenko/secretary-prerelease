# Current task — Authorized production deploy + first public_web rollout

## Human authorization

Explicitly authorized:
- schema-neutral production deploy of `3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`;
- recreate only API/worker via the normal deploy harness;
- rollback SHA `2a5d76ae80d53c13a6581852ef1a0362ad1a3e38`;
- expected Alembic `0046`;
- move canonical `production` ref to `3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`;
- after successful deploy, run the first production `public_web` rollout for the same release.

Not authorized:
- Google Cloud/OAuth changes;
- DNS/firewall changes;
- production env changes;
- direct/manual production SSH or Docker/Compose;
- DB writes outside the normal deploy/Alembic health contract;
- any release other than the exact SHA above.

## Required sequence

1. Verify preflight:
   - current production ref is rollback SHA;
   - release is a clean fast-forward;
   - no Alembic/migration files changed.
2. Move canonical `production` ref non-force to the exact release SHA.
3. Run only:
   `python3 ops/production/deploy.py --release-sha 3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c --rollback-sha 2a5d76ae80d53c13a6581852ef1a0362ad1a3e38 --expected-alembic 0046`
4. Require deploy PASS before continuing.
5. Then run only:
   `python3 ops/production/public_web_rollout.py --release-sha 3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`
6. Require public_web PASS:
   - HTTPS home/privacy/terms = 200;
   - unrelated page = 404;
   - DB/API/worker/.env identities unchanged during public_web rollout.
7. Record sanitized evidence in `PROJECT_STATE.md`, return CURRENT_TASK to HOLD, STOP.

## Safety

Use only the repository production harnesses.
No direct SSH.
No manual Docker/Compose.
No Google Cloud/OAuth mutation.
No DNS/firewall mutation.
