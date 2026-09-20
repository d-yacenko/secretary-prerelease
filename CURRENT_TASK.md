# Current task — Telegram MTProto M4AH2R2: enforce child stderr fail-closed

## Status

M4AH2R corrective implementation:
`162eb4cc7cd677bf8d9ef97df194ec0f514d60f0`

Branch:
`review/telegram-mtproto-m4ah`

Architect review: almost accepted, but NOT yet authorized for live execution.

Confirmed good:
- origin review branch points exactly to corrective SHA;
- child owns `PAGE_SIZE = 100`;
- embedded child compiles;
- import failures are sanitized as `STAGE_1_IMPORTS`;
- DB session/query failures are sanitized as `STAGE_1_DB_SESSION`;
- valid sanitized child failures exit 0;
- success requires `ENTRIES_NONE=0`, required counts, and seen == converted;
- raw child stdout is still filtered by the outer local allowlist;
- provider-call limits and no-write semantics remain intact.

One blocking gap remains.

## Blocker — nested child stderr is ignored

Inside the remote helper:

`result = run(COMPOSE + ["exec", "-T", "api", "python3", "-"], input=probe)`

captures BOTH child stdout and child stderr.

Current code checks:
- `result.returncode != 0`

but does NOT check:
- `result.stderr`.

Therefore a child process may:
- return 0;
- emit allowlisted stdout;
- also emit unexpected stderr;

and the harness can still accept the stdout result.

The required contract is:
**any non-empty child stderr must fail closed and must never be echoed raw.**

## Authorization

This task authorizes only:
- minimal corrective implementation;
- focused local tests;
- Ruff;
- `git diff --check`;
- commit + push on the same review branch.

NO production execution.

## Branch / base

Continue:
`review/telegram-mtproto-m4ah`

Base:
`162eb4cc7cd677bf8d9ef97df194ec0f514d60f0`

Do not modify main or production.

## Required fix

Immediately after the nested API-container child returns:

- if `result.returncode != 0` OR `result.stderr` is non-empty:
  - do NOT print child stdout;
  - do NOT print child stderr;
  - emit only sanitized harness failure;
  - `MESSAGE_ORDINAL=0`;
  - `TELEGRAM_NETWORK_CALLS=0`;
  - normal remote end marker;
  - no retry after remote start.

Preferred sanitized stage:
`STAGE_1_RUNTIME`

Do not include the child exception message, stderr content, traceback, IDs, secrets, or raw output.

Only when:
- returncode == 0;
- child stderr exactly empty;

may the remote helper forward child stdout to the existing outer allowlist parser.

## Required tests

Add executable tests proving:

1. nested child returncode=0 + non-empty stderr fails closed;
2. child stdout is NOT forwarded when stderr is non-empty;
3. child stderr is NOT forwarded;
4. sanitized output contains only:
   - `FAILURE_STAGE=STAGE_1_RUNTIME`
   - safe class token if current protocol requires it;
   - `MESSAGE_ORDINAL=0`
   - `TELEGRAM_NETWORK_CALLS=0`
   - remote end marker;
5. nested child nonzero exit remains fail-closed with no raw stdout/stderr;
6. nested child exit 0 + empty stderr + valid stdout remains preserved;
7. all previous M4AH/M4AH2R tests remain PASS.

Do not weaken:
- strict SSH pinning;
- Stage 0 guards;
- output allowlist;
- PAGE_SIZE=100;
- provider-call budget;
- no DB writes/login/discovery/write RPC;
- disconnect finally.

Run:
- focused pytest;
- Ruff changed Python;
- `git diff --check`.

## Review handoff

Commit and push only:
`review/telegram-mtproto-m4ah`

Report:
- full corrective SHA;
- focused test count/pass;
- Ruff;
- diff-check;
- exact stderr fix;
- remaining gaps.

Do NOT run production probe.

Final marker:
`TELEGRAM_MTPROTO_M4AH2R2_REVIEW_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
