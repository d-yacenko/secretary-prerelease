# Current task — Read-only production diagnosis of occupied public ports

## Accepted state

- Production application deploy of exact release `3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c` is ACCEPTED / PASS.
- Production Alembic is `0046`.
- DB container/volume and `.env` were unchanged; API and worker were recreated normally.
- First `public_web` rollout stopped before service start with:
  `PUBLIC_WEB_BLOCKED=public web ports already occupied`.
- No `public_web` service start, HTTPS branding verification, DNS/firewall change, or Google Cloud/OAuth mutation occurred.

Do not rerun deploy. Do not rerun `public_web` until this diagnostic is reviewed.

## Authorization

One BREAK-GLASS READ-ONLY production diagnostic is authorized solely to identify the current owners of TCP listeners on ports 80 and/or 443.

This explicit task permits pinned-host-key production SSH only for the fixed read-only observations below. It does NOT authorize any production mutation.

## Required sequence

1. Bootstrap from a fresh canonical clean checkout using `AGENTS.md` and `docs/executor_bootstrap.md`.
2. Fetch authoritative refs and verify:
   - `origin/production == 3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`;
   - production checkout HEAD is the same exact release before any remote observation.
3. Use the canonical target and pinned host-key contract. Do not discover or guess another host.
4. Perform only read-only observations sufficient to report:
   - whether TCP 80 is listening, including bound address and owning process name/PID when the OS exposes it;
   - whether TCP 443 is listening, including bound address and owning process name/PID when the OS exposes it;
   - whether either listener corresponds to a running Docker container, and if so only container ID/name/image/published-port mapping;
   - whether Compose sees any existing `public_web` container in all states.
5. Preferred bounded commands are read-only equivalents of:
   - `ss -ltnp`;
   - `docker ps --format ...`;
   - canonical Compose `ps --all -q public_web`.
   If PID ownership is not visible, reading only the relevant process `comm` or executable path is allowed. Do not dump process environments, full arbitrary command lines, files, configs, certificates, keys, or secrets.
6. Sanitize output. Record only listener ownership facts needed for architectural review.
7. Update `PROJECT_STATE.md` with the diagnostic result, return `CURRENT_TASK.md` to HOLD, commit/push, and STOP.

## Strictly not authorized

- stopping, killing, restarting, reloading, disabling, removing, renaming, or reconfiguring any process/container/service;
- changing ports, firewall, DNS, Caddy/nginx/Apache/Traefik config, Docker networks, Compose definitions, systemd units, or production files;
- starting `public_web`;
- rerunning `public_web_rollout.py`;
- rerunning the application deploy;
- Google Cloud/OAuth changes;
- production env changes;
- DB writes;
- Telegram changes;
- probing unrelated services or ports.

If the fixed read-only diagnostic cannot establish ownership, record the narrow blocker and STOP. Do not broaden discovery.
