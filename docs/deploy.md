# Production deployment contract

This document defines HOW an explicitly authorized Secretary production deployment is executed. It does not authorize a deploy or select a release. The Architect task and repository task ledger determine WHAT is authorized.

## Canonical production identity

Production is fail-closed and is never discovered by probing hosts.

The exact SSH destination and expected SSH host-key fingerprint live in:

`ops/production/target.json`

That file is intentionally non-secret. Publishing the production IP/hostname and host-key fingerprint is acceptable for this repository; credentials and private keys must never be stored there.

Until both `ssh_target` and `host_key_sha256` are populated with verified production values, all automated deployments must stop before SSH.

The canonical runtime identity is:

- Repository path: `/opt/secretary`
- Git origin: `https://github.com/d-yacenko/secretary-prerelease.git`
- Environment file: `/opt/secretary/.env`
- Compose files: `infra/compose.yaml` and `infra/compose.deploy.yaml`
- Health URL: `http://127.0.0.1:18080/health`
- Application services: `api`, `worker`
- Database service: `db`

No Executor may try alternative hosts, IP addresses, directories, `.env` files, Compose files, or repositories when a production preflight fails.

## Mandatory deployment entrypoint

Normal production deployment must use:

`ops/production/deploy.py`

Direct ad-hoc SSH and direct production Compose commands are forbidden unless the Architect explicitly authorizes a BREAK-GLASS operation.

The deployment task must supply three literal values:

- authorized release SHA;
- authorized rollback SHA;
- expected four-digit Alembic revision.

The entrypoint syntax is:

```bash
python3 ops/production/deploy.py \
  --release-sha "$RELEASE_SHA" \
  --rollback-sha "$ROLLBACK_SHA" \
  --expected-alembic "$EXPECTED_ALEMBIC"
```

The Architect task must assign those shell variables to exact authorized values before execution. Empty or malformed values fail closed.

## Schema-neutral release limitation

`ops/production/deploy.py` is only for schema-neutral, application-only releases. Before any SSH connection, it verifies that both supplied commits resolve locally and that the Alembic migration infrastructure is unchanged between the rollback and release commits.

A release that changes migration files, Alembic environment configuration, or the migration template requires a separate Architect-authorized migration deployment plan with explicit forward and rollback semantics. It must not be bypassed with an automatic migration override flag in the normal deployment harness.

## What the deployment harness enforces

The local entrypoint:

1. reads only the committed production target;
2. performs no host discovery;
3. obtains the target SSH host key with `ssh-keyscan`;
4. requires an exact SHA256 fingerprint match with `target.json`;
5. creates an ephemeral known-hosts file containing only the matching key;
6. connects with strict host-key checking and no fallback to global known-hosts state;
7. streams the committed remote deployment helper over SSH without copying secrets.

The remote helper then requires all of the following before any recreate:

- current directory resolves to `/opt/secretary`;
- Git origin is exactly the canonical prerelease repository;
- tracked working tree is clean;
- `origin/production` equals the explicitly authorized release SHA;
- current checkout is the authorized rollback SHA or already the release SHA;
- `/opt/secretary/.env` exists;
- existing `db`, `api`, and `worker` containers exist;
- existing DB container is running/healthy;
- current API health succeeds;
- explicit Compose resolution is performed with `/opt/secretary/.env`;
- `POSTGRES_PASSWORD` and `SECRETARY_CREDENTIAL_KEY` are non-empty for both `api` and `worker`;
- `api` and `worker` resolve the same DB credentials and credential-encryption key;
- a read-only PostgreSQL TCP `SELECT 1` succeeds using the exact DB credentials resolved for the proposed application containers.

Compose configuration containing secrets is held only in process memory and is never printed or persisted.

## Canonical Compose invocation

Every production Compose operation in the harness uses this exact prefix:

```bash
docker compose \
  --env-file /opt/secretary/.env \
  -f infra/compose.yaml \
  -f infra/compose.deploy.yaml
```

There is no implicit environment resolution in production.

## Application rollout

For a normal application-only release the harness:

1. records DB container identity, DB volume identity, `.env` checksum, and current `api`/`worker` container identities internally;
2. switches the production checkout to the exact authorized release SHA;
3. builds only `api` and `worker`;
4. recreates only `api` and `worker` with `--no-deps --force-recreate`;
5. never includes `db` in an `up` command;
6. verifies DB container identity is unchanged;
7. verifies DB volume identity is unchanged;
8. verifies `.env` is unchanged;
9. verifies both application container identities changed;
10. verifies health;
11. verifies the exact authorized Alembic head.

A normal application rollout must never recreate the database, change the DB volume, rotate PostgreSQL credentials, generate a new `SECRETARY_CREDENTIAL_KEY`, or use all-services `up`.

## Rollback

If a post-recreate invariant fails, the remote helper automatically attempts rollback to the exact rollback SHA supplied by the Architect task. Rollback rebuilds and recreates only `api` and `worker` with the same explicit environment and Compose files.

Rollback must preserve:

- DB container identity;
- DB volume identity;
- `.env` checksum;
- expected Alembic revision;
- API health.

The harness never moves remote Git refs during deployment or rollback.

## Task-specific runtime verification

Provider-specific or feature-specific runtime assertions are additional to this generic deployment contract. The Architect task may authorize sanitized read-only checks after the harness returns `DEPLOYMENT=PASS`.

Those checks must not modify source schedules merely to manufacture evidence and must not print account identifiers, emails, payloads, provider credentials, or raw provider errors.

## Credential and output safety

Never print or commit:

- `POSTGRES_PASSWORD`;
- `SECRETARY_CREDENTIAL_KEY`;
- API keys;
- OAuth client secrets or tokens;
- private SSH keys;
- provider credentials;
- secret hashes or prefixes;
- account IDs or emails;
- raw provider errors containing sensitive content.

Presence-only booleans and non-secret Git/container state are allowed.

## Break-glass rule

If the committed target, fingerprint, path, origin, environment, DB authentication, or container invariants do not match reality, STOP. Do not repair or bypass the mismatch during a normal deployment.

A manual recovery path requires a new explicit Architect task marked BREAK-GLASS with its own narrowly scoped commands and verification.
