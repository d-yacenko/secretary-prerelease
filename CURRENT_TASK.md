# Current task — Telegram MTProto M4AJ: deploy accepted M4AI candidate

## Status

M4AI2 candidate is ARCHITECT ACCEPTED for production deployment.

Exact candidate SHA:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Current production runtime/ref:
`8091736337689b68b4510126e74d9e409397f696`

Rollback SHA:
`8091736337689b68b4510126e74d9e409397f696`

Candidate review:
- origin/main == exact candidate SHA;
- compared against production, runtime functional changes are limited to:
  - `backend/app/api/telegram_mtproto.py`
  - `backend/app/connectors/telegram/mtproto_transport.py`
- other candidate differences are tests/docs/recovery context only;
- no client/infra/schema/dependency changes;
- Alembic remains `0046`;
- no migration `0047`;
- M4AI focused: 10 passed;
- A1-A4.4 Telegram suite: 137 passed;
- Ruff PASS;
- git diff --check PASS.

## Goal

Deploy exact candidate `23fa07df213d5a70a6dc1d3c8b32af39228107eb` to production with no unrelated changes.

Do NOT run Telegram manual Sync during deployment. Controlled Sync is a separate post-deploy human step after verification.

## Preflight

Before mutation, verify read-only:

- canonical target from `ops/production/target.json`;
- strict pinned host key matches configured ED25519 fingerprint;
- production repo HEAD/ref is exactly `8091736337689b68b4510126e74d9e409397f696`;
- production worktree clean;
- API/worker/DB running;
- DB healthy;
- Alembic exact `0046`;
- `.env` unchanged;
- DB container/volume present;
- current MTProto flags remain:
  - `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- Bot API configuration untouched.

If any preflight guard fails:
STOP. Do not deploy.

## Deployment authorization

Authorized production changes:

1. move production application/ref from:
   `8091736337689b68b4510126e74d9e409397f696`
   to:
   `23fa07df213d5a70a6dc1d3c8b32af39228107eb`;

2. rebuild/recreate only services required by the normal production deploy workflow for application code:
   - API;
   - worker if normal deploy workflow requires it;

3. preserve:
   - DB container;
   - DB volume;
   - DB data;
   - `.env`;
   - credential encryption key;
   - Telegram stored session;
   - Telegram selections/scope;
   - Bot API state;
   - AI flag;
   - SSH trust data.

No migration is needed beyond confirming Alembic stays `0046`.

## Strictly forbidden

Do NOT:

- run migration 0047;
- create any schema migration;
- recreate/delete DB container or volume;
- alter `.env`;
- alter credential key;
- login/re-login Telegram;
- submit Telegram code/password;
- run Telegram history import/manual Sync;
- Apply Scope;
- change selected groups/folders;
- enable MTProto AI;
- retire/change Bot API;
- change target.json;
- change SSH trust/pin;
- deploy any SHA other than exact candidate;
- include diagnostic review-branch harnesses not present in candidate;
- perform unrelated cleanup.

## Post-deploy verification

Verify:

- production repo HEAD/ref == exact candidate SHA;
- runtime application identity == exact candidate SHA;
- production worktree clean;
- API running;
- worker running;
- DB running and healthy;
- DB container/volume unchanged;
- Alembic still `0046`;
- health endpoint PASS;
- `.env` unchanged;
- credential key unchanged;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- Bot API untouched.

Read-only MTProto checks allowed after deploy:
- status endpoint;
- folders/groups discovery through existing session if needed for health verification;
- no history Sync.

## Rollback

If deployment or post-deploy verification fails:

Rollback application/ref to:
`8091736337689b68b4510126e74d9e409397f696`

Use normal deploy rollback workflow.

Do not rollback DB because no schema change is authorized.

After rollback verify:
- runtime/ref exact rollback SHA;
- API/worker/DB healthy;
- Alembic `0046`;
- DB container/volume unchanged.

## Required report

Return:

### Preflight
- target/pin PASS;
- old production SHA;
- worktree clean;
- services/DB health;
- Alembic;
- env/DB preservation guards.

### Deployment
- exact deployed SHA;
- services recreated;
- DB untouched;
- migration action: none;
- Telegram login/history actions: none.

### Post-deploy
- production ref/runtime exact match;
- health;
- API/worker/DB status;
- Alembic;
- env/key/DB preservation;
- AI flag;
- Bot API untouched.

If rollback occurred:
- reason;
- rollback SHA;
- final runtime/health.

Final marker:
`TELEGRAM_MTPROTO_M4AJ_DEPLOY_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
