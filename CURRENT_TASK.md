# Current task — Read-only inspection of active production nginx routing

## Accepted state

- Production application runtime is exact `3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`, Alembic `0046`.
- Application deploy is accepted.
- First `public_web` rollout did not start the service.
- TCP 80 and 443 are owned by host-level nginx, not Docker.
- No Compose `public_web` container exists.
- The current standalone Caddy host-port rollout design is blocked until nginx routing ownership is understood.

## Authorization

One BREAK-GLASS READ-ONLY production diagnostic is authorized solely to identify the active nginx routing relevant to `web-itx.duckdns.org` and ports 80/443.

This task authorizes no nginx reload/restart/edit and no other production mutation.

## Required sequence

1. Bootstrap from a fresh canonical clean checkout using `AGENTS.md` and `docs/executor_bootstrap.md`.
2. Verify authoritative `origin/production == 3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c` and production checkout HEAD equals the same release.
3. Use only the canonical pinned production SSH target.
4. Inspect the effective nginx configuration read-only. `nginx -T` or an equivalent config-test/dump is allowed, but report only the bounded facts below.
5. Report only:
   - nginx version;
   - which config file/server block handles `web-itx.duckdns.org`, if any;
   - the relevant `listen` directives for that server block;
   - whether HTTP redirects to HTTPS;
   - relevant `location` paths and their routing type: `proxy_pass`, static `root/alias`, or fixed `return`;
   - the upstream destination for the Secretary application only as host:port or local socket, without credentials/query strings;
   - certificate/key FILE PATHS only if needed to understand TLS ownership; never read certificate/key contents;
   - if no matching `server_name` exists, identify only the default 80/443 server behavior that currently receives this hostname.
6. Do not report unrelated domains/server blocks. Do not dump full configs, environment variables, certificates, keys, auth files, access logs, request bodies, headers, tokens, or secrets.
7. Make no changes. Do not run `nginx -s reload`, `systemctl restart/reload`, package operations, edits, writes, chmod/chown, Docker changes, firewall/DNS changes, deploy, or `public_web`.
8. Record sanitized findings in `PROJECT_STATE.md`, return `CURRENT_TASK.md` to HOLD, commit/push, and STOP.

## Goal

Determine whether the branding pages should be integrated into the existing nginx front door and what the smallest safe implementation shape would be. Do not implement that shape in this task.

If the bounded read-only inspection cannot establish the relevant routing, record the narrow blocker and STOP. Do not broaden discovery.
