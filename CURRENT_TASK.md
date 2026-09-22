# Current task — Close Telegram E2E post-import protocol blind spot

## Architect review

Commit:

`86e856b4e8ab54a2bf535eae45a002692e94ee4c`

is mostly accepted: stdlib bootstrap, compile/import stage markers, fixed sanitized compile/import failures, preserved guards, and no-repeat discipline are correct.

One blocking observability defect remains before any replacement live authorization.

The remote program currently treats any stdout containing `SELF_E2E_` as evidence that the harness produced its normal protocol. The new startup lines themselves begin with `SELF_E2E_STARTUP=`, so a failure after successful import but before a terminal harness result can bypass the `oneshot_failed` fallback and surface only startup markers with a nonzero exit. A helper that returns success without a terminal acceptance result can likewise produce startup-only stdout with exit 0.

No live run is authorized.

Production runtime/ref remains:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Alembic remains:

`0046`

Long-running Telegram AI remains false.

## Authorized work

Code/test-only corrective change in the self-authored E2E remote/bootstrap path.

Make startup-stage evidence explicitly distinct from a terminal harness outcome.

The parent remote wrapper must not treat `SELF_E2E_STARTUP=...` as a terminal harness result.

A terminal harness result is only an explicit sanitized acceptance outcome, for example:

- successful acceptance report containing `SELF_AUTHORED=PASS`;
- `SELF_E2E_BLOCKED=...`;
- `SELF_E2E_FAILED=...`;
- the bootstrap-owned fixed `SELF_E2E_REMOTE_BLOCKED=compile_failed` or `import_failed`.

If the helper is imported and `main(["--live"])` then raises, returns nonzero, or returns zero without producing an appropriate terminal harness outcome, fail closed with a fixed sanitized remote-blocked code that clearly identifies the post-import harness/protocol stage. Do not expose exception text, stderr, traceback, environment, Telegram content, provider responses, or credentials.

You may add one fixed stage marker immediately before invoking `main(["--live"])` if useful, but it must not itself count as terminal protocol evidence.

Preserve:

- existing compile/import stage behavior;
- child stdout once a legitimate terminal harness protocol is present;
- exact child exit code for legitimate blocked/failed harness results;
- all checkout/ref/origin/host-key/long-running-AI guards;
- no global `TELEGRAM_MTPROTO_AI_ENABLED=true`.

## Required tests

Add focused tests proving at least:

1. startup-only stdout never counts as a terminal harness result;
2. imported helper whose `main` raises produces a fixed sanitized post-import/protocol blocker and no traceback/error text;
3. imported helper whose `main` returns nonzero without `SELF_E2E_BLOCKED/FAILED` is fail-closed;
4. imported helper whose `main` returns zero without `SELF_AUTHORED=PASS` is fail-closed;
5. legitimate `SELF_E2E_BLOCKED=...` remains propagated with its exit code;
6. legitimate `SELF_E2E_FAILED=...` remains propagated with its exit code;
7. a complete success report containing `SELF_AUTHORED=PASS` remains propagated with exit 0;
8. compile/import failures remain distinguishable and sanitized;
9. no raw child stderr or traceback is surfaced.

Run focused tests, `py_compile`, Ruff check/format, and `git diff --check`.

## Hard stop

No production SSH.
No production Docker.
No live E2E.
No provider calls.
No Telegram transport/session access.
No production DB writes.
No deploy/restart/recreate.
No production env changes.
No production ref movement.

When complete, update `PROJECT_STATE.md` factually, commit and push, report SHA/checks, then STOP.

A replacement live E2E may only be authorized by the human after Architect acceptance of this correction.
