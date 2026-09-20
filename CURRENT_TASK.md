# Current task — Telegram MTProto M4AJR2: deploy already-promoted exact candidate

## Status

The GitHub production ref promotion is already complete.

Current verified GitHub refs:
- `origin/production = 23fa07df213d5a70a6dc1d3c8b32af39228107eb`
- current `main` is ahead with documentation/recovery commits.

Accepted production release:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Rollback/runtime-before-deploy SHA:
`8091736337689b68b4510126e74d9e409397f696`

Expected Alembic:
`0046`

Important distinction:
- GitHub `production` branch has already been promoted to the accepted release;
- production runtime/container state has NOT yet been confirmed deployed to that release;
- last verified production runtime remains rollback SHA `8091736337689b68b4510126e74d9e409397f696`.

This task authorizes ONLY Phase 2: run the normal deploy harness unchanged.

No production-ref promotion/update is needed or authorized during this task.

## Preparation

1. `git fetch origin`.
2. Read:
   - `origin/main:CURRENT_TASK.md`
   - `origin/main:PROJECT_STATE.md`
   - `origin/main:AGENTS.md`
   - `docs/deploy.md`
   - production files named by that runbook.
3. Use canonical clean local `main`.
4. Require local `main == origin/main`.
5. Verify:
   - `origin/production == 23fa07df213d5a70a6dc1d3c8b32af39228107eb`;
   - release SHA exists locally;
   - rollback SHA exists locally.
6. Do NOT move any GitHub ref in this task.

If `origin/production` is not exact release SHA, STOP.

## Authorized deploy command

Run exactly the existing normal deployment harness, unchanged:

`python3 ops/production/deploy.py --release-sha 23fa07df213d5a70a6dc1d3c8b32af39228107eb --rollback-sha 8091736337689b68b4510126e74d9e409397f696 --expected-alembic 0046`

Do not edit `deploy.py` or `remote_deploy.py`.

Do not bypass the harness with manual SSH.

## Harness preflight expectations

The harness must fail closed unless all required conditions pass, including:

- canonical local checkout;
- clean local main;
- local main == origin/main;
- canonical target.json;
- pinned production SSH host key;
- schema-neutral release;
- production repo clean;
- production origin correct;
- `origin/production == release SHA`;
- current production HEAD is either rollback SHA or release SHA;
- db/api/worker present;
- DB healthy;
- API/worker running;
- health endpoint PASS;
- DB volume captured;
- .env hash captured;
- API/worker required environment consistent;
- DB TCP auth PASS;
- Alembic 0046.

If harness blocks before runtime mutation:
STOP and report exact sanitized reason.

## Authorized runtime mutation

Only the existing harness may:

- switch production checkout to exact release SHA;
- build api + worker;
- recreate api + worker.

Must preserve:

- DB container;
- DB volume/data;
- .env;
- credential encryption key;
- stored Telegram session;
- Telegram selections/scope;
- AI flag;
- Bot API state;
- SSH trust data.

No migration is authorized; Alembic must remain 0046.

## Strictly forbidden

Do NOT:

- move `origin/production`, `main`, tags, or any other ref;
- manually SSH around deploy.py;
- manually git-switch production outside harness;
- deploy any other SHA;
- run migration 0047;
- change schema;
- recreate/delete DB container or volume;
- edit .env;
- change credential key;
- login/re-login Telegram;
- submit Telegram code/password;
- run Telegram manual Sync/history import;
- Apply Scope;
- change groups/folders;
- enable MTProto AI;
- change/retire Bot API;
- change target.json or SSH trust;
- perform unrelated cleanup.

## Rollback

If rollout fails after service recreation, use the harness's built-in rollback to:

`8091736337689b68b4510126e74d9e409397f696`

If runtime rollback succeeds:
- STOP;
- report final runtime SHA and health;
- do NOT change GitHub `origin/production` during this task. Ref restoration, if required, needs separate authorization because this task explicitly forbids ref movement.

## Required report

### Preflight / transport
- origin/production exact release: true/false;
- target/pin;
- SSH;
- production old HEAD;
- production worktree clean;
- API/worker/DB pre-state;
- DB health;
- health endpoint;
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
- production runtime/ref SHA;
- origin/production SHA;
- health;
- API/worker/DB status;
- Alembic;
- DB/env/key preservation;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- Bot API untouched;
- Telegram login/history actions: none.

If rollback:
- sanitized failure reason;
- rollback PASS/FAIL;
- final runtime SHA;
- final health.

Final marker:
`TELEGRAM_MTPROTO_M4AJR2_DEPLOY_READY`

Then STOP.

After successful deploy, the NEXT phase will be a separate human-controlled manual Sync of the already-selected Telegram group. Do not perform it during this task.

`CURRENT_TASK.md` is the source of active authorization.
