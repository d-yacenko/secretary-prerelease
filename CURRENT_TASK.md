# Current task — Localize Telegram self-authored E2E one-shot startup failure

## Status of the consumed live attempt

Exactly one previously authorized live production self-authored Telegram E2E invocation was executed.

Sanitized stdout:

```text
SELF_E2E_REMOTE_BLOCKED=oneshot_failed
```

Exit status: `1`.

The attempt is consumed. No retry is authorized.

This result is not a Telegram/ML pipeline acceptance failure. The canonical remote wrapper passed its local/remote production-ref, worktree, origin, and long-running-AI checks, reached `docker compose run`, and received a nonzero child result with no harness-owned stdout marker. The wrapper intentionally suppressed child stderr and collapsed that class to `oneshot_failed`, so the current evidence localizes only to the one-shot container/interpreter/helper startup boundary.

Production runtime/ref remains:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Alembic remains:

`0046`

Long-running Telegram AI remains false.

## Authorized work

Code/test-only corrective work. Do not execute any production or provider operation.

Harden `ops/production/telegram_self_authored_e2e_remote.py` so a future separately-authorized one-shot can deterministically distinguish:

1. one-shot container/Python bootstrap started;
2. helper source compiled;
3. helper module imported;
4. helper `main(["--live"])` was entered and its existing sanitized protocol took over.

The bootstrap that establishes stages 1–3 must use Python standard library only and must not import `app` before the explicit helper-import stage.

## Required protocol

Preserve all existing `SELF_E2E_REMOTE_BLOCKED=...`, `SELF_E2E_BLOCKED=...`, `SELF_E2E_FAILED=...`, and success-report semantics.

Add deterministic sanitized startup evidence sufficient to separate at least:

- container/interpreter did not start;
- helper compile failure;
- helper import failure;
- helper imported and normal harness protocol ran.

Do not forward raw child stderr, exception messages, tracebacks, environment values, Telegram content, credentials, paths containing secrets, or provider responses.

An exception class may be used only if the tests prove the emitted value is a fixed allowlisted/sanitized token. Prefer fixed stage codes.

A future Docker-level failure before bootstrap may still map to a remote blocked marker, but must be distinguishable from helper compile/import failures.

## Tests

Add focused tests that execute the generated bootstrap/protocol locally with stub helper sources and prove:

- bootstrap-start marker appears before helper loading;
- syntax/compile failure maps to the compile stage and never enters helper main;
- import-time failure maps to the import stage and never enters helper main;
- successful import enters helper main exactly once;
- helper exit code/stdout are propagated unchanged once normal harness protocol owns execution;
- raw stderr/traceback text is never surfaced;
- existing local checkout/ref/host-key/long-running-AI guards remain unchanged;
- no test requires production SSH, Docker, Telegram, OpenAI, or a production DB.

Run the focused test suite, `py_compile`, Ruff check/format, and `git diff --check`.

## Hard stop

This task authorizes no production SSH, no `docker compose run` against production, no live E2E, no provider call, no Telegram transport/session access, no DB write, no deploy/restart/recreate, no production env change, and no ref movement.

When code/tests are complete, commit and push the corrective change, record the factual result in `PROJECT_STATE.md`, report the commit SHA and checks, then STOP.

Do not request or perform another live run. A replacement live authorization can only be issued after Architect review.
