# Current task — Replace standalone public_web rollout with nginx-root static publishing

## Accepted architecture

- Production application runtime remains exact `3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`, Alembic `0046`.
- Host nginx is the existing front door for `web-itx.duckdns.org`.
- Public static root is exactly `/var/www/web-itx`.
- Public HTTP/HTTPS `location /` uses `try_files $uri $uri/ =404;`.
- `/secretary/` remains an nginx proxy to `127.0.0.1:18080` and is outside branding rollout ownership.
- Standalone Caddy/Compose `public_web` is retired and must not be started.
- Branding target layout is:
  - `/var/www/web-itx/index.html`
  - `/var/www/web-itx/privacy/index.html`
  - `/var/www/web-itx/terms/index.html`

## Authorization

Code/test/documentation only.

Implement the replacement rollout tooling in the repository. Do NOT execute it against production in this task.

## Required implementation

1. Keep the existing repository source pages under `infra/public/` as the canonical page content.
2. Remove the production rollout dependency on the Caddy container:
   - remove the `public_web` service from production Compose;
   - remove Caddy-specific production volumes/config that are no longer used;
   - remove or retire `infra/Caddyfile` if it has no remaining repository purpose;
   - no replacement reverse proxy/container may bind 80/443.
3. Rework `ops/production/public_web_rollout.py` and its remote helper into an nginx-preserving static publisher. Preserve:
   - canonical clean local checkout requirement;
   - pinned production host key;
   - exact release SHA validation;
   - exact production path/origin/ref validation;
   - production API health preflight;
   - DB/API/worker/.env identity checks before and after the branding publication;
   - sanitized fail-closed output.
4. The remote publisher must own only these final paths:
   - `/var/www/web-itx/index.html`
   - `/var/www/web-itx/privacy/index.html`
   - `/var/www/web-itx/terms/index.html`
   It must not alter nginx config, certificates, ACME files, `/secretary/`, other root contents, Docker services, DB, API, worker, or `.env`.
5. Publication must be atomic per final file and rollback-safe:
   - stage repository-controlled bytes in a private temporary directory on the same filesystem as the target root where practical;
   - validate exact source hashes/manifest before replacing targets;
   - preserve the pre-existing `index.html` bytes and metadata sufficiently for rollback;
   - distinguish absent privacy/terms targets from pre-existing targets;
   - create only the required `privacy` and `terms` directories when needed;
   - install final regular files with expected readable ownership/mode;
   - use atomic rename/replace for final-file cutover;
   - if any post-cutover invariant or public verification fails, restore the exact pre-rollout state for all owned target paths and remove only directories created by this rollout when empty;
   - never delete or overwrite unrelated files.
6. Do not edit/reload/restart nginx. Existing nginx must pick up static files without reload.
7. Public verification after cutover must require:
   - `https://web-itx.duckdns.org/` = 200;
   - `https://web-itx.duckdns.org/privacy` = 200;
   - `https://web-itx.duckdns.org/privacy/` = 200;
   - `https://web-itx.duckdns.org/terms` = 200;
   - `https://web-itx.duckdns.org/terms/` = 200;
   - an unrelated branding path = 404.
   Do not require `/secretary/` to return 200; its application route semantics are separate.
8. Verification should prove returned branding content corresponds to the authorized repository pages, not merely status 200. Use a non-secret deterministic content hash or marker comparison without printing page bodies.
9. Add focused tests for:
   - initial rollout where only index exists;
   - successful creation of privacy/terms directories and files;
   - replacement of an existing index;
   - preservation/restoration of pre-existing target files on failure;
   - cleanup of rollout-created empty directories only;
   - refusal to touch unrelated files;
   - identity drift rejection;
   - HTTP verification failure rollback;
   - source/manifest hash mismatch fail-closed;
   - no nginx reload/restart/edit commands;
   - no Docker/Compose mutation;
   - slash and non-slash privacy/terms verification.
10. Update docs/tests/state as needed, but do not claim production deployment.

## Acceptance checks

Run the relevant focused test suite, `py_compile`, Ruff check and format check, and `git diff --check`.

If Compose files change, also run `docker compose config --quiet` with the same repository test convention used previously.

## Not authorized

- production SSH execution of the new publisher;
- any production file write;
- nginx edit/test/reload/restart;
- Docker/Compose production action;
- production ref movement;
- application deploy/rollback;
- Google Cloud/OAuth changes;
- DNS/firewall changes;
- DB writes;
- Telegram work.

Record the implementation result and exact commit SHA in `PROJECT_STATE.md`, return `CURRENT_TASK.md` to HOLD, push, and STOP.
