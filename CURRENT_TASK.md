# Current task — Telegram MTProto M4AG1R: fail-closed guard + strict output allowlist

## Status

M4AG1 implementation at:
`7f592deee20b92a3ed5a4e47ae11aec052a09200`

Branch:
`review/telegram-mtproto-m4ag`

Architect review: NOT ACCEPTED for live execution yet.

The core staged design is sound, but two blocking defects remain.

### Blocker 1 — Stage 0 is not fail-closed

Current remote helper emits:
- `RELEASE_REF_MATCH`
- `PRODUCTION_REF_MATCH`
- `PRODUCTION_WORKTREE_CLEAN`

but does not stop when any is false.

A live provider probe must never proceed to `client.connect()` or `iter_messages()` unless all production guards pass.

### Blocker 2 — raw inner stdout passthrough violates output allowlist

Current remote helper uses:
`sys.stdout.write(result.stdout)`

This can leak unexpected stdout produced by imports/runtime/libraries even if the probe source itself only prints safe keys.

The M4AG output contract is strict allowlist only. Unexpected child stdout must never be echoed raw.

This task authorizes only corrective changes + local tests + review branch push.

NO production execution is authorized.

## Branch / base

Continue on:
`review/telegram-mtproto-m4ag`

Base:
`7f592deee20b92a3ed5a4e47ae11aec052a09200`

Do not modify main or production.

## Required fix A — fail-closed Stage 0

Before the inner runtime/provider probe is invoked, require ALL:

- local production HEAD == expected release `8091736337689b68b4510126e74d9e409397f696`;
- `origin/production` == same expected release;
- production worktree clean;
- db/api/worker running;
- DB healthy;
- Alembic == `0046`.

If any fail:
- emit only sanitized guard booleans and `FAILURE_STAGE=<stage>`;
- do NOT start the inner API-container probe;
- therefore no session/reference decrypt;
- no Telegram client construction;
- no Telegram network call.

Inside the inner probe, cardinality guards must also remain fail-closed:
- exactly one MTProto account;
- exactly one manual-selected group.

No Stage 2/3 calls unless all Stage 0 and Stage 1 gates pass.

## Required fix B — strict child-output parser/allowlist

Remove raw:
`sys.stdout.write(result.stdout)`

Implement a parser that accepts only explicitly allowlisted child output keys.

Allowed child keys:

- `STAGE_0_ACCOUNT_EXACTLY_ONE`
- `STAGE_0_MANUAL_SELECTED_GROUP_EXACTLY_ONE`
- `SESSION_DECRYPT_PASS`
- `STRING_SESSION_PARSE_PASS`
- `REFERENCE_DECRYPT_PASS`
- `REFERENCE_PARSE_PASS`
- `REFERENCE_PEER_MATCH_PASS`
- `TELEGRAM_CLIENT_CONSTRUCT_PASS`
- `CONNECT_PASS`
- `IS_USER_AUTHORIZED`
- `ITER_MESSAGES_STARTED`
- `ITER_MESSAGES_ONE_ITEM_OR_EMPTY_PASS`
- `FAILURE_STAGE`
- `RAW_EXCEPTION_CLASS`
- `CONNECT_CALL_COUNT`
- `IS_USER_AUTHORIZED_CALL_COUNT`
- `ITER_MESSAGES_CALL_COUNT`
- `TELEGRAM_NETWORK_CALLS`

Validation requirements:

### Boolean keys
Must be exactly:
- `true`
- `false`

### Count keys
Must be ASCII decimal integers in an explicitly bounded range:
- connect <= 1
- authorized <= 1
- iter_messages <= 1
- Telegram network-call count <= 3

### FAILURE_STAGE
Must be one exact value from a hardcoded enum/allowlist.

### RAW_EXCEPTION_CLASS
Must be class-name syntax only:
`[A-Za-z_][A-Za-z0-9_]{0,127}`

No dots, spaces, colons, messages, reprs, brackets, quotes.

### Unexpected output
If ANY non-empty child stdout line:
- lacks exactly one `=`;
- has an unknown key;
- has an invalid value;
- duplicates a key that should be unique;

then:
- do not echo that raw line;
- fail closed with a local sanitized marker such as `FAILURE_STAGE=OUTPUT_ALLOWLIST`;
- never include the offending content in stdout/stderr.

Child stderr must also never be echoed raw.
If child process stderr is non-empty or return code != 0:
- report only sanitized stage/class derived locally;
- no raw stderr.

## Required fix C — success/failure semantics

A child probe that emits a valid diagnostic failure, e.g.:
- local structural failure;
- authorization false;
- raw exception class from Stage 2/3;

is a **successful execution of the diagnostic**, not an SSH transport failure.

Therefore:
- no SSH retry once remote helper has started;
- sanitized evidence should still reach the caller;
- remote helper may end with its normal end marker after a valid diagnostic outcome.

But:
- malformed/unallowlisted output is a diagnostic harness failure;
- still no SSH retry after remote start.

## Required tests

Expand focused tests with explicit assertions for:

1. release mismatch stops before inner probe/provider call;
2. production-ref mismatch stops before inner probe/provider call;
3. dirty production worktree stops before inner probe/provider call;
4. Alembic mismatch stops before inner probe/provider call;
5. cardinality mismatch gates Stage 2/3;
6. raw child stdout is never passed through;
7. unknown output key fails closed without echoing offending line;
8. malformed output line fails closed without echoing content;
9. invalid boolean fails closed;
10. over-bound call count fails closed;
11. duplicate unique key fails closed;
12. `RAW_EXCEPTION_CLASS` accepts class-name syntax only;
13. exception message / traceback-shaped value is rejected;
14. child stderr is never echoed;
15. valid failure diagnostic is preserved and does not trigger SSH retry;
16. valid success output still reaches caller;
17. original M4AG safety tests remain passing.

Run:
- focused pytest;
- Ruff on changed Python;
- `git diff --check`.

## Review handoff

After fixes:
- commit on same review branch;
- push only `review/telegram-mtproto-m4ag`;
- do NOT run production probe;
- report:
  - full corrective SHA;
  - focused test count/pass;
  - Ruff;
  - diff-check;
  - blocker -> fix summary;
  - remaining gaps.

Final marker:
`TELEGRAM_MTPROTO_M4AG1R_REVIEW_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
