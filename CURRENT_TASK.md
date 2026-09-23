# Current task — Correct public_web rollout retry/cleanup semantics

## Architect review

Commit:

`54050ea52efb5234428dfa1fd047cbaa2766680c`

is NOT YET DEPLOY-READY.

The static branding pages, Caddy configuration, Compose `public_web` service, documentation, and schema-neutral scope are accepted.

One blocking defect remains in the production rollout helper.

No production work is authorized.

## Blocking defect

In `ops/production/remote_public_web.py`:

- `collect_statuses()` intends to retry public HTTPS verification for up to 45 seconds;
- however each iteration builds the status dict by calling `http_status()`;
- `http_status()` uses `run(curl ...)`, which raises `PublicWebError` on initial connection/TLS/certificate-provisioning failure;
- that exception escapes `collect_statuses()` immediately, so the intended retry window is bypassed;
- in `main()`, `statuses = collect_statuses()` occurs before the existing cleanup `try/except`, so a first-rollout verification exception can also bypass removal of a newly-created `public_web` container.

This violates the required first-rollout contract:
- bounded wait for HTTPS readiness;
- on failed first rollout, stop/remove only the newly-created `public_web` service.

## Required correction

Code/test-only.

1. Make HTTPS readiness polling tolerant of temporary connection/TLS/HTTP transport failures during the bounded startup window.
   - A temporary curl/network/TLS failure must be treated as "not ready yet", not as immediate terminal rollout failure.
   - Retry remains bounded; do not hide failure indefinitely.
   - Do not use `-k` / insecure TLS bypass.

2. Ensure EVERY failure after the first-rollout `public_web` start attempt enters first-rollout cleanup when:
   - `public_web` did not exist before;
   - the rollout did not reach successful verification.

   This must include at minimum:
   - temporary verification failures that persist through deadline;
   - unexpected verification exceptions;
   - identity invariant failure after service start;
   - `public_web` missing/not-running after start.

3. Cleanup must remain narrow:
   - stop/remove only `public_web`;
   - never touch db/api/worker;
   - never change `.env`;
   - do not remove Caddy persistent volumes unless separately justified/authorized;
   - do not alter Git refs.

4. If `public_web` existed before the rollout, do NOT automatically remove it on a failed update. Report the blocker and preserve the pre-existing service for separate recovery planning.

5. Keep successful evidence unchanged:
   - PUBLIC_WEB_HEALTH=PASS
   - DB_CONTAINER_UNCHANGED=true
   - DB_VOLUME_UNCHANGED=true
   - ENV_FILE_UNCHANGED=true
   - API_CONTAINER_UNCHANGED=true
   - WORKER_CONTAINER_UNCHANGED=true
   - PUBLIC_WEB_RUNNING=true
   - PUBLIC_HOME=200
   - PUBLIC_PRIVACY=200
   - PUBLIC_TERMS=200
   - PUBLIC_UNRELATED=404
   - PUBLIC_WEB=PASS

## Required tests

Add focused deterministic tests proving:

- first HTTPS probe throws connection/TLS-style `PublicWebError`, later probe succeeds -> polling succeeds and does not abort early;
- persistent probe failure reaches bounded failure;
- first rollout + persistent verification failure -> cleanup required/executed for `public_web`;
- first rollout + post-start identity invariant failure -> cleanup required/executed;
- first rollout + public_web not-running/missing -> cleanup required/executed;
- pre-existing `public_web` + failed verification -> no automatic remove;
- cleanup command cannot target db/api/worker;
- no insecure curl flag is introduced.

Run focused tests, py_compile, Ruff check/format, compose config validation as relevant, and git diff --check.

Update PROJECT_STATE.md factually, commit + push, report exact SHA, STOP.

## Production boundary

No production SSH.
No public_web start.
No deploy.
No production ref movement.
No DNS/firewall mutation.
No Google Cloud mutation.
No OAuth reauthorization.
