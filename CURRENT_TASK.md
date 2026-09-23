# Current task — Correct nginx route semantics and release binding in branding publisher

## Review state

Commit `60d7a42c0f406921c7e2298c12e4e909f40ecdc9` is directionally accepted but NOT YET DEPLOY-READY.

Production remains unchanged at `3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`, Alembic `0046`.

## Authorization

Code/test/documentation only. Do NOT execute the publisher against production.

## Required corrections

1. Align public verification with the observed nginx route semantics:
   - keep target files:
     - `/var/www/web-itx/index.html`
     - `/var/www/web-itx/privacy/index.html`
     - `/var/www/web-itx/terms/index.html`
   - canonical policy/terms URLs become the trailing-slash forms:
     - `https://web-itx.duckdns.org/privacy/`
     - `https://web-itx.duckdns.org/terms/`
   - update repository page links and `docs/google_oauth.md` to those canonical trailing-slash URLs;
   - post-cutover verification must require:
     - `/` = 200 with exact authorized home-page body hash;
     - `/privacy/` = 200 with exact authorized privacy-page body hash;
     - `/terms/` = 200 with exact authorized terms-page body hash;
     - `/privacy` = 301 redirect to the exact same-host `/privacy/` URL;
     - `/terms` = 301 redirect to the exact same-host `/terms/` URL;
     - unrelated branding path = 404;
   - do not use `curl -L` to hide redirect semantics;
   - do not alter nginx to force no-slash 200 responses.

2. Bind the streamed rollout helper to the exact authorized release:
   - local clean checkout must still be canonical `main` and equal `origin/main`;
   - additionally require local `HEAD == --release-sha` before SSH;
   - the remote checkout and `origin/production` must continue to equal the same exact release SHA;
   - add a focused test proving a newer local HEAD cannot stream a helper for an older supplied release SHA.

3. Harden static-root path validation before any target snapshot/read/write:
   - require `/var/www/web-itx` to exist as a real directory and not be a symlink;
   - require its resolved path to remain exactly `/var/www/web-itx`;
   - validate pre-existing `privacy` and `terms` parent paths are real directories and not symlinks before snapshotting their child targets;
   - reject a symlink/non-directory parent before reading any child target through it;
   - preserve the existing rule that final owned target paths themselves may not be symlinks.

4. Keep all prior accepted safety properties:
   - only the three owned branding files may be replaced;
   - rollback restores pre-existing owned targets and removes only rollout-created empty directories;
   - unrelated files remain untouched;
   - db/api/worker/.env identity drift causes rollback;
   - no nginx edit/test/reload/restart;
   - no Docker/Compose mutation;
   - no production secrets or page bodies printed.

## Focused tests required

Add/update tests that prove:
- no-slash privacy/terms expect 301, slash forms expect 200 + correct hash;
- redirect target is the exact same-host slash URL;
- homepage/docs use canonical trailing-slash policy URLs;
- local HEAD must equal release SHA;
- symlinked static root is rejected;
- symlinked pre-existing `privacy` or `terms` parent is rejected before target snapshot/read;
- prior success/rollback/identity/unrelated-file tests still pass.

Run focused tests, `py_compile`, Ruff check, Ruff format check, `docker compose config --quiet`, and `git diff --check`.

Record the result and exact commit SHA in `PROJECT_STATE.md`, return `CURRENT_TASK.md` to HOLD, push, and STOP.

## Not authorized

No production SSH execution, production file write, nginx action, Docker/Compose production action, production ref movement, application deploy/rollback, Google Cloud/OAuth mutation, DNS/firewall change, DB write, or Telegram work.
