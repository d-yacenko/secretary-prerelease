# Current task — Telegram MTProto M4AG2: one approved live history-stage probe

## Status

M4AG1R corrective history-stage probe is REVIEW ACCEPTED for exactly one live diagnostic execution.

Approved branch:
`review/telegram-mtproto-m4ag`

Approved exact SHA:
`b9b6cb6e3444d78ae7bb438eedb30e30fc83b3d1`

Parent:
`7f592deee20b92a3ed5a4e47ae11aec052a09200`

Reported local verification:
- focused tests: 32 passed;
- Ruff: PASS;
- git diff --check: PASS.

Architect review confirmed:
- origin review branch resolves exactly to approved SHA;
- Stage 0 fails closed on release/ref/worktree/container/DB/Alembic mismatch;
- no provider probe starts before Stage 0/cardinality/structural gates;
- strict pinned SSH transport is reused;
- pre-remote transport retry remains bounded to 3;
- auth failure and remote-started failure do not retry;
- child output is locally strict-allowlisted before user-visible emission;
- malformed/unknown/duplicate/secret-shaped output fails closed;
- raw child stderr is not user-visible;
- raw exception output is class-name only;
- exactly one connect, one authorization check, and one `iter_messages(... limit=1, reverse=False)` are present in the probe path;
- no login, discovery, write RPC, application `fetch_history()`, DB write, or materialization occurs;
- disconnect executes in `finally`.

This acceptance applies only to this diagnostic execution. It is not approval to merge the harness to main or deploy it.

## Context

M4AE human probe repeatedly proved the current stored Telegram MTProto session can perform provider-backed folders/groups discovery without auth-invalid.

The original manual group sync returned HTTP 409 surfaced as:
`Telegram MTProto authorization is no longer valid`.

Exact production release `fetch_history()` broadly maps `ValueError` / `TypeError` to that same authorization-invalid error.

The purpose of M4AG2 is to expose the raw stage/class without application remapping.

## Authorization

Execute the approved script exactly once:

`ops/production/diagnose_mtproto_history_stage.py`

from exact SHA:
`b9b6cb6e3444d78ae7bb438eedb30e30fc83b3d1`.

Its built-in maximum 3 SSH attempts are allowed only for pre-remote transport establishment failures.

Do not manually run it a second time.

## Preparation

1. `git fetch origin`.
2. Use exact review SHA `b9b6cb6e3444d78ae7bb438eedb30e30fc83b3d1`.
3. Require clean local worktree.
4. Verify origin `review/telegram-mtproto-m4ag` equals exact SHA.
5. Verify `target.json` remains unchanged.
6. Do not amend/rebase/edit/cherry-pick before execution.

## Provider-call budget

Only if all local/production guards and structural checks pass:

1. `client.connect()` <= 1;
2. `client.is_user_authorized()` <= 1;
3. `client.iter_messages(input_peer, limit=1, reverse=False)` <= 1, consuming at most one item.

No automatic provider retry.

Always disconnect.

## Forbidden

Do NOT:
- login/re-login;
- submit code/password;
- discover folders/groups;
- retry manual Secretary Sync;
- Apply Scope;
- send/edit/delete messages;
- mark read;
- inspect or emit message contents/IDs/senders/timestamps;
- call application `fetch_history()`;
- materialize messages;
- decrypt/print session/reference outside in-process structural use;
- print IDs, phone, usernames/titles, access hashes, provider refs, credentials, tokens, IPs;
- write DB;
- mutate production;
- restart/recreate;
- edit production files/env;
- run Alembic writes;
- change main/production refs;
- change target.json or SSH trust state;
- change Bot API or MTProto AI flag.

## Required report

Return only sanitized results emitted by the reviewed harness.

### Transport
- attempt matrix;
- pin verified;
- host-key;
- SSH auth;
- remote execution.

### Stage 0
- whether production guards passed;
- account cardinality exactly one;
- manual-selected group cardinality exactly one.

### Stage 1
- `SESSION_DECRYPT_PASS`
- `STRING_SESSION_PARSE_PASS`
- `REFERENCE_DECRYPT_PASS`
- `REFERENCE_PARSE_PASS`
- `REFERENCE_PEER_MATCH_PASS`
- `TELEGRAM_CLIENT_CONSTRUCT_PASS`

### Stage 2
- `CONNECT_PASS`
- `IS_USER_AUTHORIZED`

### Stage 3
- `ITER_MESSAGES_STARTED`
- `ITER_MESSAGES_ONE_ITEM_OR_EMPTY_PASS`

If failure:
- `FAILURE_STAGE`
- `RAW_EXCEPTION_CLASS`

If emitted:
- `CONNECT_CALL_COUNT`
- `IS_USER_AUTHORIZED_CALL_COUNT`
- `ITER_MESSAGES_CALL_COUNT`
- `TELEGRAM_NETWORK_CALLS`

Also confirm:
- no login/write/discovery calls;
- no message data emitted;
- no session/reference printed;
- no production mutation;
- SSH trust and target unchanged.

## Interpretation

A. Structural session failure
=> stored-session serialization/persistence defect.

B. Reference parse/peer-match failure
=> selected-group provider-reference defect.

C. `IS_USER_AUTHORIZED=false`
=> the stored session failed a live authorization check at probe time.

D. Stage 3 raw `ValueError` / `TypeError`
=> direct evidence that the release `fetch_history()` can falsely remap this history-stage failure as authorization-invalid.

E. Stage 3 succeeds
=> stored session, selected peer reference, live authorization, and raw first history read all work; original 409 is then either transient or caused later in the application `fetch_history`/history processing path.

F. Other raw exception
=> classify from exact exception class before any further action.

Do not repair or retry during this task.

Final marker:
`TELEGRAM_MTPROTO_M4AG2_LIVE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
