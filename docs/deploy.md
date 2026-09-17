# Production deployment runbook

This document is the execution protocol for an explicitly authorized
production deploy, rollback, recovery, or runtime-maintenance task. It does not
authorize work. `CURRENT_TASK.md` and the Architect authorization determine
what may be done.

## Fixed production paths

- Repository: `/opt/secretary`
- Environment file: `/opt/secretary/.env`
- Compose files: `infra/compose.yaml` and `infra/compose.deploy.yaml`
- API health: `http://127.0.0.1:18080/health`
- Expected health response: `{"status":"ok"}`

Run every production command from `/opt/secretary`. Do not require changing
into `infra`.

Every production Compose invocation that performs `config`, `build`, `up`, or
recreate operations must use this explicit form:

```bash
docker compose \
  --env-file /opt/secretary/.env \
  -f infra/compose.yaml \
  -f infra/compose.deploy.yaml
```

Use the same explicit form for production `ps` and `exec` commands where it
removes ambiguity about the project configuration.

## Authorization and preflight

Before acting, the Executor must confirm that the requested SHA/ref is the
exact one authorized for this operation, the checkout is clean, and the
working directory is `/opt/secretary`:

```bash
cd /opt/secretary
git status --short
git rev-parse HEAD
git branch --show-current
```

Before any application recreate, record and verify all of the following:

- current `api`, `worker`, and `db` state;
- the current DB container ID;
- the actual host-to-container API port mapping;
- health on the actual published port (currently `127.0.0.1:18080->8000`);
- the current Alembic revision;
- Compose resolution using the explicit `/opt/secretary/.env`;
- presence of `POSTGRES_PASSWORD` and `SECRETARY_CREDENTIAL_KEY`, reported
  only as booleans.

The Compose configuration must be parsed internally by a root-only temporary
helper. Do not print or persist the config JSON because it contains secrets.
The helper must inspect the resolved `api` and `worker` environment and emit
only presence/match booleans.

For example, the helper may consume the explicit Compose output below and
print only presence booleans for the required secrets:

```bash
docker compose \
  --env-file /opt/secretary/.env \
  -f infra/compose.yaml \
  -f infra/compose.deploy.yaml \
  config --format json | python3 /run/production-config-presence-check.py
```

The helper must not write the JSON to a file or pass it through a command that
prints it. It must check `POSTGRES_PASSWORD` and
`SECRETARY_CREDENTIAL_KEY` separately for both `api` and `worker`.

Before recreate, perform a read-only PostgreSQL TCP authentication probe using
the database name, user, and password that the proposed `api`/`worker`
containers would receive from the explicit Compose resolution. Compare those
resolved values with the existing DB container's credentials internally, then
run `SELECT 1` from inside the existing DB container. Never print the
credentials. If the proposed application credentials do not authenticate,
stop before recreating any container.

Never recreate containers hoping that unresolved or mismatched credentials
will work.

## Normal application rollout

Record the DB container ID before any application operation. Build only the
application services:

```bash
cd /opt/secretary
docker compose \
  --env-file /opt/secretary/.env \
  -f infra/compose.yaml \
  -f infra/compose.deploy.yaml \
  build api worker
```

Recreate only `api` and `worker`, with no dependency recreation:

```bash
docker compose \
  --env-file /opt/secretary/.env \
  -f infra/compose.yaml \
  -f infra/compose.deploy.yaml \
  up -d --no-deps --force-recreate api worker
```

Never recreate `db`, change the DB volume, rotate PostgreSQL credentials, or
use an all-services `up` for an application-only rollout. The DB container ID
must be identical before and after the rollout unless DB work was explicitly
authorized.

## Known production credential constraint

Production currently has known PostgreSQL credential drift between the normal
`.env`/Compose value and the existing persistent DB container. The baseline
was recovered with a temporary application-container override. A normal
`api`/`worker` recreate is not authorized until the persistent credential
transport correction has been accepted.

Do not document or print the credential value. Do not turn the temporary
override into the normal deployment procedure. Do not generate or replace
`SECRETARY_CREDENTIAL_KEY` during deployment or recovery.

## Post-deploy verification

After a rollout, verify the expected Git SHA and clean checkout, then verify
that `api` and `worker` are running and `db` is healthy:

```bash
cd /opt/secretary
git rev-parse HEAD
git status --short
docker compose \
  --env-file /opt/secretary/.env \
  -f infra/compose.yaml \
  -f infra/compose.deploy.yaml \
  ps api worker db
```

Verify that the DB container ID is unchanged, then check the actual published
API port:

```bash
curl -fsS http://127.0.0.1:18080/health
docker compose \
  --env-file /opt/secretary/.env \
  -f infra/compose.yaml \
  -f infra/compose.deploy.yaml \
  exec -T api alembic current
```

The expected health response and Alembic revision must be explicitly supplied
by the authorized task. Verify required runtime credential presence only with
booleans. If source-sync behavior changed, perform only the authorized
sanitized source/job validation; do not print account identifiers, emails,
credentials, or raw provider errors.

Do not declare health failure before inspecting the actual Compose port
mapping. Do not use host port `8000` as an assumption.

## Rollback and recovery

Rollback requires an explicitly authorized previous application SHA. Switch
the checkout to that SHA/ref, verify it, and use the same explicit Compose
environment and files:

```bash
cd /opt/secretary
git switch --detach <authorized-previous-sha>
docker compose \
  --env-file /opt/secretary/.env \
  -f infra/compose.yaml \
  -f infra/compose.deploy.yaml \
  build api worker
docker compose \
  --env-file /opt/secretary/.env \
  -f infra/compose.yaml \
  -f infra/compose.deploy.yaml \
  up -d --no-deps --force-recreate api worker
```

Verify health, Alembic, service state, and the unchanged DB container ID
afterward. Rollback must not move remote refs unless separately authorized.
Preserve the DB service and volumes.

## Credential and output safety

Never print or commit `POSTGRES_PASSWORD`, `SECRETARY_CREDENTIAL_KEY`, API
keys, OAuth secrets, provider credentials, hashes, prefixes, account data, or
raw provider errors. Presence-only booleans are allowed. Use root-only
temporary helpers and remove them, along with any secret-bearing temporary
files, before completion.
