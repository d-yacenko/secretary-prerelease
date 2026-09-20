# Current task — Telegram MTProto M4AM1: build deterministic two-page history probe

## Status

Production runtime/ref:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

M4AK human Sync:
- exactly one click;
- HTTP/UI result: `Telegram provider is temporarily unavailable`;
- reopening settings restored normal connected/group discovery state;
- no retry/re-login/scope change.

M4AL1 sanitized logs:
- route seen;
- one HTTP 503;
- zero 409;
- no root exception class or traceback logged;
- no auth-invalid evidence;
- no provider calls made during log review.

Ordinary logs are insufficient.

This task authorizes ONLY implementation + tests + review-branch push for a read-only diagnostic harness.

NO live production probe is authorized yet.

## Goal

Build a deterministic read-only diagnostic that reproduces the current production history provider sequence closely enough to classify whether failure occurs on:

- first history page;
- second/backfill history page;
- iteration;
- exact message conversion;
- or not at all.

The diagnostic must not materialize objects or mutate DB state.

## Branch / base

Create:

`review/telegram-mtproto-m4am`

from current `origin/main`.

Do not modify production.

## Production semantics to reproduce

Use exact release behavior from:

- `TelegramMtprotoHistoryService._sync_selection`
- `TelethonMtprotoTransport.fetch_history`
- `_history_entry_from_message`
- `_next_backfill_state`

Key facts:

- page size = 100;
- max messages per manual sync run = 200;
- initial sync may fetch first page:
  `reverse=False, limit=100`
- if current history state requires more backfill, it may fetch second page:
  `reverse=False, max_message_id=<oldest first-page message id>, limit<=100`
- production transport creates a fresh `TelegramClient(StringSession(session), ...)` per `fetch_history` call.

The probe must mirror that fresh-client-per-page behavior.

## Structural state handling

Read exactly one MTProto account and exactly one manual-selected group.

Read current selection history state without mutating it:
- `history_latest_message_id`
- `history_backfill_before_message_id`
- `history_cutoff_at`
- `history_complete`

Do not print raw IDs or timestamps.

Emit only booleans / bounded aggregate indicators such as:
- `INITIAL_STATE=true|false`
- `HISTORY_COMPLETE_BEFORE=true|false`
- `BACKFILL_CURSOR_PRESENT_BEFORE=true|false`

The probe should determine the provider requests that the current production state would perform.

## Provider behavior

For each page actually required by the reproduced production state:

1. decrypt stored session/reference;
2. build a fresh TelegramClient with StringSession;
3. connect once;
4. call is_user_authorized once;
5. call exactly one iter_messages for that page;
6. convert each yielded message with exact `_history_entry_from_message`;
7. stop at first failure;
8. disconnect in finally.

No retries.

Total maximum provider calls:
- max 2 connects;
- max 2 authorization checks;
- max 2 iter_messages creations;
- consume max 200 messages.

No discovery/login/write RPCs.

## Stage protocol

Use narrow explicit failure stages, minimum:

- `STAGE_1_IMPORTS`
- `STAGE_1_DB_SESSION`
- `STAGE_1_SESSION_DECRYPT`
- `STAGE_1_REFERENCE_DECRYPT`
- `STAGE_1_REFERENCE_PARSE`
- `STAGE_1_REFERENCE_PEER_MATCH`
- `STAGE_2_PAGE1_CONNECT`
- `STAGE_2_PAGE1_AUTHORIZED`
- `STAGE_3_PAGE1_ITERATION`
- `STAGE_3_PAGE1_CONVERSION`
- `STAGE_4_PAGE2_CONNECT`
- `STAGE_4_PAGE2_AUTHORIZED`
- `STAGE_5_PAGE2_ITERATION`
- `STAGE_5_PAGE2_CONVERSION`

If second page is not required by current production state, emit:
`PAGE2_REQUIRED=false`

If it is required:
`PAGE2_REQUIRED=true`

## Safe output

Allowed aggregate fields only:

- account/manual-selection cardinality booleans;
- session/reference decrypt/parse/peer-match booleans;
- initial/current-state booleans;
- page1/page2 required/pass booleans;
- per-page messages-seen and entries-converted counts (0..100);
- `ENTRIES_NONE=0` on successful conversion;
- stage;
- raw exception CLASS NAME only;
- message ordinal 0..100;
- provider-call counts;
- total network-call count <= 6.

Do NOT emit:
- message ids;
- peer/group ids;
- user ids;
- message text/body;
- sender ids;
- timestamps;
- session/reference;
- credentials;
- raw traceback;
- exception messages;
- request bodies.

Unknown exception class may be emitted only as class token if it matches safe identifier syntax; otherwise `OTHER`.

## Parent/child safety

Use the hardened M4AH design principles:

- strict pinned SSH;
- exact target.json;
- fail-closed parent allowlist;
- any child stderr => fail closed;
- nonzero child exit => fail closed;
- malformed/unknown output => fail closed;
- no raw stdout/stderr passthrough;
- remote end marker required;
- no retry after remote start.

The diagnostic implementation may reuse/copy reviewed M4AH helper patterns, but do not merge old diagnostic branch code into main.

## Exact production code use

Where practical, import exact production helpers:
- `_history_entry_from_message`
- `_input_peer_from_reference`
- `validate_provider_peer_reference`
- `_next_backfill_state`

If importing `_next_backfill_state` is undesirable due service dependencies, reproduce its logic exactly and test parity against the real helper locally.

Do not call application `fetch_history()` because that would remap raw exceptions and hide the class we are trying to observe.

## Required tests

At minimum:

1. embedded child compiles independently;
2. page size owned by child = 100;
3. max total messages = 200;
4. current selection state determines whether page2 is required;
5. initial sync first-page success can derive page2 cursor without emitting id;
6. page1 ValueError/TypeError classified at PAGE1 iteration/conversion stage;
7. page2 ValueError/TypeError classified at PAGE2 iteration/conversion stage;
8. auth exceptions retain page-specific auth stage;
9. conversion None => invalid-entry style conversion failure;
10. per-page fresh client creation;
11. max one iter_messages per page;
12. max two pages;
13. disconnect per page;
14. no application fetch_history call;
15. no DB writes/session.add/flush/commit;
16. no materializer;
17. no login/discovery/write RPC;
18. no content/id leakage;
19. child stderr/nonzero/malformed fail closed;
20. success protocol counts consistent:
    - seen == converted
    - ENTRIES_NONE=0
    - each <=100
    - total <=200;
21. if PAGE2_REQUIRED=false, no page2 provider call is possible.

## Verification

Run:
- focused pytest for new diagnostic;
- relevant M4AH safety tests if reusable;
- Ruff changed Python;
- `git diff --check`.

## Forbidden

Do NOT:
- run this probe against production;
- SSH to production;
- retry Sync;
- re-login;
- Apply Scope;
- change selected groups/folders;
- mutate production;
- change schema/migrations;
- enable AI;
- change Bot API.

## Handoff

Commit and push only:
`review/telegram-mtproto-m4am`

Report:
- full SHA;
- test counts;
- Ruff;
- diff-check;
- exact stage model;
- proof of fresh client per page;
- proof of max provider-call budget;
- proof no writes/materialization/content leakage;
- remaining gaps.

Final marker:
`TELEGRAM_MTPROTO_M4AM1_REVIEW_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
