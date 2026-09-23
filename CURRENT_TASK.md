# Current task — Suppress helper import-time output in Telegram E2E bootstrap

## Architect review

Commit:

`88e9055d901a931f4df2dc66b6e8b5a1011d8142`

correctly replaces the acceptance container-create path with stdin-fed `docker compose exec -T -w /app ... api python3 -B -` inside the already-running production API container.

The exec/container/build/pull/filesystem contract is accepted.

One privacy blocker remains before live readiness.

The in-memory helper import currently executes:

`exec(compiled, module.__dict__)`

without redirecting helper stdout. Therefore top-level helper code can emit arbitrary stdout before the harness terminal protocol owns the output. The focused test currently demonstrates this by expecting `HELPER_IMPORT` in public stdout.

That violates the fail-closed requirement that partial/nonterminal helper output, credentials, provider responses, Telegram content, traceback, and exception details are never surfaced.

No live E2E is authorized.

Production runtime remains:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Alembic remains:

`0046`

Long-running Telegram AI remains false.

## Authorized work

Code/test-only correction in the stdin bootstrap.

1. Execute the compiled helper module under redirected stdout and stderr.
2. Discard all helper top-level/import-time stdout and stderr, whether import succeeds or fails.
3. Keep bootstrap-owned markers outside that redirection:
   - `SELF_E2E_STARTUP=bootstrap`
   - `SELF_E2E_STARTUP=compiled`
   - `SELF_E2E_STARTUP=imported`
   - fixed `compile_failed`
   - fixed `import_failed`
4. Only after a successful import and `SELF_E2E_STARTUP=imported` may helper `main(["--live"])` run under the existing captured-output protocol.
5. Preserve existing terminal propagation:
   - legitimate `SELF_E2E_BLOCKED=...`;
   - legitimate `SELF_E2E_FAILED=...`;
   - complete success output containing exact `SELF_AUTHORED=PASS`.
6. Preserve `harness_protocol` fail-closed behavior for exception/nonterminal main results.
7. Do not surface raw stderr, traceback, exception messages, import-time stdout, partial helper output, credentials, provider responses, or Telegram content.
8. Do not alter the accepted `docker compose exec` command, ref/origin/host-key/long-running-AI guards, or process-local AI semantics.

## Required tests

Add/update focused tests proving at least:

1. top-level helper stdout is not present in public stdout;
2. top-level helper stderr is not present in public stderr or stdout;
3. import-time code that prints a secret fixture and then raises returns only startup markers plus fixed `import_failed`, without the fixture text;
4. successful import still emits `SELF_E2E_STARTUP=imported`;
5. helper `main(["--live"])` is called exactly once after import;
6. legitimate BLOCKED/FAILED/PASS main output still propagates with the correct exit code;
7. exception/nonterminal main output still becomes fixed `harness_protocol`;
8. exec command remains `docker compose exec -T -w /app ... api python3 -B -`;
9. no run/create/up/build/pull path and no filesystem writes reappear.

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
