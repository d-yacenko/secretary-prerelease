# Current task — Production Migration Rollout M2 BLOCKED: Telegram credential prerequisite

## Status

- Telegram A4.1–A4.4: ACCEPTED.
- Telegram Integration Gate I1: ACCEPTED.
- Production Line Reconciliation R1: ACCEPTED.
- Production Migration Rollout M1: ACCEPTED at exact SHA `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`.
- M1 is integrated into `main`.
- M2 production readiness inspection executed read-only and is **BLOCKED**.
- Production branch/runtime remains exact `5cce4b57b14e0052a038acae1354a2821a2bb77b`.
- Production DB Alembic remains exact `0041`.
- Candidate release code remains `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`.
- **No production deploy, ref move, service restart/recreate, Alembic write, DB write, env mutation, or credential mutation is currently authorized.**

## M2 readiness result

The following required checks passed:

- local main/origin-main alignment;
- clean local worktree;
- production runtime checkout exact rollback SHA;
- `origin/production` exact rollback SHA;
- SSH fingerprint verification;
- production health;
- DB TCP authentication;
- direct DB Alembic exact `0041`;
- rollback Compose DB/key environment invariant;
- candidate release Compose resolution;
- release api/worker credential-field matching check;
- release DB/key equality with rollback configuration;
- no-mutation invariant;
- temporary candidate worktree cleanup.

The blocking required check failed:

- `RELEASE_TELEGRAM_CREDENTIALS=FAIL`.

No credential values or hashes were emitted.

## Blocker

The accepted candidate release Compose requires usable Telegram MTProto application credentials for both api and worker:

- `TELEGRAM_API_ID`: numeric and > 0;
- `TELEGRAM_API_HASH`: nonblank.

The existing production `/opt/secretary/.env` does not currently resolve to usable values for the candidate release.

This is a hard fail-closed prerequisite. The release must not be deployed until valid Telegram API credentials are provisioned and M2 readiness is repeated successfully.

## Current authorization

STOP.

Do not:

- move `main` or `production` for rollout purposes;
- SSH to production for mutation;
- modify `/opt/secretary/.env`;
- create or rotate credentials;
- stop/restart/recreate any service;
- run production Compose mutation commands;
- run Alembic upgrade/downgrade;
- change DB rows/schema;
- execute `migrate_deploy.py`;
- attempt M3.

## Next prerequisite

A human/operator must have valid Telegram MTProto application credentials available through a secure channel.

Do **not** commit them, paste them into repository files, issue trackers, logs, chat transcripts, or command history.

Once the operator confirms that valid credentials are available, Architect will authorize a separate narrowly scoped credential-provisioning phase that will:

1. update only `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in production `/opt/secretary/.env` using a non-echoing/non-logging path;
2. preserve all other environment entries exactly, especially `SECRETARY_CREDENTIAL_KEY` and PostgreSQL settings;
3. preserve file ownership/mode;
4. perform no service restart/recreate and no DB/schema/ref mutation;
5. verify only presence/validity through candidate release Compose without printing values;
6. rerun the complete M2 readiness no-mutation gate.

Only after that readiness returns READY may Architect authorize M3 actual migration cutover.

`CURRENT_TASK.md` remains the source of active authorization.
