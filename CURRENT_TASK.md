# Current task — Telegram MTProto M4AH1R: first-page probe correctness fixes

## Status

M4AH1 implementation:
`50ae5b65ac0a243b006f352d1b585c8ae2f4f09c`

Branch:
`review/telegram-mtproto-m4ah`

Architect review: NOT ACCEPTED for live execution yet.

Reviewed files:
- `ops/production/diagnose_mtproto_history_page.py`
- `backend/tests/test_telegram_mtproto_m4ah_history_page.py`

The strict SSH transport, fail-closed outer parser, and output redaction are acceptable.

Three blocking correctness issues remain.

## Blocker 1 — failure ordinal is not emitted

M4AH1 requires:
- iteration failure => `MESSAGE_ORDINAL`;
- conversion failure => `MESSAGE_ORDINAL`.

The current helper emits only:
- `FAILURE_STAGE`;
- `RAW_EXCEPTION_CLASS`.

The parser/tests accept ordinal fields but the real helper does not produce them.

### Required semantics

Maintain an ordinal meaning "the message position whose retrieval/conversion is being attempted".

For conversion failure:
- ordinal = current yielded message position, 1..100.

For raw iterator failure:
- before any message is yielded => ordinal 0;
- if N messages were successfully yielded and iterator fails while obtaining the next item => ordinal = min(N + 1, 100).

Emit:
`MESSAGE_ORDINAL=<0..100>`

Never emit a message ID.

## Blocker 2 — authorization-check exception is misclassified

Current logic sets `authorized_calls = 1` before:
`await client.is_user_authorized()`

The broad outer exception handler then classifies an exception raised by `is_user_authorized()` as `STAGE_3_ITERATION`.

That is incorrect.

### Required semantics

Distinguish explicitly:

- exception from `client.connect()`
  => `FAILURE_STAGE=STAGE_2_CONNECT`

- exception from `client.is_user_authorized()`
  => `FAILURE_STAGE=STAGE_2_AUTHORIZED`

- authorized == false
  => `FAILURE_STAGE=STAGE_2_AUTHORIZED`
  and sanitized `RAW_EXCEPTION_CLASS=AuthorizationFalse`

- exception while obtaining/yielding raw history messages
  => `FAILURE_STAGE=STAGE_3_ITERATION`

- exception from `_history_entry_from_message(message)`
  => `FAILURE_STAGE=STAGE_3_CONVERSION`

Do not infer stage from counters after the fact; use narrowly-scoped try/except or an explicit stage variable.

## Blocker 3 — conversion None does not match production fetch_history semantics

Exact release `8091736337689b68b4510126e74d9e409397f696` does:

`entry = _history_entry_from_message(message)`

then, if `entry is None`:
raises `TelegramMtprotoProviderUnavailableError`.

The current diagnostic instead increments `ENTRIES_NONE` and continues, eventually declaring `FIRST_PAGE_PASS=true`.

That does not reproduce the production first-page behavior.

### Required semantics

On the first `entry is None`:

- stop page processing;
- emit:
  - `FAILURE_STAGE=STAGE_3_CONVERSION`
  - `RAW_EXCEPTION_CLASS=InvalidHistoryEntry` (diagnostic sentinel class-name token is acceptable)
  - `MESSAGE_ORDINAL=<current 1..100>`
- do not continue to later messages;
- `FIRST_PAGE_PASS` must not be true.

Keep `ENTRIES_NONE` only if useful for protocol compatibility, but on a successful page it must be `0` under exact release semantics.

## Branch / base

Continue on:
`review/telegram-mtproto-m4ah`

Base:
`50ae5b65ac0a243b006f352d1b585c8ae2f4f09c`

NO production execution is authorized.

## Preserve existing safety properties

Do not weaken:

- exact pinned SSH contract;
- fresh temp known_hosts;
- max 3 retries only before remote start;
- auth/remote-started failures do not SSH-retry;
- Stage 0 production guards;
- account/selection cardinality guards;
- session/reference structural checks;
- connect <= 1;
- is_user_authorized <= 1;
- one `iter_messages(... limit=100, reverse=False)`;
- consume <= 100 yielded messages;
- exact release `_history_entry_from_message`;
- no application `fetch_history()`;
- no materialization;
- no DB writes;
- no login/discovery/write RPC;
- disconnect in finally;
- strict output allowlist;
- no raw child stdout/stderr exposure;
- no IDs/message data/session/reference/credentials.

## Required focused tests

Add/adjust explicit tests for:

1. conversion exception at first item emits ordinal 1;
2. conversion exception at item N emits ordinal N;
3. iterator exception before first item emits ordinal 0;
4. iterator exception after N yielded items emits ordinal N+1 bounded to 100;
5. `is_user_authorized()` exception is STAGE_2_AUTHORIZED, never STAGE_3_ITERATION;
6. `connect()` exception is STAGE_2_CONNECT;
7. authorized=false is STAGE_2_AUTHORIZED + AuthorizationFalse;
8. `_history_entry_from_message() is None` stops immediately as STAGE_3_CONVERSION / InvalidHistoryEntry;
9. None conversion cannot produce FIRST_PAGE_PASS=true;
10. successful page has ENTRIES_NONE=0;
11. successful page still reports aggregate counts only;
12. ordinal parser bounds remain 0..100;
13. all existing M4AH1 safety tests remain passing.

Prefer executable behavioral tests over only string-presence assertions for the stage transitions above.

Run:
- focused pytest;
- Ruff changed Python files;
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
`TELEGRAM_MTPROTO_M4AH1R_REVIEW_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
