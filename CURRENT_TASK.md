# Current task — Telegram MTProto M4AH2R: runtime-stage diagnostics and child-scope fix

## Status

M4AH2 was executed exactly once on approved SHA:
`0e512795c2e389f1e84e7682457395b3daee7bd0`.

Transport:
- strict pinned SSH PASS on attempt 1;
- SSH auth PASS;
- remote helper started;
- no production mutation.

Sanitized result:
- `FAILURE_STAGE=STAGE_1_RUNTIME`;
- `RAW_EXCEPTION_CLASS=RuntimeError`;
- `MESSAGE_ORDINAL=0`;
- `TELEGRAM_NETWORK_CALLS=0`.

Therefore M4AH2 produced no Telegram/auth/history evidence.

Static review found an additional guaranteed child-script defect:
- the embedded API-container child probe references `PAGE_SIZE`;
- `PAGE_SIZE` is defined in the outer remote helper but NOT inside the child script scope;
- if runtime startup were fixed, Stage 3 would later fail with a child-scope `NameError`.

This task authorizes only **corrective implementation + local tests + review-branch push**.

NO production execution is authorized.

## Branch / base

Continue on:
`review/telegram-mtproto-m4ah`

Base:
`0e512795c2e389f1e84e7682457395b3daee7bd0`

Do not modify main or production.

## Goal

Make the inner API-container probe self-diagnosing and self-contained so that:

1. import/runtime/bootstrap failures are surfaced as sanitized child failure stages/classes instead of collapsing to outer `STAGE_1_RUNTIME / RuntimeError`;
2. `PAGE_SIZE=100` is defined inside the child script itself;
3. success protocol is internally consistent:
   - `FIRST_PAGE_PASS=true` requires `ENTRIES_NONE=0`;
4. no raw child stderr/stdout is leaked.

## Required fix A — child-scope PAGE_SIZE

Inside the embedded child Python script itself, define:

`PAGE_SIZE = 100`

Do not rely on the outer helper variable.

Tests must prove the child script compiles and that `PAGE_SIZE` is available where `iter_messages(... limit=PAGE_SIZE ...)` is executed.

## Required fix B — sanitized inner bootstrap/import diagnostics

The current child script has top-level imports before `run_probe()`.
If one of those imports fails, the child process exits nonzero and the outer helper only sees generic runtime failure.

Refactor so import/bootstrap failures are converted inside the child process into the same strict protocol.

At minimum distinguish sanitized stages:

- `STAGE_1_IMPORTS`
- `STAGE_1_DB_SESSION`
- existing structural stages thereafter.

Allowed example behavior:

- import failure:
  - `FAILURE_STAGE=STAGE_1_IMPORTS`
  - `RAW_EXCEPTION_CLASS=<class-name-only>`
  - `MESSAGE_ORDINAL=0`
  - `TELEGRAM_NETWORK_CALLS=0`

- SessionLocal/open/query bootstrap failure:
  - `FAILURE_STAGE=STAGE_1_DB_SESSION`
  - class only
  - ordinal 0
  - network calls 0

Do not emit exception messages or tracebacks.

The child should return process exit code 0 after a valid sanitized diagnostic failure so the parent parser can preserve the real stage/class.

## Required fix C — parent child-process handling

If child:
- returncode == 0;
- stderr empty;
- stdout follows strict allowlist;

then preserve sanitized diagnostic failure/success.

If child:
- returncode != 0; OR
- stderr non-empty; OR
- malformed/unknown output;

then parent must fail closed without echoing raw child content.

The parent may emit:
- `FAILURE_STAGE=OUTPUT_ALLOWLIST` or another hardcoded local harness stage;
- `MESSAGE_ORDINAL=0`;
- `TELEGRAM_NETWORK_CALLS=0`.

Do not regress to generic raw RuntimeError hiding a valid child protocol result.

## Required fix D — success protocol invariants

Tighten `parse_page_output()`.

If `FIRST_PAGE_PASS=true`, require all:
- no `FAILURE_STAGE`;
- `ENTRIES_NONE=0`;
- `MESSAGES_SEEN` present;
- `ENTRIES_CONVERTED` present;
- `MESSAGES_SEEN == ENTRIES_CONVERTED`;
- all success counts 0..100.

If failure:
- require:
  - `FAILURE_STAGE`;
  - `RAW_EXCEPTION_CLASS`;
  - `MESSAGE_ORDINAL`;
- reject `FIRST_PAGE_PASS`.

Do not allow synthetic success payloads with `ENTRIES_NONE>0`.

## Required fix E — preserve exact provider behavior

Do not alter the intended live probe behavior:
- connect <= 1;
- auth check <= 1;
- one `iter_messages(input_peer, limit=100, reverse=False)`;
- consume <= 100 yielded messages;
- exact `_history_entry_from_message()`;
- first conversion exception => stop;
- first `None` => `InvalidHistoryEntry`;
- no application `fetch_history()`;
- no materialization;
- no DB writes;
- no login/discovery/write RPC;
- disconnect in finally.

## Required focused tests

Add/adjust explicit executable tests for at least:

1. embedded child script compiles independently;
2. child defines `PAGE_SIZE=100` in its own scope;
3. import failure -> sanitized `STAGE_1_IMPORTS`, class only, ordinal 0, calls 0;
4. DB session/query bootstrap failure -> sanitized `STAGE_1_DB_SESSION`, class only, ordinal 0, calls 0;
5. sanitized child failure exits 0 and is preserved by parent;
6. nonzero child exit never leaks raw stderr/stdout;
7. child stderr never leaks;
8. malformed child output fails closed;
9. success with `ENTRIES_NONE>0` rejected;
10. success missing counts rejected;
11. success requires seen == converted;
12. failure requires stage/class/ordinal;
13. Stage 2/3 provider-call limits unchanged;
14. `limit=100, reverse=False` unchanged;
15. no application `fetch_history()`;
16. no materialization/DB-write/login/discovery/write RPC;
17. disconnect success/failure;
18. all existing M4AH safety tests remain passing.

Run:
- focused pytest;
- Ruff on changed Python;
- `git diff --check`.

## Review handoff

After fixes:
- commit on same review branch;
- push only `review/telegram-mtproto-m4ah`;
- do NOT run production probe;
- report:
  - full corrective SHA;
  - focused test count/pass;
  - Ruff;
  - diff-check;
  - blocker -> fix summary;
  - remaining gaps.

Final marker:
`TELEGRAM_MTPROTO_M4AH2R_REVIEW_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
