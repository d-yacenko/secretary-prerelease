# Current task — Fix deterministic streamed remote-program crash before Telegram rehearsal

## Root cause

The attempted wrapper invocation for run id `tgprod0922a` returned:

`REHEARSAL_WRAPPER_EXIT=1`

with empty stdout.

Architect review found a deterministic local code defect in
`ops/production/telegram_production_rehearsal_remote.py`:

- `build_remote_program()` inlines `_flag_enabled()`;
- `_flag_enabled()` references module constant `TRUE_FLAGS`;
- generated remote program does NOT define `TRUE_FLAGS`;
- normal remote state reaches `assess_remote_state(...)`;
- this raises `NameError` in the streamed Python program;
- traceback goes only to stderr;
- outer wrapper intentionally suppresses stderr;
- SSH returns remote exit code 1;
- local stdout is empty.

This exactly matches the observed invocation.

The failure occurs before:
- helper file write;
- `docker compose run`;
- synthetic object creation;
- ML/LLM calls;
- Telegram transport;
- production mutation.

Therefore the authorized synthetic rehearsal itself did NOT execute.

## Goal

Fix this one deterministic remote-program generation defect and make future streamed remote-program failures impossible to surface as empty stdout.

CODE/TEST ONLY. Do not run production rehearsal.

## Required correction

1. Make generated remote program self-contained:
   - define/inject `TRUE_FLAGS`, or
   - generate flag parsing without any undeclared outer-module dependency.

2. Add execution-level regression for the GENERATED remote program, not only string inspection.

The test must execute the generated program under mocked/fake subprocess behavior representing:
- exact production HEAD;
- clean worktree;
- canonical origin;
- API flag=false;
- worker flag=false;
- successful one-shot child stdout.

It must prove:
- no `NameError`;
- remote program reaches the one-shot invocation;
- child stdout is forwarded;
- child exit code is propagated.

3. Add failure regression:
- generated remote program internal unexpected exception must emit one fixed sanitized marker, for example
  `REHEARSAL_REMOTE_BLOCKED=remote_program`;
- no traceback/raw exception text on stdout;
- nonzero exit.

This is specifically to make an empty-stdout remote-program crash impossible.

4. Preserve:
- stderr suppression;
- pinned SSH;
- exact production release guard;
- clean worktree/origin checks;
- long-running API/worker AI=false probes;
- streamed helper;
- isolated `docker compose run --rm --no-deps --no-build`;
- no Docker socket;
- no deploy/restart/recreate;
- process-local AI=true only in one-shot helper;
- helper fail cleanup from `23d2521b...`.

5. Do NOT change rehearsal business logic or production release.

## Run-id semantics

Keep authorized run id:

`tgprod0922a`

Because the streamed program crashed before helper write/one-shot execution, no synthetic user/artifacts for this run id should exist from this attempt.

Do not run it live in this task.

## Validation

Run:
- focused remote-wrapper tests;
- focused rehearsal helper tests;
- py_compile;
- Ruff;
- git diff --check.

## Authorization

AUTHORIZED:
- local wrapper/tests correction;
- update PROJECT_STATE.md;
- commit/push canonical main.

NOT AUTHORIZED:
- live rehearsal;
- production SSH;
- product deploy;
- ref movement;
- production env changes;
- LLM/provider calls;
- Telegram calls;
- synthetic DB writes.

## Required report

Return:
- commit SHA;
- exact root-cause fix;
- generated-program execution regression;
- sanitized unexpected-failure regression;
- tests/compile/Ruff/diff-check;
- live rehearsal executed=0.

Final marker:

`TELEGRAM_REHEARSAL_REMOTE_PROGRAM_FIXED`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
