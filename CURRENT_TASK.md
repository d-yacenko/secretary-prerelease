# Current task — Final public_web existence-state correction

## Architect review

Commit:

`157fbbbd7545192cd65639426becea90999e1ef7`

successfully fixes the previously identified HTTPS retry and first-rollout cleanup defect.

One final narrow correctness issue remains before the rollout helper is accepted.

No production work is authorized.

## Blocking defect

`remote_public_web.py` currently determines:

`existed_before = bool(service_id("public_web", required=False))`

and `service_id()` uses:

`docker compose ps -q public_web`

Docker Compose `ps` shows only running containers by default. A previously-created but stopped `public_web` container therefore appears absent.

That violates the required update contract:
- if `public_web` existed before the rollout, a failed update must NOT automatically remove it;
- "existed before" includes a stopped/exited Compose container, not only a running one.

## Required correction

Code/test-only, no architecture changes.

1. Add a dedicated existence check for `public_web` that includes stopped/exited containers, e.g. using the Compose equivalent of:
   - `docker compose ps --all -q public_web`
   or another deterministic all-state query.

2. Use that all-state existence result ONLY to decide `existed_before`.

3. Keep the post-start validation strict:
   - after `up`, `public_web` must have a running container id;
   - `require_running()` remains required.

4. Preserve all already-correct behavior from `157fbbbd...`:
   - bounded 45-second HTTPS readiness polling;
   - temporary connection/TLS failures retry;
   - no insecure TLS flags;
   - any failed first rollout cleans up only newly-created `public_web`;
   - a pre-existing service is not removed after failed update;
   - db/api/worker/.env remain untouched.

## Required tests

Add deterministic regression proving:
- running pre-existing public_web => existed_before true;
- stopped/exited pre-existing public_web => existed_before true;
- no public_web container in any state => false;
- stopped pre-existing public_web + failed verification => no automatic stop/rm cleanup;
- post-start running check still fails if no running public_web container exists.

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
