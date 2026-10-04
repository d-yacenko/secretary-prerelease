# CURRENT_TASK

ACTIVE

## REL1D-HG-R5 — schema-neutral production backend rollout for HG1.5/HG1.5.1

Architect source acceptance is complete for the combined mention-backed fallback package.

Exact accepted release:

```
RELEASE_SHA=bc69c6fa5c0735db9509d12dd5f77e6285e45901
ROLLBACK_SHA=67e8f14ba7ced8408086bd1ea57c2fa9f7b049dc
EXPECTED_ALEMBIC=0054
```

Accepted implementations contained in this release:

- HG1.5 mention-backed role-import fallback:
  `8f3c748a805956eeed137d67ee1c75b81e49fb25`
- HG1.5.1 batched approve-time mention revalidation:
  `547169d5ebde1b52860eb554a6fc78c3d5be8181`

The release commit `bc69c6fa...` adds only Architect source-acceptance ledger on top of those implementations.

Current live production state before this task:

- `refs/heads/production = ROLLBACK_SHA`
- backend/runtime = `ROLLBACK_SHA`
- installed Linux client = `ROLLBACK_SHA`
- Alembic = `0054 / 0054`
- last recorded health = PASS

This task is ONLY the schema-neutral backend rollout.

Do not build/install the client in this task.
Do not perform the human REL1D acceptance flow.
Do not create a mention-backed Person as a smoke test.
Do not call a real model/provider.

## Architect-verified release delta

Architect verified `RELEASE_SHA` is a strict descendant of `ROLLBACK_SHA`.

Product/runtime changes in the release delta are limited to:

- `backend/app/assistant/approval_presentation.py`
- `backend/app/domain/role_import_mentions.py`
- `backend/app/services/person_role_import_batch_models.py`
- `backend/app/services/person_role_import_batch_service.py`
- `backend/app/services/person_role_import_grounding_service.py`
- `backend/app/services/person_role_import_mention_service.py`
- `client/lib/api/role_import_models.dart`
- `client/lib/assistant/role_import_preview.dart`

Other changes are focused tests and repository ledger/task documentation.

There are no changes to:

- `backend/alembic/**`
- DB schema/models requiring migration
- dependency manifests
- production infra/deploy harness

Therefore Alembic must remain `0054 / 0054`.

## Required bootstrap

Use only the canonical repository:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/deploy.py`

Verify before mutation:

1. fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task;
2. fresh `origin/production == ROLLBACK_SHA`;
3. `RELEASE_SHA` resolves locally;
4. `RELEASE_SHA` is a strict descendant of `ROLLBACK_SHA`;
5. release delta contains no Alembic/schema/dependency/infra change;
6. current production health is PASS;
7. current production Alembic is `0054 / 0054`.

If any precondition differs, do not improvise. Return HOLD with the exact sanitized blocker and STOP.

Do not read/print/rotate credentials or secrets.

## Production ref promotion

Fast-forward `refs/heads/production` from exactly:

`67e8f14ba7ced8408086bd1ea57c2fa9f7b049dc`

to exactly:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

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
  --release-sha bc69c6fa5c0735db9509d12dd5f77e6285e45901 \
  --rollback-sha 67e8f14ba7ced8408086bd1ea57c2fa9f7b049dc \
  --expected-alembic 0054
```

Do not run Alembic upgrade/downgrade manually.

Required success evidence:

- `DEPLOYMENT=PASS`;
- runtime/release head exact `RELEASE_SHA`;
- Alembic remains `0054`;
- health PASS;
- API/worker recreated as expected;
- DB container unchanged;
- DB volume unchanged;
- production `.env` unchanged;
- no migration occurred;
- rollback unused.

Do not use role-import extraction/grounding/approval as a deploy smoke test.

Do not intentionally create/update/delete:

- Person
- PersonIdentity
- PersonIdentityEvidence
- RoleTerm
- PersonRoleAssignment
- messages
- tasks
- labels
- notifications
- other product data

Do not call provider/model APIs.

## Failure behavior

If deployment fails:

- follow only the deployment harness's bounded schema-neutral application rollback behavior;
- do not perform migration rollback;
- do not manually mutate DB;
- record exact sanitized final state;
- ensure health/state are known before reporting;
- return HOLD;
- STOP.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG-R5` result to `PROJECT_STATE.md`, including:
   - exact release/rollback SHA;
   - production-ref fast-forward result;
   - deploy harness command/result;
   - runtime release SHA;
   - Alembic;
   - health;
   - DB container/volume/`.env` preservation;
   - API/worker recreation;
   - rollback used/unused;
   - explicit no migration/model/provider/product-data mutation;
   - installed Linux client still remains `67e8f14ba7ced8408086bd1ea57c2fa9f7b049dc`.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - REL1D-HG-R5 succeeded;
   - production backend/source/ref = `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic = `0054 / 0054`;
   - installed Linux client still = `67e8f14ba7ced8408086bd1ea57c2fa9f7b049dc`;
   - next controlled stage is exact-release Linux client build/install;
   - human REL1D acceptance remains paused;
   - do not start the client stage without fresh Architect authorization.

3. commit + push ledger updates to `main`.

4. STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
