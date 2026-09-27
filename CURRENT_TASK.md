# Current task — Production D2: deploy exact main release with 0047 -> 0050

Production D1 is accepted.

This task AUTHORIZES one live production/preprod rollout.

## Exact identities

Release SHA:
`fd45df20ff53ad973f22e461ff84f3cb5c251b8a`

Rollback SHA / current production:
`296b4735f9473ea60ef22f1827ed94260603128e`

Schema:
`0047 -> 0050`

Dedicated entrypoint:
`ops/production/migrate_people_tasks_0050.py`

Do not substitute another SHA.
Do not deploy HEAD by name.
Do not use the schema-neutral `deploy.py`.

## Bootstrap

Use the canonical Executor bootstrap in `AGENTS.md` and `docs/executor_bootstrap.md`.

Use a fresh canonical checkout if the current checkout is wrong-origin/dirty/stale.

Verify before any production mutation:
- canonical repo is `d-yacenko/secretary-prerelease`;
- release SHA resolves exactly;
- rollback SHA resolves exactly;
- rollback is ancestor of release;
- current `origin/production` is exactly the rollback SHA before promotion;
- committed production target/pin is valid.

If any precondition fails, STOP with one sanitized blocker.

## Pre-deploy local checks

Before promoting `origin/production`, run the D1 focused harness tests and exact migration-delta validation against the authorized release.

At minimum:
- `ops/production/tests/test_migrate_people_tasks_0050.py`;
- existing migration deploy tests relevant to target/pin/secret safety;
- `git diff --check`.

If these fail, STOP. Do not promote production.
Do not run manual Flutter UI checks.

## Promote production ref

If pre-deploy checks pass, fast-forward the remote production ref from exactly:
`296b4735f9473ea60ef22f1827ed94260603128e`
to exactly:
`fd45df20ff53ad973f22e461ff84f3cb5c251b8a`

Fail closed if the remote ref changed concurrently.
Do not force-push.
Do not move any other branch/tag.
After promotion, verify `origin/production` resolves to the exact release SHA.

## Execute migration rollout

From the exact release checkout, run only:

    python3 ops/production/migrate_people_tasks_0050.py \
      --release-sha fd45df20ff53ad973f22e461ff84f3cb5c251b8a \
      --rollback-sha 296b4735f9473ea60ef22f1827ed94260603128e \
      --from-alembic 0047 \
      --to-alembic 0050

Do not bypass harness guards.
Do not use direct SSH/Compose.
Do not manually run Alembic on production.

## Required success evidence

A successful D2 report must establish all of:
- migration harness returned PASS;
- production checkout/runtime is exact release SHA;
- Alembic is exactly `0050`;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- api recreated and running;
- worker recreated and running;
- health PASS;
- `person_identities` table exists;
- `person_identity_evidence` table exists;
- `objects.completion_mode` exists;
- no Task has NULL completion_mode;
- no invalid Task completion_mode;
- no non-Task was backfilled with a mode.

Use only aggregate/boolean output. Do not print titles, bodies, identities, messages, tokens, credentials, or other PII/secrets.

## Backend contract verification after health

After successful harness completion, perform bounded read-only verification against the deployed API/runtime without changing user data.

Prefer deployed OpenAPI or in-container/import-level route inspection if no authenticated read is needed.

Prove:
- Task PATCH schema includes `completion_mode`;
- manual Capture request includes `completion_mode`;
- Task profile route `GET /tasks/{task_id}/profile` is registered;
- deployed code exposes the current Graph People workspace route expected by main.

No user token creation is needed for these checks.
Do not manufacture Tasks/People in production.
Do not create an ongoing Direction on behalf of the user.

If these read-only contract checks fail after otherwise successful cutover, report the failure and STOP for Architect review. Do not improvise a schema downgrade solely for an inspection mismatch.

## Rollback behavior

Let the dedicated harness own rollback.
Do not improvise rollback outside the harness.

If it reports successful automatic rollback: report production runtime/revision and STOP.
If it reports `BREAK_GLASS_REQUIRED=true`: do not delete/convert any data, do not retry, do not downgrade manually, STOP immediately.

After release runtime starts, automatic downgrade is intentionally blocked if Person identity/evidence rows exist, an ongoing Task exists, or safety cannot be proven.

## Client boundary

Do not open or click through Flutter UI.
Do not change the user's saved API URL/token.
Do not install a new client unless a separate explicit task authorizes client installation.

Record whether the already-built current-main/S2 client remains the expected client for human validation. The user will manually use/point their client against production after D2.

## Production scope guard

Do NOT:
- start S3;
- start H2D;
- change code during rollout;
- fix unrelated failures;
- run provider-specific probes;
- touch Telegram configuration/login/scope;
- run manual UI scenarios;
- create test Tasks/People on production;
- rotate secrets;
- recreate DB;
- change `.env`.

## Completion

On success, update `PROJECT_STATE.md` with:
- exact release SHA;
- exact production ref/runtime SHA;
- Alembic `0050`;
- harness result;
- DB/container/volume/env preservation;
- health result;
- structural migration checks;
- backend contract verification;
- whether client update/install is still required;
- confirmation no manual UI/data creation was performed.

Return `CURRENT_TASK.md` to HOLD.
Push documentation-only completion commit to `main` if required by the normal Executor workflow.
STOP.

Do not begin human visual validation yourself.
