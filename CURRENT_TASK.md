# Current task — Telegram MTProto M4AH2: one approved live first-page conversion probe

## Status

M4AH1R corrective first-page history probe is REVIEW ACCEPTED for exactly one live diagnostic execution.

Approved branch:
`review/telegram-mtproto-m4ah`

Approved exact SHA:
`0e512795c2e389f1e84e7682457395b3daee7bd0`

Parent:
`50ae5b65ac0a243b006f352d1b585c8ae2f4f09c`

Reported verification:
- focused pytest: 23 passed;
- Ruff: PASS;
- git diff --check: PASS;
- worktree clean.

Architect review confirmed:
- origin review branch resolves exactly to approved SHA;
- reviewed pinned/fail-closed SSH transport is reused;
- production guards/cardinality/structural checks precede provider calls;
- connect/auth/iteration/conversion failure stages are explicitly separated;
- all failure paths carry sanitized MESSAGE_ORDINAL;
- raw iterator failure ordinal is 0 before first item or next attempted position after yielded items, bounded to 100;
- conversion failure ordinal is the current yielded position;
- exact release `_history_entry_from_message(message)` is used;
- `entry is None` stops immediately as STAGE_3_CONVERSION / InvalidHistoryEntry;
- a failed page cannot emit FIRST_PAGE_PASS;
- successful helper output uses ENTRIES_NONE=0;
- no application `fetch_history()`, materialization, DB write, login/discovery/write RPC occurs;
- output remains aggregate/sanitized only;
- disconnect is in finally;
- remote-started diagnostic does not SSH-retry.

Non-blocking review debt:
- the local protocol parser would accept a synthetic externally supplied success payload with `ENTRIES_NONE>0`, although the exact approved helper itself cannot emit that on success. Do not modify before this authorized run.

This acceptance applies only to this diagnostic execution. It is not approval to merge or deploy the diagnostic harness.

## Context

M4AG2 proved:
- session decrypt/StringSession parse PASS;
- selected provider reference decrypt/parse/peer-match PASS;
- TelegramClient construct PASS;
- connect PASS;
- live authorization true;
- one raw `iter_messages(... limit=1, reverse=False)` PASS.

Production release `8091736337689b68b4510126e74d9e409397f696` uses first-page size 100 and calls `_history_entry_from_message()` for every yielded message. Broad `ValueError`/`TypeError` in `fetch_history()` is currently remapped to authorization-invalid.

M4AH2 tests the complete first page without that remapping.

## Authorization

Execute exactly once:

`ops/production/diagnose_mtproto_history_page.py`

from exact SHA:
`0e512795c2e389f1e84e7682457395b3daee7bd0`.

Its built-in maximum 3 SSH attempts are allowed only for pre-remote transport establishment failure.

No manual second run.

## Preparation

1. `git fetch origin`.
2. Use exact review SHA `0e512795c2e389f1e84e7682457395b3daee7bd0`.
3. Require clean local worktree.
4. Verify `origin/review/telegram-mtproto-m4ah` equals exact SHA.
5. Verify `target.json` unchanged.
6. Do not edit/amend/rebase/cherry-pick before run.

## Provider budget

Only after all fail-closed guards pass:

- `client.connect()` <= 1;
- `client.is_user_authorized()` <= 1;
- one `client.iter_messages(input_peer, limit=100, reverse=False)`;
- consume <= 100 yielded items;
- one local `_history_entry_from_message()` conversion per yielded item until first failure.

No provider retry.

Always disconnect.

## Forbidden

Do NOT:
- login/re-login;
- submit code/password;
- discover folders/groups;
- press/retry Secretary Sync;
- Apply Scope;
- send/edit/delete/mark-read;
- call application `fetch_history()`;
- materialize messages;
- inspect or emit message IDs/text/body/sender/timestamps/titles/metadata;
- print session/reference, IDs, phone, access hash, credentials, tokens, IPs;
- write DB;
- mutate production;
- restart/recreate;
- edit production files/env;
- run Alembic writes;
- change main/production refs;
- change target.json or SSH trust state;
- change Bot API or MTProto AI flag.

## Required report

Return only sanitized reviewed-harness results.

### Transport
- attempt matrix;
- pin verified;
- host-key;
- SSH auth;
- remote execution.

### Guards / structure
- account exactly one;
- manual-selected group exactly one;
- session decrypt;
- StringSession parse;
- reference decrypt;
- reference parse;
- peer match;
- client construct.

### Live
- CONNECT_PASS;
- IS_USER_AUTHORIZED;
- call counts if emitted.

### First page

If success:
- `FIRST_PAGE_PASS`;
- `MESSAGES_SEEN`;
- `ENTRIES_CONVERTED`;
- `ENTRIES_NONE`;
- iterator/network call counts.

If failure:
- `FAILURE_STAGE`;
- `RAW_EXCEPTION_CLASS`;
- `MESSAGE_ORDINAL`;
- call counts if emitted.

Also confirm:
- no login/write/discovery calls;
- no message data emitted;
- no session/reference printed;
- no production mutation;
- SSH trust/target unchanged.

## Interpretation

A. `STAGE_3_CONVERSION` + `ValueError`/`TypeError`
=> direct evidence that release `fetch_history()` falsely maps a conversion failure to authorization-invalid.

B. `STAGE_3_CONVERSION` + `InvalidHistoryEntry`
=> exact first-page message conversion returns None; release would surface provider-unavailable, not auth-invalid. Original 409 then likely came from a different/transient attempt path.

C. `STAGE_3_ITERATION` + `ValueError`/`TypeError`
=> direct evidence that raw full-page history iteration can be falsely remapped to authorization-invalid.

D. first page PASS
=> session/reference/auth/raw 100-message page/conversion path works now; original 409 was transient or outside this first-page provider/conversion path. Next step should be application-path classification fix before any user retry.

E. other class/stage
=> classify exact sanitized evidence before further action.

Do not repair/retry during M4AH2.

Final marker:
`TELEGRAM_MTPROTO_M4AH2_LIVE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
