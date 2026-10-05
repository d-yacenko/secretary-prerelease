# CURRENT_TASK

ACTIVE

## REL1D-HG2D2 — schema-neutral production backend rollout of the qualified HG2 release

REL1D-HG2D1.1 is ARCHITECT ACCEPTED.

The frozen candidate is now ARCHITECT RELEASE-QUALIFIED under the explicitly recorded production-baseline no-regression gate.

Exact release SHA:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Exact rollback/current production SHA:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Expected Alembic:

`0054`

This task authorizes exactly ONE normal schema-neutral backend production rollout using the committed Production Deploy Contract v2.

It does NOT authorize:
- any provider call;
- any HG2 data repair/backfill;
- any sync/reconcile run;
- any client build/install;
- any schema migration;
- any model call;
- human REL1D acceptance;
- any next phase.

## Qualification basis

Do not rerun D1/D1.1 unless a bootstrap invariant requires it.

The accepted release basis is already recorded:

- focused HG2 union: 241 passed / 0 failed;
- candidate-only pytest failures/errors relative to production baseline: 0;
- 109 candidate-only/new node ids passed;
- candidate-only Ruff findings relative to production baseline: 0;
- rollback and candidate Ruff totals both 96, all common and in unchanged files;
- rollback -> candidate: 56 commits / 37 files;
- migration-infrastructure delta: 0;
- `ops/production/` delta: 0;
- `git diff --check`: clean;
- sole Alembic head: `0054`.

The historical global suite/Ruff debt remains recorded and is NOT considered fixed.

## Mandatory bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/deploy.py`
- `ops/production/remote_deploy.py`
- `ops/production/target.json`

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use canonical clean local `main` for the harness.

Before any production-ref move, verify:

1. release and rollback SHAs resolve exactly;
2. `origin/production == bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
3. rollback is an ancestor of release;
4. release is in `origin/main` history;
5. current `origin/main` after release changes no `backend/` or `ops/production/` files relative to the frozen release candidate except ledger/docs outside those paths;
6. rollback -> release changes no migration infrastructure covered by `deploy.py`;
7. repository Alembic graph has sole head `0054`;
8. local checkout satisfies the committed deployment bootstrap/runbook.

If any invariant fails, STOP before moving `production`.

## Production ref move

Immediately before the ref move:

- fetch `origin/production`;
- require it still equals the exact rollback SHA.

Fast-forward `refs/heads/production` from rollback to release WITHOUT FORCE.

A canonical equivalent is:

`git push origin f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6:refs/heads/production`

Do not use `--force` or `--force-with-lease`.

Then fetch `origin/production` again and require exact equality to:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

If the push/fetch verification fails, STOP. Do not deploy.

## Authorized deployment command

Only after the production ref is proven at the release SHA, run exactly the normal committed harness from canonical clean `main`:

`python3 ops/production/deploy.py --release-sha f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6 --rollback-sha bc69c6fa5c0735db9509d12dd5f77e6285e45901 --expected-alembic 0054`

Do not use direct SSH.
Do not use direct Docker Compose.
Do not edit `target.json`, `.env`, Compose files, deploy scripts, or production configuration.

Normal harness safety/automatic application rollback semantics apply exactly as committed.

## Required success evidence

A successful rollout requires the harness itself to report success and the final sanitized evidence to prove at minimum:

- `DEPLOYMENT=PASS`;
- production runtime/release HEAD is exactly `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`;
- API health PASS;
- Alembic exactly `0054`;
- DB container unchanged;
- DB volume unchanged;
- environment file unchanged;
- API recreated;
- worker recreated;
- application rollback unused/not required;
- fresh `origin/production` still equals the release SHA.

Do not print or record secrets, raw environment values, provider credentials, account identifiers, emails, tokens, host secrets, or raw provider payloads.

## Post-deploy boundary

After `DEPLOYMENT=PASS`:

- do NOT run any HG2 repair primitive;
- do NOT call Mattermost/Gmail/Yandex/Teams/Telegram;
- do NOT start sync/reconcile/backfill;
- do NOT run production data counts that were not explicitly authorized;
- do NOT build/install a client;
- do NOT start human REL1D acceptance.

This rollout only changes the backend application runtime to the exact qualified release.

The existing installed client remains unchanged. The rollback/current client SHA remains the previously installed `bc69c6fa5c0735db9509d12dd5f77e6285e45901` unless factual source evidence says otherwise; do not reinstall it.

## Failure / blocker behavior

### Before production ref move

Return HOLD with the exact sanitized blocker and STOP. No ref move, no deploy.

### After production ref move but before/deployment failure

Do not invent manual recovery.

Let the committed harness perform only its built-in authorized rollback behavior.

Record:
- whether the application runtime ended on release or rollback;
- whether the harness reported `BREAK_GLASS_REQUIRED`;
- whether health/Alembic/DB invariants are known;
- current `origin/production` SHA.

Then HOLD and STOP for fresh Architect authorization.

Do not force-move the production ref backward.
Do not use ad-hoc SSH.

## Completion protocol

### On success

Append a compact factual `REL1D-HG2D2` entry to `PROJECT_STATE.md` including:

- release SHA;
- rollback SHA;
- production ref fast-forward without force;
- exact harness command;
- `DEPLOYMENT=PASS`;
- runtime release HEAD;
- health result;
- Alembic result;
- DB container/volume/env invariants;
- API/worker recreation;
- rollback unused;
- explicit no migration/provider/model/data-repair/client/product-data action.

Replace `CURRENT_TASK.md` with HOLD stating:

- HG2 backend release is deployed;
- production/backend runtime and ref are `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`;
- Alembic remains `0054 / 0054`;
- installed client remains unchanged;
- human REL1D acceptance remains paused;
- no HG2 data repair/provider call/next phase without fresh Architect authorization.

Commit + push ledger updates to `main`.
STOP.

### On failure

Write only bounded factual evidence to `PROJECT_STATE.md` / HOLD.
Do not modify runtime source, deploy harness, provider config, DB/schema, or credentials.
STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
