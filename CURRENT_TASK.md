# Current task — Bind branding page bytes to the exact release object

## Review state

Commit `5dff00d482eafc7982d7ea2a6c763fc806d6f3d0` closes the prior nginx-route, release-binding, and symlink blockers, but is NOT YET DEPLOY-READY.

Production remains unchanged at `3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c`, Alembic `0046`.

## Authorization

Code/test/documentation only. Do NOT execute the publisher against production.

## Required correction

1. Before any static-root snapshot/read/write, the remote helper must prove the production repository tracked worktree is clean:
   - use a bounded tracked-files-only Git status check;
   - untracked production files such as `.env` must not be enumerated or printed;
   - any tracked modification/deletion/type change must fail closed with a sanitized error.

2. Bind the three source page byte streams to the exact authorized `release_sha`, not merely to mutable worktree files:
   - load or independently verify:
     - `infra/public/index.html`
     - `infra/public/privacy.html`
     - `infra/public/terms.html`
     against the Git objects at the exact authorized release;
   - preferred shape: read the bytes directly from `git show <release_sha>:<path>` / equivalent exact-object plumbing;
   - do not derive both the source bytes and their trust proof from the same mutable filesystem read;
   - missing/non-blob source objects must fail closed before any target write.

3. Preserve all accepted gates:
   - local `HEAD == origin/main == --release-sha`;
   - remote `HEAD == origin/production == release_sha`;
   - canonical path/origin and pinned SSH trust;
   - static-root and parent symlink rejection;
   - only three owned target files;
   - rollback on identity or HTTP/hash verification failure;
   - 200 exact hashes for `/`, `/privacy/`, `/terms/`;
   - exact same-host 301 redirects for `/privacy` and `/terms`;
   - unrelated path 404;
   - no nginx or Docker mutation.

## Focused tests required

Add tests proving:
- a dirty tracked source page is rejected before any target write;
- a dirty unrelated tracked repository file is also rejected before any target write;
- untracked files do not need to be listed or exposed by the cleanliness check;
- page bytes are obtained/validated from the supplied exact release object;
- a source object mismatch or missing source fails before target mutation;
- existing success, rollback, redirect, exact-release, symlink, identity, and unrelated-file tests still pass.

Run focused tests, `py_compile`, Ruff check, Ruff format check, `docker compose config --quiet`, and `git diff --check`.

Record the result and exact commit SHA in `PROJECT_STATE.md`, return `CURRENT_TASK.md` to HOLD, push, and STOP.

## Not authorized

No production SSH execution, production file write, nginx action, Docker/Compose production action, production ref movement, application deploy/rollback, Google Cloud/OAuth mutation, DNS/firewall change, DB write, or Telegram work.
