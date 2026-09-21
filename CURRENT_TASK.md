# Current task — Telegram MTProto M4AV1: schema-neutral production deploy of manual-only visibility

## Status

M4AU1 manual-only ordinary visibility semantics are accepted.

Authorized release:
`2db36510fe884eadc40d63fed8661ed3627f1cbb`

Authorized rollback:
`b7fbdc71584cfde042a998fbfefb06015175a205`

Expected production Alembic:
`0046`

This release is schema-neutral. No migration / no `0047`.

Accepted semantics:
- `manual_selected=true OR scope_active=true` grants ordinary non-AI transport visibility for a correctly owned matching MTProto object;
- AI policy remains scope-only;
- production `TELEGRAM_MTPROTO_AI_ENABLED=false` must remain unchanged;
- recurring sync remains `scope_active=true` only;
- Bot API remains untouched.

The future shallow folder bootstrap preference (roughly 10–20 recent messages per chat) is NOT part of this deployment.

## Authorization

The human explicitly authorized deployment.

Normal production deployment is authorized exactly once through the canonical harness:

`ops/production/deploy.py`

Do NOT use direct SSH or direct Compose.

## Executor workspace

Work only from:

`~/work/secretary-executor`

Canonical origin:

`https://github.com/d-yacenko/secretary-prerelease.git`

## Required bootstrap

```bash
git fetch origin
git switch main
git pull --ff-only
git remote get-url origin
git rev-parse HEAD
git status --short
git rev-parse origin/production
```

Require:
- canonical origin;
- local main == current `origin/main`;
- clean worktree;
- `origin/production == 2db36510fe884eadc40d63fed8661ed3627f1cbb`.

Read:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/deploy.py`
- `ops/production/target.json`
- relevant helper(s) named by the deploy harness.

## Exact deploy command

Set exact literals:

```bash
RELEASE_SHA=2db36510fe884eadc40d63fed8661ed3627f1cbb
ROLLBACK_SHA=b7fbdc71584cfde042a998fbfefb06015175a205
EXPECTED_ALEMBIC=0046

python3 ops/production/deploy.py \
  --release-sha "$RELEASE_SHA" \
  --rollback-sha "$ROLLBACK_SHA" \
  --expected-alembic "$EXPECTED_ALEMBIC"
```

Run the deploy harness exactly once.

## Required invariants

The harness must prove:
- target + pinned SSH host key PASS;
- current production checkout is rollback SHA or already release SHA;
- `origin/production` exact release SHA;
- production worktree clean;
- existing DB/API/worker present;
- DB healthy;
- pre-deploy API health PASS;
- DB credentials and `SECRETARY_CREDENTIAL_KEY` presence/invariants PASS without printing values;
- schema-neutral comparison PASS;
- only API + worker rebuilt/recreated;
- DB container identity unchanged;
- DB volume unchanged;
- `.env` checksum unchanged;
- health PASS after rollout;
- Alembic exact `0046`.

## Telegram-specific invariants

Do not during deployment:
- call Telegram/provider APIs;
- login/re-login;
- click Sync;
- Apply Scope;
- change folders/selections;
- enable MTProto AI;
- change recurring sync semantics;
- change Bot API.

After deploy, verify only sanitized runtime facts available from the harness:
- release/runtime exact `2db36510fe884eadc40d63fed8661ed3627f1cbb`;
- Alembic `0046`;
- `TELEGRAM_MTPROTO_AI_ENABLED=false` remains effective if the accepted deploy verification surface reports it;
- Bot API untouched.

Do not run a separate provider probe in this deploy task.

## Failure handling

If the canonical deploy harness blocks before mutation:
- do not bypass;
- do not use direct SSH;
- report sanitized blocker and STOP.

If it mutates and then fails:
- allow only the harness's automatic rollback to exact rollback SHA;
- report rollback result;
- do not repair manually.

## Completion report

Return:
- release SHA;
- rollback SHA;
- production ref;
- previous runtime;
- resulting runtime;
- target/pin result;
- DB/API/worker preflight;
- API/worker recreation result;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- health;
- Alembic;
- rollback attempted yes/no and result;
- migration none;
- MTProto AI flag unchanged/false if verified;
- Bot API untouched;
- Telegram/provider actions=0;
- confirmation only canonical deploy harness was used.

Final marker on success:

`TELEGRAM_MTPROTO_M4AV1_DEPLOY_SUCCESS`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
