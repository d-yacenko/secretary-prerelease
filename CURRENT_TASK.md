# Current task — Final read-only preflight for nginx static branding root

## Accepted architecture

- Production application runtime remains exact `3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`, Alembic `0046`.
- Host nginx is the existing production front door for `web-itx.duckdns.org`.
- Public static root is `/var/www/web-itx`.
- HTTPS `/secretary/` proxies to `127.0.0.1:18080`.
- The standalone Caddy/`public_web` design is retired. Do not start it.
- Intended next implementation is a repository-controlled static-file rollout into the existing nginx root, with no nginx config edit/reload and no change to `/secretary/`.

## Authorization

One BREAK-GLASS READ-ONLY production preflight is authorized solely to establish the exact target-file and `try_files` shape needed for a safe static branding rollout.

No production mutation is authorized.

## Required observations

1. Bootstrap canonically and verify authoritative `origin/production` and production checkout HEAD remain exact `3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`.
2. Use only the pinned canonical production SSH target.
3. Report the exact `try_files` directive used by the public port-80 `location /` and public port-443 `location /` for `web-itx.duckdns.org`. Report only those directive lines, not full config.
4. For `/var/www/web-itx`, report only:
   - resolved real path;
   - directory owner:group and mode;
   - whether each bounded candidate exists, its type, owner:group, mode, byte size, and SHA-256 for regular files:
     - `index.html`
     - `privacy`
     - `privacy.html`
     - `privacy/index.html`
     - `terms`
     - `terms.html`
     - `terms/index.html`
   - do not read or print file contents.
5. Read-only HTTP(S) probes are allowed only for:
   - `http://web-itx.duckdns.org/`
   - `https://web-itx.duckdns.org/`
   - `https://web-itx.duckdns.org/privacy`
   - `https://web-itx.duckdns.org/privacy/`
   - `https://web-itx.duckdns.org/terms`
   - `https://web-itx.duckdns.org/terms/`
   - `https://web-itx.duckdns.org/secretary/`
   Report status code only. Do not report response bodies or headers.
6. Confirm only whether the nginx worker/master account can traverse/read the static root based on current ownership/mode. Do not change permissions.
7. Record sanitized findings in `PROJECT_STATE.md`, return `CURRENT_TASK.md` to HOLD, commit/push, and STOP.

## Strictly not authorized

- writing, deleting, renaming, copying, moving, chmod/chown, symlinking, or backing up any production file;
- nginx edit/test/reload/restart;
- Docker/Compose changes;
- deploy or rollback;
- `public_web` start;
- firewall/DNS/Google Cloud/OAuth changes;
- DB or application mutation;
- reading arbitrary files or file contents.

## Goal

Provide enough bounded evidence for the Architect to design the replacement static rollout so it can atomically publish only the branding pages while preserving existing nginx, ACME handling, and the `/secretary/` proxy.
