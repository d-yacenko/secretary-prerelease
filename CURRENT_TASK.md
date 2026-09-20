# Current task — Telegram MTProto M4AH3: one approved live first-page probe retry

## Status

M4AH2R2 corrective probe is REVIEW ACCEPTED for exactly one live diagnostic execution.

Approved branch:
`review/telegram-mtproto-m4ah`

Approved exact SHA:
`2b9b8d3d7f19f2174808ecdadfd4bddc148aa5e9`

Parent:
`162eb4cc7cd677bf8d9ef97df194ec0f514d60f0`

Reported verification:
- focused pytest: 32 passed;
- Ruff: PASS;
- git diff --check: PASS.

Architect review confirmed:
- origin review branch resolves exactly to approved SHA;
- nested API-container child now fails closed when returncode != 0 OR stderr is non-empty;
- child stdout/stderr are not forwarded on that failure path;
- only sanitized STAGE_1_RUNTIME / RuntimeError / ordinal 0 / network calls 0 are emitted;
- normal remote end marker is preserved;
- no SSH retry occurs after remote start;
- child owns PAGE_SIZE=100;
- import failures sanitize to STAGE_1_IMPORTS;
- DB session/query failures sanitize to STAGE_1_DB_SESSION;
- success protocol requires ENTRIES_NONE=0 and MESSAGES_SEEN == ENTRIES_CONVERTED;
- previous strict SSH/output/provider safety properties remain intact.

This acceptance authorizes only one diagnostic run. It is not approval to merge/deploy the harness.

## Context

Previous M4AH2:
- strict SSH transport PASS;
- remote helper started;
- inner API-container runtime failed before any provider calls;
- sanitized result STAGE_1_RUNTIME / RuntimeError;
- TELEGRAM_NETWORK_CALLS=0.

M4AG2 previously proved:
- stored session decrypt/StringSession/reference/peer match PASS;
- connect PASS;
- is_user_authorized == true;
- one raw iter_messages(limit=1, reverse=False) PASS.

M4AH3 must now determine whether the complete first production-like page (up to 100 messages + exact _history_entry_from_message conversion) passes or exposes a raw iteration/conversion exception.

## Authorization

Execute exactly once:

`ops/production/diagnose_mtproto_history_page.py`

from exact SHA:
`2b9b8d3d7f19f2174808ecdadfd4bddc148aa5e9`.

Built-in maximum 3 SSH attempts are allowed only for pre-remote transport establishment failures.

No manual second run.

## Preparation

1. `git fetch origin`.
2. Use exact SHA `2b9b8d3d7f19f2174808ecdadfd4bddc148aa5e9`.
3. Require clean local worktree.
4. Verify `origin/review/telegram-mtproto-m4ah` == exact SHA.
5. Verify `target.json` unchanged.
6. Do not edit/amend/rebase/cherry-pick before run.

Run with Python explicitly if executable bit is absent:

`python3 ops/production/diagnose_mtproto_history_page.py`

This is the single authorized execution.

## Provider-call budget

Only after all guards pass:

- client.connect() <= 1;
- client.is_user_authorized() <= 1;
- one iter_messages(input_peer, limit=100, reverse=False);
- consume <= 100 yielded messages;
- exact _history_entry_from_message() once per yielded item until first failure.

No provider retry.

Always disconnect.

## Forbidden

Do NOT:
- run the probe a second time;
- login/re-login;
- submit code/password;
- discover folders/groups;
- retry Secretary Sync;
- Apply Scope;
- send/edit/delete/mark-read;
- call application fetch_history();
- materialize messages;
- inspect/emit message IDs/text/body/sender/timestamps/titles/metadata;
- print session/reference or credentials;
- write DB;
- mutate production;
- restart/recreate;
- edit production files/env;
- run Alembic writes;
- change main/production refs;
- change target.json / SSH trust;
- change Bot API or MTProto AI flags.

## Required report

Return only sanitized harness output.

### Transport
- attempts;
- pin;
- host-key;
- SSH auth;
- remote execution.

### If runtime/bootstrap failure
- FAILURE_STAGE;
- RAW_EXCEPTION_CLASS;
- MESSAGE_ORDINAL;
- TELEGRAM_NETWORK_CALLS.

### If structural/live progress
- account cardinality;
- manual group cardinality;
- SESSION_DECRYPT_PASS;
- STRING_SESSION_PARSE_PASS;
- REFERENCE_DECRYPT_PASS;
- REFERENCE_PARSE_PASS;
- REFERENCE_PEER_MATCH_PASS;
- TELEGRAM_CLIENT_CONSTRUCT_PASS;
- CONNECT_PASS;
- IS_USER_AUTHORIZED;
- call counts if emitted.

### First page success
- FIRST_PAGE_PASS;
- MESSAGES_SEEN;
- ENTRIES_CONVERTED;
- ENTRIES_NONE;
- call counts.

### First page failure
- FAILURE_STAGE;
- RAW_EXCEPTION_CLASS;
- MESSAGE_ORDINAL;
- call counts.

Also confirm:
- no login/write/discovery;
- no message data emitted;
- no session/reference printed;
- no production mutation;
- SSH trust/target unchanged.

## Interpretation

A. STAGE_1_IMPORTS / STAGE_1_DB_SESSION
=> harness/runtime bootstrap issue; no Telegram conclusion.

B. STAGE_2_CONNECT / STAGE_2_AUTHORIZED
=> classify exact live session failure.

C. STAGE_3_ITERATION + ValueError/TypeError
=> direct evidence that release fetch_history() can falsely remap raw history iteration failure to authorization-invalid.

D. STAGE_3_CONVERSION + ValueError/TypeError
=> direct evidence that release fetch_history() can falsely remap conversion failure to authorization-invalid.

E. STAGE_3_CONVERSION + InvalidHistoryEntry
=> production path would classify provider-unavailable, not auth-invalid.

F. FIRST_PAGE_PASS=true
=> current session/reference/auth/full first page/conversion all work. Original 409 was transient or outside this first-page path. Next step is to fix broad auth-invalid error taxonomy and then perform a controlled application Sync retry after review/deploy.

G. STAGE_1_RUNTIME / OUTPUT_ALLOWLIST
=> harness problem; no provider conclusion unless call counters prove otherwise.

Do not repair/retry during M4AH3.

Final marker:
`TELEGRAM_MTPROTO_M4AH3_LIVE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
