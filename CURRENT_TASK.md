# Current task — Telegram MTProto M4AQ1: deploy bound-normalization release

## Status

User explicitly authorized production deployment.

GitHub production ref promotion is complete.

Authorized release SHA:
`b7fbdc71584cfde042a998fbfefb06015175a205`

Authorized rollback/runtime-before-deploy SHA:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Expected Alembic:
`0046`

Verified GitHub refs:
- `origin/production == b7fbdc71584cfde042a998fbfefb06015175a205`
- canonical main contains the same release and later task/state documentation only as applicable.

The release is schema-neutral: no Alembic migration change is authorized.

This task authorizes ONLY the normal production deploy harness and post-deploy verification described below.

## Executor workspace

Work only from:

`~/work/secretary-executor`

Canonical origin:

`https://github.com/d-yacenko/secretary-prerelease.git`

Do not use:
- `~/work/secretary`
- `~/work/secretary-prerelease`

for Executor work.

## Preparation

1. `git fetch --prune origin`
2. `git switch main`
3. `git pull --ff-only`
4. Verify:
   - exact canonical origin;
   - clean worktree;
   - local `main == origin/main`;
   - `origin/production == b7fbdc71584cfde042a998fbfefb06015175a205`;
   - release SHA exists locally;
   - rollback SHA exists locally.
5. Read:
   - `CURRENT_TASK.md`
   - `PROJECT_STATE.md`
   - `AGENTS.md`
   - `docs/executor_bootstrap.md`
   - `docs/deploy.md`
   - `ops/production/deploy.py`
   - `ops/production/remote_deploy.py`
   - `ops/production/target.json`

If any precondition fails, STOP with one sanitized blocker.

Do not move any Git ref during this task.

## Authorized deploy command

Run exactly:

```bash
RELEASE_SHA=b7fbdc71584cfde042a998fbfefb06015175a205
ROLLBACK_SHA=23fa07df213d5a70a6dc1d3c8b32af39228107eb
EXPECTED_ALEMBIC=0046

python3 ops/production/deploy.py \
  --release-sha "$RELEASE_SHA" \
  --rollback-sha "$ROLLBACK_SHA" \
  --expected-alembic "$EXPECTED_ALEMBIC"
```

Use the committed deploy harness unchanged.

Do NOT edit `deploy.py` or `remote_deploy.py`.

Do NOT bypass the harness with manual SSH or manual Compose.

## Authorized runtime mutation

Only the existing harness may:

- switch production checkout from rollback SHA to release SHA;
- build `api` and `worker`;
- recreate only `api` and `worker`.

Must preserve:
- DB container;
- DB volume/data;
- `.env`;
- credential-encryption key;
- stored Telegram MTProto session;
- Telegram selection state;
- AI flag;
- Bot API state;
- Alembic `0046`.

No migration is authorized.

## Required post-deploy verification

After `DEPLOYMENT=PASS`, report only sanitized facts already exposed by the harness and safe read-only checks allowed by the runbook.

Require final:
- production HEAD == `b7fbdc71584cfde042a998fbfefb06015175a205`;
- `origin/production` == same;
- production worktree clean;
- API running/healthy;
- worker running;
- DB running/healthy;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- Alembic == `0046`;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- Bot API untouched;
- Telegram login/history/provider actions during deploy = none.

Do not perform the human Sync in this task.

## Rollback

If the harness fails after mutation, allow only its built-in rollback to:

`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

If rollback occurs:
- STOP;
- report sanitized failure;
- report rollback PASS/FAIL;
- report final runtime SHA and health;
- do not move `origin/production` back in this task.

A GitHub ref change after rollback would require a separate authorization.

## Strictly forbidden

Do NOT:
- run migration 0047;
- change schema;
- recreate/delete DB container or volume;
- edit `.env`;
- rotate/change credential key;
- login/re-login Telegram;
- submit Telegram code/password;
- run Telegram Sync/history import;
- Apply Scope;
- discover groups/folders/dialogs;
- enable MTProto AI;
- change/retire Bot API;
- change target.json or SSH trust;
- manually SSH around the deploy harness;
- perform unrelated cleanup.

## Required report

### Preflight
- canonical repo/main clean/exact;
- origin/production exact release;
- target/pin PASS;
- SSH PASS;
- production old HEAD;
- production worktree clean;
- API/worker/DB pre-state;
- DB health;
- API health;
- Alembic.

### Rollout
- release HEAD selected;
- API recreated;
- worker recreated;
- DB container unchanged;
- DB volume unchanged;
- env file unchanged;
- migration action: none.

### Final
- production runtime SHA;
- origin/production SHA;
- health;
- API/worker/DB status;
- Alembic;
- DB/env/key preservation;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- Bot API untouched;
- Telegram login/history/provider actions: none.

Final marker:

`TELEGRAM_MTPROTO_M4AQ1_DEPLOY_READY`

Then STOP.

After successful deploy, the next phase will be a separate human-controlled single manual Sync of the already-selected Telegram group.

`CURRENT_TASK.md` is the source of active authorization.
