# CURRENT_TASK

ACTIVE

## REL1D-HG-R1 — schema-neutral production backend rollout for accepted HG1.1/HG1.2

Architect source acceptance is complete.

Exact accepted release:

```
RELEASE_SHA=1879aabc97bfc5ed13fbc2ffa4d0c9c7ccbb3320
ROLLBACK_SHA=6693578d35c1ea1d6e25bf73768ca0cf6c07dac9
EXPECTED_ALEMBIC=0054
```

The accepted product implementations contained in this release are:

- REL1D-HG1.1 scroll corrective: `6f0a51b947d19eff2ccb840e7262f463a862304e`
- REL1D-HG1.2 communication-backed grounding: `f792e1834b86c5045603e85da076ee5748331e31`

The release commit `1879aabc...` adds only Architect acceptance ledger on top of those implementations.

Production currently remains exactly:

- backend/runtime: `6693578d35c1ea1d6e25bf73768ca0cf6c07dac9`
- `refs/heads/production`: same SHA
- Alembic: `0054 / 0054`
- installed Linux client: same old SHA

This task is ONLY the schema-neutral backend rollout. Do not build/install the client in this task. Do not perform human REL1D acceptance.

## Verified release delta contract

Architect verified the release is a descendant of the current production SHA.

There are no changes to:

- `backend/alembic/**`
- DB schema/models requiring migration
- dependency manifests
- production infra/deploy harness

Runtime product changes are limited to:

- `backend/app/services/person_role_import_grounding_service.py`
- `client/lib/assistant/assistant_screen.dart`
- `client/lib/assistant/role_import_preview.dart`

Other release-delta files are tests and repository ledger/bootstrap documentation.

Therefore this is a normal schema-neutral backend deployment and Alembic must remain `0054 / 0054`.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/deploy.py`

Verify:

1. fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task;
2. `origin/production == ROLLBACK_SHA`;
3. `RELEASE_SHA` resolves and is a strict descendant of `ROLLBACK_SHA`;
4. the release delta has no Alembic/schema/dependency/infra change;
5. current production health is PASS before mutation;
6. current production Alembic is `0054 / 0054`.

If any precondition differs, do not improvise; return HOLD with the sanitized blocker and STOP.

Do not read/print/rotate credentials or secrets.

## Production ref promotion

Fast-forward `refs/heads/production` from exactly `ROLLBACK_SHA` to exactly `RELEASE_SHA`.

Requirements:

- fast-forward only;
- no force push;
- no merge commit;
- no branch rewrite;
- immediately fetch and verify fresh `origin/production == RELEASE_SHA`.

If the branch cannot be advanced by exact fast-forward, do not deploy.

## Backend deployment

Use the canonical schema-neutral deployment harness:

```
python3 ops/production/deploy.py \
  --release-sha 1879aabc97bfc5ed13fbc2ffa4d0c9c7ccbb3320 \
  --rollback-sha 6693578d35c1ea1d6e25bf73768ca0cf6c07dac9 \
  --expected-alembic 0054
```

Do not run Alembic upgrade/downgrade manually.

Required success evidence:

- deployment reports PASS;
- release runtime/head is exact `RELEASE_SHA`;
- Alembic remains `0054`;
- health gate PASS;
- API and worker are recreated as expected;
- DB container unchanged;
- DB volume unchanged;
- production `.env` unchanged;
- no migration occurred;
- rollback unused.

Do not call the role-import extraction/model path as a deployment smoke test.

Do not intentionally create/update/delete Person, RoleTerm, PersonRoleAssignment, messages, or other product data.

Do not call provider/model APIs.

## Failure behavior

If the deployment harness fails:

- follow only the harness's bounded schema-neutral application rollback behavior;
- do not perform any migration rollback;
- do not manually mutate DB;
- record exact sanitized state;
- ensure health/state are known before reporting;
- return HOLD;
- STOP.

If `production` was advanced but deployment did not start due to a fail-closed precondition, record that exact state rather than inventing corrective actions.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG-R1` entry to `PROJECT_STATE.md`, including:
   - exact release/rollback SHA;
   - production-ref fast-forward result;
   - deploy command/harness result;
   - runtime release SHA;
   - Alembic;
   - health;
   - DB container/volume/`.env` preservation;
   - API/worker recreation;
   - rollback used/unused;
   - explicit no migration/model/provider/product-data mutation;
   - installed Linux client still remains `6693578d35c1ea1d6e25bf73768ca0cf6c07dac9`.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - REL1D-HG-R1 succeeded;
   - production backend/source/ref = `RELEASE_SHA`;
   - Alembic = `0054 / 0054`;
   - installed Linux client still = `ROLLBACK_SHA`;
   - next controlled stage is exact-release Linux client build/install;
   - human REL1D acceptance remains paused;
   - do not start the client stage without fresh Architect authorization.

3. commit + push ledger changes to `main`.

4. STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
