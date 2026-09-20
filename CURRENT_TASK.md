# Current task — Telegram MTProto M4AM2: one approved live two-page history probe

## Status

The deterministic two-page history diagnostic is ARCHITECT ACCEPTED for exactly one live execution.

Approved branch:
`review/telegram-mtproto-m4am`

Approved exact SHA:
`48816aedd639268770b2fb67caa22e048ce03493`

Production runtime/ref expected:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Current origin/production at task creation:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Reported/reviewed verification:
- focused tests: 51 passed;
- Ruff PASS;
- git diff --check PASS;
- strict pinned SSH;
- no DB writes/materialization/application fetch_history;
- fresh TelegramClient per history page;
- <=2 pages / <=200 messages / <=6 bounded provider-operation calls;
- sanitized page-specific + structural failure protocol.

This authorizes ONLY one diagnostic execution. It is not approval to merge/deploy the diagnostic harness.

## Goal

Determine whether the current production-like manual history sequence fails on:
- page 1;
- page 2/backfill;
- iteration;
- exact conversion;
- auth/connect;
- or currently passes completely.

Do not retry the Secretary Sync during this phase.

## Preparation

1. `git fetch origin`.
2. Read:
   - `origin/main:CURRENT_TASK.md`
   - `origin/main:PROJECT_STATE.md`
   - `origin/main:AGENTS.md`
3. Use exact diagnostic SHA:
   `48816aedd639268770b2fb67caa22e048ce03493`
4. Require clean local worktree.
5. Verify:
   - `origin/review/telegram-mtproto-m4am == 48816aedd639268770b2fb67caa22e048ce03493`;
   - `origin/production == 23fa07df213d5a70a6dc1d3c8b32af39228107eb`;
   - `ops/production/target.json` unchanged.
6. Do not edit/amend/rebase/cherry-pick before run.

## Single authorized execution

Run exactly once from the approved diagnostic SHA:

`python3 ops/production/diagnose_mtproto_history_two_page.py`

Built-in maximum 3 SSH attempts are allowed only before remote execution starts.

Once the remote begin marker has been observed:
- no retry;
- no second manual execution.

## Provider budget

The probe itself may perform only what its reviewed contract permits:

- page 1 only if current production state requires it;
- page 2 only if the reproduced production state requires it;
- fresh TelegramClient per page;
- connect <=2 total;
- is_user_authorized <=2 total;
- iter_messages <=2 total;
- consume <=200 total messages;
- exact _history_entry_from_message conversion only;
- total bounded provider-operation counter <=6.

Always disconnect each created client.

No discovery/login/write RPCs.

## Strictly forbidden

Do NOT:
- run the probe a second time;
- retry Secretary Sync;
- call application fetch_history();
- materialize/upsert objects;
- write DB;
- login/re-login;
- submit Telegram code/password;
- discover folders/groups;
- Apply Scope;
- change selections;
- send/edit/delete/mark-read;
- emit message/peer/user IDs;
- emit message text/body/sender/timestamps;
- emit session/reference/credentials;
- print raw traceback/stderr;
- restart/recreate production;
- edit production files/env;
- change refs;
- run migrations;
- enable MTProto AI;
- change Bot API.

## Required report

Return only sanitized harness facts.

### Transport/guards
- attempt count;
- pin;
- host-key;
- SSH auth;
- remote execution;
- production release/ref/worktree guards.

### Structural state
- account exactly one;
- manual-selected group exactly one;
- INITIAL_STATE;
- HISTORY_COMPLETE_BEFORE;
- BACKFILL_CURSOR_PRESENT_BEFORE;
- session decrypt/StringSession parse;
- reference decrypt/parse/peer-match.

### Page sequence
- PAGE2_REQUIRED;
- PAGE1_PASS if emitted;
- PAGE1_MESSAGES_SEEN;
- PAGE1_ENTRIES_CONVERTED;
- PAGE1_ENTRIES_NONE;
- PAGE2_PASS if emitted;
- PAGE2_MESSAGES_SEEN;
- PAGE2_ENTRIES_CONVERTED;
- PAGE2_ENTRIES_NONE;
- totals;
- call counts;
- TELEGRAM_NETWORK_CALLS.

### Failure
If failure occurs:
- FAILURE_STAGE;
- RAW_EXCEPTION_CLASS;
- MESSAGE_ORDINAL;
- TELEGRAM_NETWORK_CALLS;
- any safe fields already emitted before failure.

Also confirm:
- no DB writes/materialization;
- no content/IDs/session/reference emitted;
- no login/discovery/write RPC;
- production unchanged.

## Interpretation

A. STAGE_0 / STAGE_1 structural failure
=> harness/runtime/state issue; no Telegram auth conclusion.

B. PAGE1 connect/auth failure
=> current live session/connect issue at first history page.

C. PAGE1 iteration/conversion ValueError/TypeError
=> exact non-auth root class localized to first page.

D. PAGE2 connect/auth failure
=> first page currently works, second fresh-client page fails at connect/auth.

E. PAGE2 iteration/conversion ValueError/TypeError
=> exact root localized to second/backfill page; explains M4AK 503 path if reproducible.

F. PAGE1/PAGE2 conversion InvalidHistoryEntry
=> exact message conversion returned None on that page.

G. Both required pages PASS
=> current provider sequence works now; M4AK 503 was transient/intermittent. Do not retry Sync in this task.

H. PAGE2_REQUIRED=false and PAGE1 PASS
=> current production state does not require a second page; current required provider sequence passes. M4AK 503 was transient/intermittent or state changed only if separately proven.

Do not repair/retry during M4AM2.

Final marker:
`TELEGRAM_MTPROTO_M4AM2_LIVE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
