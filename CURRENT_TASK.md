# Current task — Production Migration Rollout M3: exact Telegram MTProto cutover

## Status

Telegram MTProto product chain A1/A2 through C3B is ACCEPTED.

RF1/RF1R release freeze is ACCEPTED.

The only Architect-authorized M3 release candidate is exactly:
`M3_RELEASE_SHA=8091736337689b68b4510126e74d9e409397f696`

RF1 validated product base:
`e503f680543d2eeafbfbb9b641b1b1942d7990ca`

The product-base SHA above is NOT an authorized release SHA.

RF1 head:
`a90716602d35cf5525554a1005a543dd8dda5491`
is superseded and is NOT authorized for deployment.

Exact production rollback/runtime SHA:
`M3_ROLLBACK_SHA=5cce4b57b14e0052a038acae1354a2821a2bb77b`

Exact schema transition:
`0041 -> 0046`

Repository migration head:
`0046`

No `0047` is authorized.

RF1/RF1R integration merge on main:
`9e74e892fa133b68679af1e3152d0a6947cd99f6`

This task authorizes M3 production cutover only through the accepted migration harness.

Telegram Bot API retirement remains NOT AUTHORIZED.
Production MTProto login/history import remains NOT AUTHORIZED during M3.

## Mandatory execution path

Use only:
- `ops/production/migrate_deploy.py`
- its accepted streamed `remote_migrate_deploy.py`
- existing committed production target / strict SSH host-key contract
- existing accepted runtime-verification helpers

Do NOT use ad-hoc SSH/Compose/Alembic commands as a substitute for the harness.
Do NOT modify deployment scripts during execution.

If the harness reports a blocker, STOP and report it. Do not improvise around it.

## Local preflight before production ref move

Required:
- local branch is `main`;
- local worktree clean;
- `git fetch --prune origin`;
- local `HEAD == origin/main`;
- exact release SHA resolves:
  `8091736337689b68b4510126e74d9e409397f696`;
- exact rollback SHA resolves:
  `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- rollback is an ancestor of release;
- repository Alembic has exactly one head: `0046`;
- no `0047`;
- exact migration delta from rollback to release is only accepted `0042..0046`;
- current remote `origin/production` is exactly rollback SHA before ref move.

If any local preflight fails:
- do NOT move `production`;
- do NOT contact production for mutating actions;
- report M3 BLOCKED.

## Exact production ref move

Only after all local preflight checks pass, move:

`refs/heads/production`

from exact expected old SHA:

`5cce4b57b14e0052a038acae1354a2821a2bb77b`

to exact release SHA:

`8091736337689b68b4510126e74d9e409397f696`

Use an atomic expected-old/lease guard. Do not use an unguarded force push.

After the move:
- fetch/verify `origin/production`;
- require exact equality to release SHA before invoking the migration harness.

If the guarded ref move fails:
- STOP;
- do not run migration harness;
- report M3 BLOCKED.

## Exact harness execution

Run the accepted harness with exact arguments:

`--release-sha 8091736337689b68b4510126e74d9e409397f696`
`--rollback-sha 5cce4b57b14e0052a038acae1354a2821a2bb77b`
`--from-alembic 0041`
`--to-alembic 0046`

No other release/rollback/from/to value is authorized.

The harness must itself prove before destructive progress:
- strict production host identity;
- canonical repository/origin;
- clean production checkout;
- current production checkout exact rollback SHA;
- `origin/production` exact release SHA;
- db/api/worker state valid;
- API health PASS;
- DB TCP auth PASS;
- DB revision exact `0041`;
- production env file present and unchanged;
- release Compose environment valid;
- Telegram API credentials present/valid without printing values;
- DB/credential-key invariants unchanged;
- candidate build succeeds before downtime.

Accepted sequence:
1. build release api/worker while old application is live;
2. stop api + worker only;
3. keep DB container/volume unchanged;
4. migrate exactly to `0046`;
5. verify direct DB revision `0046`;
6. recreate/start api + worker only;
7. verify DB container/volume/.env unchanged;
8. verify api/worker recreated and running;
9. verify health PASS;
10. verify direct DB revision exact `0046`.

## Failure/ref reconciliation rules

The Git `production` ref must not be left knowingly inconsistent with the final recovered runtime.

### A. Failure before migration/live cutover, rollback runtime remains/restores 5cce...

If harness fails and proves/returns to:
- application runtime = rollback SHA;
- DB = `0041`;
- old api/worker healthy;

then restore `refs/heads/production` from exact release SHA back to exact rollback SHA using an expected-old/lease guard.

Verify remote ref = rollback SHA.

Then STOP and report M3 FAILED / ROLLED BACK.

### B. Migration started but accepted automatic pre-live rollback succeeds

If harness:
- downgrades DB back to `0041`;
- restores rollback app;
- health passes;

restore `production` ref back to rollback SHA with guarded expected-old semantics.

Then STOP and report M3 FAILED / ROLLED BACK.

### C. Successful cutover

If harness returns success:
- do NOT restore production ref;
- require production ref exact release SHA;
- continue post-cutover verification below.

### D. Break-glass / rollback blocked / uncertain state

If harness emits or implies:
- `BREAK_GLASS_REQUIRED=true`;
- rollback blocked because MTProto data exists;
- revision uncertainty;
- container/writer-state uncertainty;
- rollback/downgrade failed;
- DB/app state cannot be proven;

DO NOT move `production` ref again automatically.
DO NOT run ad-hoc downgrade, truncate/delete Telegram data, restore backup, or force app checkout.

STOP immediately and report exact sanitized markers/state for Architect review.

## Post-cutover verification after harness success

Verify using accepted/read-only tooling:

- `origin/production == 8091736337689b68b4510126e74d9e409397f696`;
- production checkout/runtime exact release SHA;
- DB Alembic exactly `0046`;
- one Alembic revision/head only;
- api running;
- worker running;
- DB healthy;
- health endpoint PASS;
- DB container identity unchanged from harness preflight;
- DB volume unchanged;
- `.env` unchanged;
- production Telegram credentials were not printed/modified;
- `SECRETARY_CREDENTIAL_KEY` unchanged;
- `TELEGRAM_MTPROTO_AI_ENABLED` remains false unless a pre-existing explicitly authorized production override says otherwise; do not mutate it in M3;
- source-sync MTProto interval resolves through accepted Compose contract;
- run existing production runtime verification appropriate to the deployment contract, including the accepted Google sync verification helper if its preconditions remain valid.

Do NOT log in a Telegram personal account during M3.
Do NOT run Telegram history import during M3.
Do NOT disable/delete the Bot API integration.

## Production data protection

M3 must not:
- recreate/remove DB service;
- replace DB volume;
- edit production `.env`;
- rotate credentials;
- expose secret values/hashes;
- delete/truncate MTProto tables;
- manually repair DB rows;
- run migration `0047`;
- perform an unreviewed forward fix.

Any such need is a blocker requiring a new Architect task.

## Final success criteria

M3 succeeds only if all are true:
- production ref exact release SHA;
- runtime exact release SHA;
- Alembic exact `0046`;
- health PASS;
- api + worker running;
- DB container/volume preserved;
- env preserved;
- no secret exposure;
- no unauthorized Telegram login/import;
- Bot API not retired;
- production worktree clean;
- no break-glass marker.

## Completion report

Return:
- `M3_RELEASE_SHA=8091736337689b68b4510126e74d9e409397f696`;
- `M3_ROLLBACK_SHA=5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- starting `origin/production` SHA;
- guarded production-ref move result;
- harness exact command arguments;
- harness sanitized output markers;
- migration result;
- final DB Alembic revision;
- final production ref;
- final runtime/checkout SHA;
- api/worker/db health/state;
- DB container/volume preservation;
- env preservation;
- runtime verification results;
- confirmation no secret values were printed;
- confirmation no Telegram login/history import occurred;
- confirmation Bot API retirement did not occur;
- final production worktree cleanliness.

Success marker:
`PRODUCTION_MIGRATION_ROLLOUT_M3_SUCCESS`

If clean rollback restored old runtime/schema/ref:
`PRODUCTION_MIGRATION_ROLLOUT_M3_ROLLED_BACK`

If blocked before mutation:
`PRODUCTION_MIGRATION_ROLLOUT_M3_BLOCKED`

If break-glass/manual Architect decision is required:
`PRODUCTION_MIGRATION_ROLLOUT_M3_BREAK_GLASS_REQUIRED`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
