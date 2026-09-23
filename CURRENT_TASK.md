# Current task — Replace Telegram E2E one-shot create path with exec-in-running-api

## Architect review

Commit:

`7d571f410a31e4fc322f90ae0ac5e976b300b4fb`

correctly removes the unsupported `docker compose run --no-build` option and adds useful image diagnostics, but it is NOT accepted as live-ready.

Reason: for `docker compose run`, omitting `--build` does not establish a hard no-build guarantee. Current Compose internals still construct build options for the run/create path when a service has a `build:` definition, while `run` exposes no public `--no-build` flag. `--pull never` prevents pulls only; it does not prove that the create path cannot build. The current running-container image-id precondition also does not force `compose run api` to use that exact image id.

No new live E2E is authorized.

Production runtime remains:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Alembic remains:

`0046`

Long-running Telegram AI remains false.

## Authorized work

Code/test-only correction of the self-authored E2E remote execution path.

Replace the one-shot container creation path with a separate Python process executed inside the already-running production `api` container.

Use the canonical Compose files and an exec command equivalent to:

```text
docker compose --env-file /opt/secretary/.env \
  -f infra/compose.yaml \
  -f infra/compose.deploy.yaml \
  exec -T \
  -w /app \
  -e SELF_E2E_CONFIRM=reviewed \
  -e REHEARSAL_LONG_RUNNING_API_AI=false \
  -e REHEARSAL_LONG_RUNNING_WORKER_AI=false \
  api python3 -B -
```

The exact option ordering may follow Compose CLI requirements, but the resulting operation must be `exec`, not `run`, `create`, `up`, or `build`.

### Bootstrap requirements

- Feed the acceptance bootstrap through stdin.
- Embed the helper source in the stdin program; do not write helper/bootstrap files into the production checkout or container filesystem.
- Before helper execution, bootstrap code must use Python standard library only.
- Emit the existing startup protocol:
  - `SELF_E2E_STARTUP=bootstrap`
  - `SELF_E2E_STARTUP=compiled`
  - `SELF_E2E_STARTUP=imported`
- Compile the helper source in memory.
- Execute it in an isolated synthetic module namespace with `__name__` not equal to `"__main__"`.
- Call helper `main(["--live"])` exactly once.
- Preserve fixed sanitized `compile_failed`, `import_failed`, and `harness_protocol` behavior.
- Preserve propagation of legitimate `SELF_E2E_BLOCKED=...`, `SELF_E2E_FAILED=...`, and complete success output containing the exact `SELF_AUTHORED=PASS` line.
- Suppress raw stderr, traceback, exception text, partial nonterminal helper output, credentials, provider responses, and Telegram content.

### Safety requirements

The exec process inherits the already-running container environment. The three `-e` overrides above apply only to the exec process.

Keep the existing explicit probes proving long-running API and worker `TELEGRAM_MTPROTO_AI_ENABLED` are false before acceptance starts.

Do not set global/container `TELEGRAM_MTPROTO_AI_ENABLED=true`.

Remove the now-unneeded one-shot image-resolution/build/pull logic and temporary `/tmp` helper/bootstrap file writes if they are no longer used.

The acceptance path must contain no Docker image build, pull, create, run, restart, or recreate operation.

## Required tests

Add/update focused tests proving at least:

1. the acceptance command uses `docker compose exec`, not `run`, `create`, `up`, or `build`;
2. it contains `-T`, `-w /app`, the three required exec-only env overrides, service `api`, and `python3 -B -`;
3. there is no `--build`, `--pull`, helper volume mount, or one-shot container creation path;
4. bootstrap/helper source is passed via stdin and no helper/bootstrap file is written to remote/container filesystem;
5. bootstrap marker precedes helper execution;
6. syntax failure -> fixed `compile_failed`;
7. top-level helper execution/import failure -> fixed `import_failed`;
8. helper `main(["--live"])` is called exactly once;
9. legitimate BLOCKED/FAILED/success output and exit code propagation remain correct;
10. exception/nonterminal result -> fixed `harness_protocol`;
11. raw stderr/traceback/secret fixture text is never surfaced;
12. checkout/ref/origin/host-key/long-running-AI guards remain unchanged.

No test may invoke real Docker, SSH, Telegram, providers, or production DB.

Run focused tests, `py_compile`, Ruff check/format, and `git diff --check`.

## Hard stop

No production SSH.
No production Docker.
No remote wrapper execution.
No live E2E.
No provider calls.
No Telegram transport/session access.
No production DB writes.
No deploy/restart/recreate.
No production env changes.
No production ref movement.

When complete, update `PROJECT_STATE.md` factually, commit and push, report SHA/checks, then STOP.

Any future live E2E requires separate Architect acceptance and new explicit human authorization.
