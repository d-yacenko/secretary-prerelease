# Current task — Telegram Bot API M4BQ1: schema-neutral production deploy of Stage C cleanup

## Status

Human explicitly authorized production deploy M4BP1 Stage C.

Accepted release:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Rollback / current production before deploy:
`fe151f12f64886505253e765b82458710a949e34`

Expected Alembic:
`0046`

The rollback -> release comparison is a fast-forward with no Alembic/migration changes.

## Deploy scope

Authorize exactly ONE normal schema-neutral production deploy through:

`ops/production/deploy.py`

This deploy rolls out server-side Stage C cleanup:
- legacy Bot link/webhook routes removed;
- Bot HTTP transport/webhook service/webhook CLI removed;
- active Bot Settings/Compose runtime fields removed;
- legacy Bot send execution removed;
- historical Bot-derived canonical objects remain preserved/readable;
- historical Bot mutations remain fail-closed;
- legacy Bot DB models/tables/migrations remain preserved;
- MTProto remains the sole live Telegram transport.

Production `.env` must remain unchanged. The already-empty legacy Bot lines may remain; candidate Settings ignores unknown entries and Compose no longer injects them into API/worker.

## Mandatory bootstrap

Follow `AGENTS.md`, `docs/executor_bootstrap.md`, and `docs/deploy.md`.

Verify:
- canonical origin;
- clean checkout;
- fresh `origin/main`;
- exact release and rollback SHAs resolve;
- `origin/production == bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`.

## Exact deploy command

```bash
RELEASE_SHA=bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b
ROLLBACK_SHA=fe151f12f64886505253e765b82458710a949e34
EXPECTED_ALEMBIC=0046

python3 ops/production/deploy.py \
  --release-sha "$RELEASE_SHA" \
  --rollback-sha "$ROLLBACK_SHA" \
  --expected-alembic "$EXPECTED_ALEMBIC"
```

Run exactly once.

## Required invariants

The harness must prove:
- target/pin PASS;
- current production runtime is rollback SHA or already release SHA;
- `origin/production` exact release SHA;
- production tracked worktree clean;
- DB/API/worker preflight PASS;
- DB healthy and current application health PASS;
- schema-neutral release check PASS;
- only API + worker rebuilt/recreated;
- DB container identity unchanged;
- DB volume identity unchanged;
- production `.env` checksum unchanged;
- post-deploy health PASS;
- Alembic exact `0046`.

## Hard prohibitions

Do NOT:
- edit production `.env`;
- remove the four empty legacy Bot lines;
- touch Telegram/Bot provider;
- change MTProto account/session/scope;
- delete historical Bot-derived objects;
- drop legacy Bot tables;
- add/run migration;
- enable MTProto AI;
- perform unrelated client rollout.

## Failure handling

If bootstrap/harness blocks before mutation:
- do not bypass;
- do not use direct SSH;
- do not retry;
- report sanitized blocker and STOP.

If mutation occurs and harness fails:
- allow only harness automatic rollback to exact rollback SHA;
- report rollback result;
- do not manually repair/retry.

## Required report

Return:
- release SHA;
- rollback SHA;
- `origin/production`;
- previous and resulting production runtime;
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
- confirmation canonical deploy harness only.

Final marker on success:

`TELEGRAM_BOT_M4BQ1_STAGE_C_DEPLOY_SUCCESS`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
