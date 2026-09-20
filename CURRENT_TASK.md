# Current task — Telegram MTProto M4AK: one human-controlled manual Sync

## Status

M4AJR2 production deployment: SUCCESS.

Production runtime/ref:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Origin production ref:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Production health:
PASS

Alembic:
`0046`

Preserved:
- DB container/volume/data;
- .env;
- credential key;
- stored Telegram session;
- existing selected group/scope;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- Bot API state.

No Telegram login/history/manual Sync was performed during deploy.

## Goal

Perform exactly ONE human-controlled manual Sync of the already-selected Telegram group through the current Secretary UI, then STOP and report the result.

This task is a human validation step, not an automated retry loop.

## Preconditions

Before clicking Sync:

- use the current Secretary client already connected to the deployed backend;
- do NOT re-login;
- do NOT enter Telegram code/password;
- do NOT change selected groups;
- do NOT change folders;
- do NOT Apply Scope;
- do NOT revoke Telegram session;
- do NOT restart or redeploy production.

If the Telegram account/group controls do not load normally, STOP and report the visible UI state instead of attempting login or repair.

## Human action

Navigate to the existing Telegram MTProto account/group section.

Locate the already-selected manual group.

Press that group's:
`Синхронизировать`

Exactly ONCE.

Do not press Sync again, even if:
- no counters appear immediately;
- an error appears;
- the UI looks unchanged.

Do not click global/folder Apply Scope.

## Evidence to report

After the single Sync action, report exactly what the UI shows.

### If success

Report:
- whether an error banner/message appeared;
- any visible counters/results, including scanned/materialized/created/updated/unchanged/skipped if shown;
- whether history_complete or equivalent state is visible;
- whether the group remains selected;
- whether connected account identity remains visible.

### If failure

Report:
- exact user-visible error text;
- whether connected account identity remains visible;
- whether groups/folders still load after the failure;
- whether the selected group remains selected;
- whether any counters appeared before the error.

Do NOT retry.

## Interpretation

A. Sync succeeds
=> M4 activation path is operational after taxonomy fix. Next step is verification of imported objects/UI behavior and then close M4 activation.

B. HTTP/UI provider-unavailable style error
=> taxonomy fix is working; capture exact visible message and stop. Do not re-login.

C. Authorization-invalid appears again
=> stop immediately. This would now be meaningful evidence because the broad ValueError/TypeError remap has been removed.

D. No counters / generic Secretary connectivity error
=> stop and report exact UI state; do not infer Telegram auth failure.

## Strictly forbidden

Do NOT:
- retry Sync;
- re-login;
- enter Telegram auth code/password;
- Apply Scope;
- change group/folder selections;
- revoke/delete session;
- run diagnostic scripts;
- mutate production;
- enable MTProto AI;
- change Bot API.

## Final report

Return:
- one Sync click performed: yes/no;
- visible result/error;
- counters if any;
- account connected status;
- group selection state;
- whether folders/groups still load;
- confirmation no retry/re-login/scope change occurred.

Final marker:
`TELEGRAM_MTPROTO_M4AK_HUMAN_SYNC_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
