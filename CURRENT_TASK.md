# Current task — Telegram MTProto M4AM1R: correct two-page probe failure protocol

## Status

M4AM1 implementation:
`122daf0a0c8e361919415dc478174d8c1f5f390e`

Branch:
`review/telegram-mtproto-m4am`

Architect review: NOT yet accepted for live execution.

Confirmed good:
- origin review branch points exactly to implementation SHA;
- only diagnostic script + focused test file added;
- page size 100 / max 200;
- production-like initial vs established history ordering;
- optional page2 backfill;
- fresh client construction inside per-page helper;
- exact conversion helper and production backfill helper imported;
- no application fetch_history/materializer/DB writes;
- strict pinned SSH and fail-closed raw-output handling;
- production not touched.

Three corrective issues remain.

## Blocker 1 — realistic page2 failure is rejected by parent parser

Current parser contains logic equivalent to:

if PAGE1_PASS=true and PAGE2_REQUIRED=true and PAGE2_PASS != true:
    reject

This also runs when a valid page2 failure is present.

Therefore the exact desired protocol:

- PAGE1_PASS=true
- PAGE2_REQUIRED=true
- FAILURE_STAGE=STAGE_5_PAGE2_ITERATION or STAGE_5_PAGE2_CONVERSION
- RAW_EXCEPTION_CLASS=...
- MESSAGE_ORDINAL=...
- no PAGE2_PASS

is incorrectly rejected.

Required fix:

- a page2 failure must be accepted when:
  - PAGE1_PASS=true;
  - PAGE2_REQUIRED=true;
  - FAILURE_STAGE is one of the PAGE2 stages;
  - PAGE2_PASS is absent;
  - failure fields are complete;
  - bounded call counts are valid.

- PAGE2_PASS must be required only for overall success / absence of FAILURE_STAGE.

- reject impossible combinations, including:
  - page2 failure when PAGE2_REQUIRED=false;
  - PAGE2_PASS=true together with PAGE2 FAILURE_STAGE;
  - page1 failure together with PAGE1_PASS=true;
  - success totals when an incompatible failure is present.

Add an executable regression using the realistic output shape produced after page1 succeeds and page2 fails.

## Blocker 2 — conversion None classification must be deterministic

Current child uses:

`ValueError("InvalidHistoryEntry")`

when `_history_entry_from_message(message)` returns None.

Because only class name is emitted, this becomes:

`RAW_EXCEPTION_CLASS=ValueError`

and cannot be distinguished from an actual conversion ValueError.

Required fix:

- use a local safe exception class such as:
  `InvalidHistoryEntry`
- emit:
  `RAW_EXCEPTION_CLASS=InvalidHistoryEntry`
- keep stage page-specific:
  - STAGE_3_PAGE1_CONVERSION
  - STAGE_5_PAGE2_CONVERSION

No exception message output.

## Corrective 3 — sanitized structural failures must terminate cleanly

Several child paths currently call `fail(...)` but then continue execution.

Examples include cardinality/decrypt/reference failures.

That can turn a valid sanitized failure into a later Python exception/stderr, which the outer layer then collapses.

Required fix:

- after any terminal structural `fail(...)`, execution must return/exit immediately;
- no later access to potentially unset variables;
- child must finish with exit 0 and no stderr after emitting the valid sanitized protocol.

Do not weaken parent fail-closed behavior for genuine child nonzero/stderr.

## Additional protocol tightening

Review and test:

- PAGE1 failure cannot coexist with PAGE1_PASS=true;
- PAGE2 failure requires PAGE2_REQUIRED=true and PAGE1_PASS=true;
- PAGE2 success requires PAGE2_REQUIRED=true;
- overall no-failure success requires PAGE1_PASS=true and, if page2 required, PAGE2_PASS=true;
- totals, when emitted on success, equal sums of page counts;
- MESSAGES_SEEN_TOTAL == ENTRIES_CONVERTED_TOTAL;
- per-page seen == converted;
- ENTRIES_NONE=0;
- each page <=100, total <=200;
- call counts are coherent with pages actually attempted where practical.

Keep raw exception class identifier-only.

## Authorization

This task authorizes only:
- minimal corrective implementation;
- focused local tests;
- Ruff;
- git diff --check;
- commit + push on same review branch.

NO production SSH.
NO live provider probe.
NO Sync retry.

## Branch / base

Continue:
`review/telegram-mtproto-m4am`

Base:
`122daf0a0c8e361919415dc478174d8c1f5f390e`

Do not modify main or production runtime/ref.

## Required tests

At minimum add/adjust tests proving:

1. realistic PAGE1 PASS + PAGE2 REQUIRED + PAGE2 iteration failure is accepted;
2. same for PAGE2 conversion failure;
3. PAGE2 failure with PAGE2_REQUIRED=false is rejected;
4. PAGE2_PASS + PAGE2 failure together rejected;
5. PAGE1_PASS + PAGE1 failure together rejected;
6. overall success still requires PAGE2_PASS when page2 required;
7. conversion None emits InvalidHistoryEntry, not ValueError;
8. structural cardinality/decrypt/reference failures terminate sanitized with exit 0/no stderr;
9. success totals equal per-page sums;
10. total seen == total converted;
11. previous 30 focused tests remain passing;
12. provider-call maximums/fresh-client/no-write/no-materialization restrictions unchanged.

Run:
- focused pytest;
- Ruff changed Python;
- git diff --check.

## Handoff

Commit/push only:
`review/telegram-mtproto-m4am`

Report:
- full corrective SHA;
- focused tests count/pass;
- Ruff;
- diff-check;
- exact parser failure fix;
- InvalidHistoryEntry behavior;
- terminal failure behavior;
- remaining gaps.

Do NOT execute production probe.

Final marker:
`TELEGRAM_MTPROTO_M4AM1R_REVIEW_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
