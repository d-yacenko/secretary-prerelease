# Current task — Telegram MTProto M4AH1: implement first-page history conversion probe

## Status

M4AG2 live probe passed completely on exact diagnostic SHA:
`b9b6cb6e3444d78ae7bb438eedb30e30fc83b3d1`.

Confirmed:
- stored session decrypts;
- `StringSession` parses;
- selected-group provider reference decrypts/parses;
- peer reference matches selected row;
- `TelegramClient` constructs;
- one `connect()` succeeds;
- one `is_user_authorized()` returns true;
- one raw `iter_messages(input_peer, limit=1, reverse=False)` completes successfully;
- no login/write/discovery/materialization/production mutation occurred.

Therefore:
- the stored MTProto session is not generally revoked;
- the selected-group provider reference is structurally valid;
- the first raw history read works.

Exact production release behavior:
- `TELEGRAM_MTPROTO_HISTORY_PAGE_SIZE = 100`;
- `fetch_history()` iterates up to 100 messages;
- each message is converted with `_history_entry_from_message(message)`;
- any `ValueError` or `TypeError` anywhere in that try block is broadly remapped to
  `TelegramMtprotoAuthorizationInvalidError("Telegram MTProto authorization is no longer valid")`.

This task authorizes only **implementation + local tests + review-branch push** for a first-page history conversion probe.

NO production execution is authorized yet.

## Goal

Build a deterministic diagnostic that reproduces the first production history page as closely as possible while preserving the raw failure stage/class.

It must distinguish:

1. failure during raw Telethon iteration;
2. failure during `_history_entry_from_message()` conversion;
3. successful conversion of the complete first page.

No DB writes or materialization.

## Branch / base

Create a new review branch from:
`b9b6cb6e3444d78ae7bb438eedb30e30fc83b3d1`

Preferred branch:
`review/telegram-mtproto-m4ah`

Do not modify main or production.

## Deliverable

Preferred script:
`ops/production/diagnose_mtproto_history_page.py`

Reuse the reviewed strict SSH transport / output allowlist patterns from:
- `diagnose_mtproto_auth_readonly.py`
- `diagnose_mtproto_history_stage.py`

Do not weaken trust or output-sanitization behavior.

## Remote stages

### Stage 0 — same fail-closed production guards

Require before provider calls:
- production HEAD exact `8091736337689b68b4510126e74d9e409397f696`;
- `origin/production` same exact SHA;
- production worktree clean;
- db/api/worker running;
- DB healthy;
- Alembic exact `0046`;
- exactly one MTProto account;
- exactly one manual-selected group.

No IDs emitted.

### Stage 1 — same structural checks

In memory only:
- decrypt session;
- parse `StringSession`;
- decrypt selected provider reference;
- parse exact release local reference;
- validate peer match;
- construct `TelegramClient`.

No network yet.

### Stage 2 — one authorization session

Only after all previous checks:
- `client.connect()` exactly once;
- `client.is_user_authorized()` exactly once;
- stop if false.

Always disconnect in `finally`.

### Stage 3 — full first-page raw iteration + exact release conversion

Use exact production page size:
`TELEGRAM_MTPROTO_HISTORY_PAGE_SIZE = 100`.

Run:
`client.iter_messages(input_peer, limit=100, reverse=False)`

Constraints:
- one iterator creation only;
- consume at most 100 items;
- no second provider read;
- no retry.

For EACH yielded message:
- increment an in-memory ordinal counter starting at 1;
- call exact release `_history_entry_from_message(message)`;
- do not inspect/emit message content, IDs, sender, timestamps, titles, or metadata;
- if conversion returns `None`, emit only a sanitized aggregate count at end or stop with a sanitized conversion-invalid marker, whichever best matches release semantics;
- do not call application `fetch_history()`;
- do not materialize anything.

If raw iteration raises:
- `FAILURE_STAGE=STAGE_3_ITERATION`
- `RAW_EXCEPTION_CLASS=<class only>`
- `MESSAGE_ORDINAL=<1..100 or 0 if before first item>`

If conversion raises:
- `FAILURE_STAGE=STAGE_3_CONVERSION`
- `RAW_EXCEPTION_CLASS=<class only>`
- `MESSAGE_ORDINAL=<1..100>`

If all up to 100 items convert:
- `FIRST_PAGE_PASS=true`
- `MESSAGES_SEEN=<0..100>`
- `ENTRIES_CONVERTED=<0..100>`
- `ENTRIES_NONE=<0..100>`

No message-level detail.

## Output allowlist

Strictly allow only:
- Stage 0/1/2 booleans already used in M4AG;
- `FIRST_PAGE_PASS`;
- `MESSAGES_SEEN`;
- `ENTRIES_CONVERTED`;
- `ENTRIES_NONE`;
- `MESSAGE_ORDINAL`;
- `FAILURE_STAGE`;
- `RAW_EXCEPTION_CLASS`;
- call counters;
- `TELEGRAM_NETWORK_CALLS`.

Validation:
- booleans exactly true/false;
- counters ASCII decimal only with exact upper bounds;
- ordinal 0..100;
- exception class regex only;
- hardcoded failure-stage enum;
- no duplicate keys;
- unexpected child stdout/stderr fails closed and is never echoed raw.

## Provider-call budget

At most:
- connect: 1;
- is_user_authorized: 1;
- iter_messages iterator: 1.

Do not count each yielded item as a separate provider-call budget unit; report explicit iterator call count separately.

No:
- login;
- folder/group discovery;
- send/edit/delete;
- mark-read;
- application `fetch_history()`;
- retry.

## Forbidden output

Never emit:
- account/user/Telegram/peer IDs;
- phone;
- usernames/titles;
- session/ref encrypted or decrypted;
- access hash;
- message ID/text/body;
- sender;
- timestamps;
- API id/hash;
- credential key;
- token;
- IP;
- raw logs;
- traceback;
- exception message.

## Required local tests

Add explicit tests for at least:

1. exact reviewed pinned SSH contract reused;
2. Stage 0 fail-closed before provider calls;
3. structural/cardinality gates preserved;
4. connect <=1;
5. authorization check <=1;
6. iterator creation <=1;
7. exact `limit=100, reverse=False`;
8. maximum 100 yielded items consumed;
9. exact release `_history_entry_from_message` is used;
10. application `fetch_history` is not used;
11. no materializer/DB-write path;
12. iteration exception reports only stage/class/ordinal;
13. conversion exception reports only stage/class/ordinal;
14. ordinal bounds 0..100 enforced;
15. success aggregates only counts, no message details;
16. child output strict allowlist/redaction;
17. child stderr never emitted raw;
18. no write/login/discovery methods;
19. disconnect on success and failure;
20. transport retries only pre-remote, max 3.

Run:
- focused pytest;
- Ruff changed Python files;
- `git diff --check`.

## Review handoff

After implementation:
- commit on `review/telegram-mtproto-m4ah`;
- push only that review branch;
- do NOT run against production;
- report full SHA;
- focused tests PASS/count;
- Ruff;
- diff-check;
- test-to-safety mapping;
- remaining gaps.

Final marker:
`TELEGRAM_MTPROTO_M4AH1_REVIEW_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
