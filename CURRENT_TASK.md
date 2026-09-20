# Current task — Telegram MTProto M4AM1R2: accept structural/preflight failure protocol

## Status

M4AM1R implementation:
`ee04da7c88dc2fec1e838a92d07ab841beb25892`

Branch:
`review/telegram-mtproto-m4am`

Architect review: NOT yet accepted for live execution.

Confirmed fixed:
- realistic PAGE1 PASS + PAGE2 REQUIRED + PAGE2 failure is accepted;
- PAGE2 success/failure contradictions are rejected;
- PAGE1 success/failure contradictions are rejected;
- success totals are checked against page sums;
- `_history_entry_from_message(...) is None` now emits safe `InvalidHistoryEntry`;
- inner structural `fail(...)` is terminal via exit 0;
- provider budget/fresh-client/no-write/no-materialization behavior remains intact.

One protocol blocker remains.

## Blocker — parser rejects structural/preflight failures

Current `parse_output()` treats every `FAILURE_STAGE` as if it must be PAGE1 or PAGE2.

Therefore valid sanitized failures such as:

- `STAGE_1_IMPORTS`
- `STAGE_1_DB_SESSION`
- `STAGE_1_SESSION_DECRYPT`
- `STAGE_1_REFERENCE_DECRYPT`
- `STAGE_1_REFERENCE_PARSE`
- `STAGE_1_REFERENCE_PEER_MATCH`

are rejected with:
`failure stage is not page-specific`.

Additionally the outer remote helper emits:

- `STAGE_0_RELEASE_REF`
- `STAGE_0_PRODUCTION_REF`
- `STAGE_0_WORKTREE`

but these are not currently present in `FAILURE_STAGES`, so those guard failures are also rejected by the parent parser.

This violates the diagnostic contract: valid sanitized pre-provider failures must survive intact.

## Required fix

### 1. Add explicit preflight/structural stages

Add to the accepted failure-stage set:

- `STAGE_0_RELEASE_REF`
- `STAGE_0_PRODUCTION_REF`
- `STAGE_0_WORKTREE`

Keep existing STAGE_1 and page stages.

### 2. Classify failure stage families

Parser must distinguish three families:

#### Preflight / structural failures

Includes:
- STAGE_0_RELEASE_REF
- STAGE_0_PRODUCTION_REF
- STAGE_0_WORKTREE
- STAGE_1_IMPORTS
- STAGE_1_DB_SESSION
- STAGE_1_SESSION_DECRYPT
- STAGE_1_REFERENCE_DECRYPT
- STAGE_1_REFERENCE_PARSE
- STAGE_1_REFERENCE_PEER_MATCH

For these:
- require `RAW_EXCEPTION_CLASS`;
- require `MESSAGE_ORDINAL`;
- require `TELEGRAM_NETWORK_CALLS`;
- reject PAGE1_PASS/PAGE2_PASS;
- reject page success totals;
- provider network calls must be 0 for STAGE_0/STAGE_1 structural failures;
- preserve any already-emitted safe structural booleans;
- accept sanitized result.

#### PAGE1 failures

Keep current page1 consistency rules.

#### PAGE2 failures

Keep current page2 consistency rules:
- PAGE1_PASS=true;
- PAGE2_REQUIRED=true;
- no PAGE2_PASS;
- no overall success totals.

### 3. Network-call field required on all failures

Require:
`TELEGRAM_NETWORK_CALLS`

for every failure result.

For structural/preflight failures:
- must equal 0.

For page failures:
- must remain within existing bound and coherent enough for the attempted stage.

No need to overfit exact Telethon packet counts; use the probe's own bounded operation counter.

### 4. Preserve fail-closed behavior

Still reject:
- unknown stages;
- duplicate keys;
- malformed booleans/counts;
- stderr;
- child nonzero;
- raw/unknown output;
- impossible success/failure combinations.

Do not loosen raw-output filtering.

## Authorization

This task authorizes only:
- minimal parser/protocol corrective;
- focused tests;
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
`ee04da7c88dc2fec1e838a92d07ab841beb25892`

Do not modify main or production.

## Required executable tests

At minimum:

1. `STAGE_1_IMPORTS` sanitized failure is accepted;
2. `STAGE_1_DB_SESSION` sanitized failure is accepted;
3. each decrypt/reference STAGE_1 failure is accepted;
4. `STAGE_0_RELEASE_REF` accepted;
5. `STAGE_0_PRODUCTION_REF` accepted;
6. `STAGE_0_WORKTREE` accepted;
7. structural failure + PAGE1_PASS rejected;
8. structural failure + PAGE2_PASS rejected;
9. structural failure + success totals rejected;
10. structural/preflight failure with TELEGRAM_NETWORK_CALLS != 0 rejected;
11. any failure missing TELEGRAM_NETWORK_CALLS rejected;
12. page1/page2 failure tests from M4AM1R remain PASS;
13. realistic page2 failure remains accepted;
14. success protocol remains unchanged;
15. stderr/nonzero/malformed remain fail-closed;
16. provider-call maximum/fresh-client/no-write/no-materialization tests remain PASS.

Prefer tests that call `parse_output()` with the exact shapes emitted by the real outer/inner helpers, not only string-search assertions.

## Verification

Run:
- focused pytest;
- Ruff changed Python;
- `git diff --check`.

## Handoff

Commit/push only:
`review/telegram-mtproto-m4am`

Report:
- full corrective SHA;
- focused tests count/pass;
- Ruff;
- diff-check;
- exact stage-family parser changes;
- proof structural/preflight failures preserve sanitized protocol;
- remaining gaps.

Do NOT execute production probe.

Final marker:
`TELEGRAM_MTPROTO_M4AM1R2_REVIEW_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
