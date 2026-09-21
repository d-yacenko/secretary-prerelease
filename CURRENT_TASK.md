# Current task — Telegram MTProto M4AZ1: schema-neutral production deploy of shallow folder bootstrap

## Status

Shallow folder-scope bootstrap is accepted for production candidacy.

Authorized release:
`cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`

Authorized rollback:
`2db36510fe884eadc40d63fed8661ed3627f1cbb`

Expected Alembic:
`0046`

The release is schema-neutral:
- no migration files changed;
- no `0047`;
- normal deploy harness applies.

Accepted folder-scope semantics:
- fresh scope peer: one newest-first fetch, limit 20, no min/max history bounds;
- no second historical page;
- age does not impose the legacy 14-day cutoff;
- scope cutoff is transient and never persisted;
- fresh scope backfill cursor remains/ends None and history_complete=true;
- existing scope peer: incremental-only, preserve legacy cutoff/backfill/completion state;
- manual `sync_group`: existing 14-day bounded backfill unchanged;
- recurring remains `scope_active=true` only;
- Q1 AI quarantine remains unchanged.

## Authorization

The human explicitly authorized deployment.

Authorize exactly ONE normal production deploy through:

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
- `origin/production == cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`.

Read:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/deploy.py`
- `ops/production/target.json`
- any helper directly named by the deploy harness.

## Exact deploy command

```bash
RELEASE_SHA=cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa
ROLLBACK_SHA=2db36510fe884eadc40d63fed8661ed3627f1cbb
EXPECTED_ALEMBIC=0046

python3 ops/production/deploy.py \
  --release-sha "$RELEASE_SHA" \
  --rollback-sha "$ROLLBACK_SHA" \
  --expected-alembic "$EXPECTED_ALEMBIC"
```

Run exactly once.

## Required invariants

The canonical harness must prove:
- target/pinned SSH host-key PASS;
- current production checkout is rollback SHA or already release SHA;
- `origin/production` exact release SHA;
- production worktree clean;
- DB/API/worker preflight PASS;
- DB healthy;
- current API health PASS;
- DB credentials / `SECRETARY_CREDENTIAL_KEY` presence and equality checks PASS without printing values;
- schema-neutral release check PASS;
- only API + worker rebuilt/recreated;
- DB container identity unchanged;
- DB volume unchanged;
- production `.env` checksum unchanged;
- post-deploy health PASS;
- Alembic exact `0046`.

## Telegram-specific constraints

Do NOT during deployment:
- call Telegram/provider APIs;
- Sync;
- select/save folders;
- preview scope;
- Apply Scope;
- login/re-login;
- enable MTProto AI;
- alter recurring semantics;
- alter Bot API.

The future human folder acceptance is NOT part of this deploy task.

## Failure handling

If the deploy harness blocks before mutation:
- do not bypass;
- do not use direct SSH;
- report sanitized blocker and STOP.

If mutation occurs and the harness fails:
- allow only its automatic rollback to exact rollback SHA;
- report rollback result;
- do not manually repair.

## Required report

Return:
- release SHA;
- rollback SHA;
- production ref;
- previous runtime;
- resulting runtime;
- target/pin result;
- DB/API/worker preflight;
- API/worker recreation;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- health;
- Alembic;
- rollback attempted yes/no and result;
- migration none;
- Telegram/provider actions=0;
- confirmation only canonical deploy harness was used.

Final marker on success:

`TELEGRAM_MTPROTO_M4AZ1_DEPLOY_SUCCESS`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
