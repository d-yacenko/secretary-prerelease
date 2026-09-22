# Current task — Telegram Bot API M4BI1: schema-neutral production deploy of Stage A backend isolation

## Status

Human explicitly authorized production deploy M4BH1.

Accepted release:
`fe151f12f64886505253e765b82458710a949e34`

Rollback / current production before deploy:
`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

Expected Alembic:
`0046`

The rollback -> release comparison is a fast-forward and contains no Alembic/migration changes.

## Deploy scope

This task authorizes exactly ONE normal schema-neutral production deploy through:

`ops/production/deploy.py`

The deploy harness updates server runtime only (API + worker). It does not roll out the Flutter client.

Therefore this deploy is accepted as the Stage A BACKEND isolation rollout:
- legacy `POST /telegram/link` becomes HTTP 410;
- legacy Bot webhook becomes HTTP 410 with zero dispatch;
- legacy Bot-derived send/reply fails closed before Bot transport;
- MTProto server behavior remains live;
- historical Bot-derived objects/tables remain preserved;
- Bot credentials/config remain present for now;
- Telegram webhook at Telegram remains configured for now but will receive HTTP 410 from Secretary after this deploy.

Flutter client retirement UI from the same code candidate is NOT considered production-rolled-out by this server deploy. Client rollout/verification is a separate follow-up before Stage B credential/webhook removal.

## Authorization

Authorize exactly one normal schema-neutral deploy through the canonical harness.

The production Git ref must be exact:
`fe151f12f64886505253e765b82458710a949e34`

before the harness is run.

## Mandatory bootstrap

Follow `AGENTS.md`, `docs/executor_bootstrap.md`, and `docs/deploy.md`.

Use only canonical repository:
`https://github.com/d-yacenko/secretary-prerelease.git`

Verify:
- canonical origin;
- clean checkout;
- fresh `origin/main`;
- release and rollback SHAs resolve exactly;
- `origin/production == fe151f12f64886505253e765b82458710a949e34`.

## Exact deploy command

```bash
RELEASE_SHA=fe151f12f64886505253e765b82458710a949e34
ROLLBACK_SHA=c69d2353c19c4958e1fb60aac69466fcf6ac1482
EXPECTED_ALEMBIC=0046

python3 ops/production/deploy.py \
  --release-sha "$RELEASE_SHA" \
  --rollback-sha "$ROLLBACK_SHA" \
  --expected-alembic "$EXPECTED_ALEMBIC"
```

Run the harness exactly once.

## Required invariants

The harness must prove:
- committed target / pinned SSH host key PASS;
- current production checkout is rollback SHA or already release SHA;
- `origin/production` exact release SHA;
- production tracked worktree clean;
- DB/API/worker preflight PASS;
- DB healthy and current API health PASS;
- credentials/key presence checks PASS without printing secrets;
- schema-neutral release check PASS;
- only API + worker rebuilt/recreated;
- DB container identity unchanged;
- DB volume identity unchanged;
- production `.env` checksum unchanged;
- post-deploy health PASS;
- Alembic exact `0046`.

## Telegram retirement boundary

DEPLOY ONLY.

Do NOT:
- delete/change Telegram webhook at Telegram;
- call Bot API/provider;
- remove Bot token/username/webhook secret/webhook URL from production env;
- change MTProto folder/scope/login;
- press Sync or Apply Scope;
- enable MTProto AI;
- perform client rollout;
- perform Stage B cleanup.

## Failure handling

If bootstrap/harness blocks before mutation:
- do not bypass;
- do not use direct SSH;
- do not retry;
- report sanitized blocker and STOP.

If mutation occurs and the harness fails:
- allow only harness automatic rollback to exact rollback SHA;
- report rollback result;
- do not manually repair/retry.

## Required report

Return:
- release SHA;
- rollback SHA;
- `origin/production`;
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
- rollback attempted yes/no;
- migration: none;
- confirmation canonical deploy harness only;
- confirmation no Bot API/provider/webhook/env/client action occurred.

Final marker on success:

`TELEGRAM_BOT_M4BI1_BACKEND_DEPLOY_SUCCESS`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
