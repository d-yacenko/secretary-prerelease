# Current task — Continue authorized production deploy + first public_web rollout

## Human authorization

Explicitly authorized:
- schema-neutral production deploy of `3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`;
- recreate only API/worker via the normal deploy harness;
- rollback SHA `2a5d76ae80d53c13a6581852ef1a0362ad1a3e38`;
- expected Alembic `0046`;
- first production `public_web` rollout for the same release after deploy PASS.

## Current canonical state

Architect verified:
- the `public_web` stopped/exited-container correction at `3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c` is ACCEPTED / DEPLOY-READY;
- canonical `production` ref has already been moved non-force from the rollback SHA to exact release `3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`;
- the prior Architect-side execution attempt did not start the deploy harness;
- last recorded production runtime remains `2a5d76ae80d53c13a6581852ef1a0362ad1a3e38`;
- no `public_web` rollout has been accepted as executed.

Do not move, rewind, or recreate the `production` ref as part of this continuation. If the authoritative fetched `origin/production` is not the exact release SHA, STOP and report the mismatch.

## Required Executor sequence

1. Bootstrap from a fresh/canonical clean checkout according to `AGENTS.md` and `docs/executor_bootstrap.md`.
2. Fetch authoritative `origin/main` and `origin/production`, then verify:
   - `origin/production == 3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`;
   - release is a clean fast-forward descendant of rollback `2a5d76ae80d53c13a6581852ef1a0362ad1a3e38`;
   - no Alembic/migration files changed in that delta.
3. Run only:
   `python3 ops/production/deploy.py --release-sha 3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c --rollback-sha 2a5d76ae80d53c13a6581852ef1a0362ad1a3e38 --expected-alembic 0046`
4. Require deploy PASS before continuing. On any bootstrap/deploy blocker, record one sanitized blocker and STOP. Do not use direct SSH/manual Docker as a workaround.
5. After deploy PASS, run only:
   `python3 ops/production/public_web_rollout.py --release-sha 3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`
6. Require `public_web` PASS:
   - HTTPS home/privacy/terms = 200;
   - unrelated page = 404;
   - DB/API/worker/.env identities unchanged during `public_web` rollout.
7. Record sanitized evidence in `PROJECT_STATE.md`, return `CURRENT_TASK.md` to HOLD, commit/push, and STOP.

## Not authorized

- Google Cloud/OAuth changes;
- DNS/firewall changes;
- production env changes;
- direct/manual production SSH or Docker/Compose;
- DB writes outside the normal deploy/Alembic health contract;
- any release other than the exact SHA above;
- Telegram AI changes or unrelated product work.
