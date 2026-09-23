# Current task — Fix invalid Docker Compose one-shot option

## Root cause

The second explicitly authorized replacement live self-authored Telegram E2E was executed exactly once and returned:

```text
SELF_E2E_REMOTE_BLOCKED=oneshot_failed
```

Exit status: `1`.

No retry, direct SSH, manual Docker command, or correction was performed.

Architect review localized the failure before the first Python bootstrap marker. The canonical wrapper currently invokes:

`docker compose run ... --no-build ...`

Official Docker Compose `run` supports `--build`, `--no-deps`, `--rm`, `--pull`, env/volume options, etc., but not `--no-build`. Therefore Compose can reject the command during CLI parsing before creating the one-shot container. Because child stderr is intentionally suppressed, that failure collapses to `SELF_E2E_REMOTE_BLOCKED=oneshot_failed`.

This explains both observed startup-only live failures without implicating Telegram, ML/LLM providers, the helper import path, or the downstream pipeline.

The replacement live authorization is consumed. No further live run is authorized.

Production runtime remains:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Alembic remains:

`0046`

Long-running Telegram AI remains false.

## Authorized work

Code/test-only correction in `ops/production/telegram_self_authored_e2e_remote.py` and focused tests.

1. Remove the unsupported `--no-build` option from the `docker compose run` command.
2. Preserve `--rm` and `--no-deps`.
3. Do not add `--build`.
4. Prefer adding `--pull never` to the one-shot command, since it is supported by `docker compose run`, so the acceptance path cannot pull a new image.
5. Add a read-only precondition in the generated remote program that verifies the existing production `api` service image is resolvable/present before the one-shot. If the image is not present/resolvable, fail closed with a fixed sanitized blocker such as `SELF_E2E_REMOTE_BLOCKED=image_missing`; do not build or pull.
6. Preserve all existing production-ref/worktree/origin/host-key/long-running-AI/startup/import/harness-protocol privacy guards.
7. Continue suppressing raw Docker stderr, tracebacks, env values, credentials, provider output, and Telegram content.

## Tests

Add focused tests proving:

- generated `docker compose run` contains no `--no-build`;
- it contains no `--build`;
- it retains `--rm` and `--no-deps`;
- if used, `--pull never` is present in the correct command position;
- existing image precondition succeeds only with a non-empty image id and otherwise emits only the fixed sanitized blocker;
- no test invokes real Docker, SSH, Telegram, providers, or production DB;
- existing startup/compile/import/harness-protocol tests remain green.

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

A new live attempt requires separate Architect review and new explicit human authorization.
