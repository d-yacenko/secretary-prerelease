# Current task — Telegram MTProto M4BC1: schema-neutral production deploy of M4BB1

## Status

M4BB3 wide read-only scope preview is complete and PASS.

Human explicitly authorized production deployment of M4BB1.

Current production runtime/ref before this deployment:
`cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`

Authorized release:
`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

Authorized rollback:
`cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`

Expected Alembic:
`0046`

The release is schema-neutral. The exact rollback -> release comparison is a fast-forward and contains no Alembic/migration file changes.

## Accepted M4BB1 semantics

- folder-derived scope dialog-universe scan uses a 2000-dialog retained bound with one-item lookahead;
- exactly 2000 dialogs can be proven complete when no 2001st dialog is observed;
- 2001+ dialogs remain fail-closed as truncated;
- folder discovery and manual-group discovery remain on their existing 500-dialog bound;
- truncated scope reconciliation remains fail-closed;
- shallow folder-scope bootstrap behavior from production `cbd5e7d...` remains unchanged;
- manual group history behavior remains unchanged;
- `TELEGRAM_MTPROTO_AI_ENABLED=false` quarantine remains unchanged;
- no schema change / no `0047`;
- Bot API remains untouched.

M4BB3 already proved the current production account has a complete dialog universe of 649 dialogs and the configured folder derives exactly 28 eligible peers with `TRUNCATED=false`.

## Authorization

Authorize exactly ONE normal schema-neutral production deploy through:

`ops/production/deploy.py`

Do NOT use direct SSH or direct Compose.

The production Git ref must be exact authorized release `c69d2353c19c4958e1fb60aac69466fcf6ac1482` before the deploy harness is run.

## Mandatory bootstrap

Follow `AGENTS.md` and `docs/executor_bootstrap.md`.

Use only the canonical repository:

`https://github.com/d-yacenko/secretary-prerelease.git`

Verify:
- canonical origin;
- clean canonical checkout;
- current `origin/main`;
- authorized release and rollback SHAs resolve exactly;
- `origin/production == c69d2353c19c4958e1fb60aac69466fcf6ac1482`.

Read before execution:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/deploy.py`
- `ops/production/target.json`
- helpers directly named by the deploy harness.

## Exact deploy command

```bash
RELEASE_SHA=c69d2353c19c4958e1fb60aac69466fcf6ac1482
ROLLBACK_SHA=cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa
EXPECTED_ALEMBIC=0046

python3 ops/production/deploy.py \
  --release-sha "$RELEASE_SHA" \
  --rollback-sha "$ROLLBACK_SHA" \
  --expected-alembic "$EXPECTED_ALEMBIC"
```

Run the deploy harness exactly once.

## Required deployment invariants

The canonical harness must prove:
- committed target / pinned SSH host-key PASS;
- current production checkout is rollback SHA or already release SHA;
- `origin/production` exact release SHA;
- production tracked worktree clean;
- DB/API/worker preflight PASS;
- DB healthy and current API health PASS;
- DB credentials and `SECRETARY_CREDENTIAL_KEY` presence/equality checks PASS without printing values;
- schema-neutral release check PASS;
- only API + worker rebuilt/recreated;
- DB container identity unchanged;
- DB volume identity unchanged;
- production `.env` checksum unchanged;
- post-deploy health PASS;
- Alembic exact `0046`.

## Telegram-specific boundary

This task is DEPLOY ONLY.

Do NOT intentionally:
- click or call Apply Scope;
- click or call Sync;
- run a Telegram/provider probe;
- change folder configuration;
- login/re-login Telegram;
- enable MTProto AI;
- alter recurring semantics;
- alter Bot API;
- perform post-deploy Inbox/scope/bootstrap acceptance.

The worker may naturally execute already-existing recurring jobs after restart. Do not suppress, accelerate, manufacture, or manually trigger that behavior in this deploy task. Acceptance of resulting scope/bootstrap behavior is a separate Architect task after the deploy report is reviewed.

## Failure handling

If bootstrap or deploy harness blocks before mutation:
- do not bypass;
- do not use direct SSH;
- report one sanitized blocker and STOP.

If mutation occurs and the harness fails:
- allow only the harness's automatic rollback to exact rollback SHA;
- report rollback result;
- do not manually repair or retry.

Do not run the deploy harness a second time without new Architect authorization.

## Required report

Return:
- release SHA;
- rollback SHA;
- `origin/production` ref;
- previous production runtime;
- resulting production runtime;
- target/pin result;
- schema-neutral check;
- DB/API/worker preflight;
- API/worker recreation;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- health;
- Alembic;
- rollback attempted yes/no and result;
- migration: none;
- confirmation that only the canonical deploy harness was used;
- confirmation that no manual Telegram/provider action or acceptance probe was performed.

Final marker on success:

`TELEGRAM_MTPROTO_M4BC1_DEPLOY_SUCCESS`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
