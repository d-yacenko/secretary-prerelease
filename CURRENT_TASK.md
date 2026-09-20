# Current task — Telegram MTProto M4AM2R2: run unused live probe from fresh canonical clone

## Status

The M4AM2 live diagnostic has still NOT been executed.

Two local preflight attempts stopped before script/SSH/provider execution.

Root cause is now identified:

Executor reused checkout origin:
`https://github.com/d-yacenko/secretary.git`

Canonical active repository:
`https://github.com/d-yacenko/secretary-prerelease.git`

Architect reverified canonical GitHub refs:

- `main` exists in `d-yacenko/secretary-prerelease`;
- `production = 23fa07df213d5a70a6dc1d3c8b32af39228107eb`;
- `review/telegram-mtproto-m4am = 48816aedd639268770b2fb67caa22e048ce03493`.

The old dirty checkout is NOT to be repaired or repointed during this task.

Exactly-one live probe authorization remains UNUSED.

## Goal

Create a fresh local clone of the canonical repository, verify exact refs, checkout exact approved diagnostic SHA detached, and execute the approved live probe exactly once.

## Canonical repository

Exact URL:

`https://github.com/d-yacenko/secretary-prerelease.git`

Do not substitute:
- `secretary.git`;
- `secretary_alpha.git`;
- another local remote;
- another mirror/fork.

## Approved SHAs

Diagnostic:
`48816aedd639268770b2fb67caa22e048ce03493`

Production:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

## Preserve old checkout

Do NOT modify the reused old checkout.

Specifically do not:
- change its origin URL;
- git clean;
- delete .tmp_*;
- reset;
- switch branches;
- stash;
- fetch canonical refs into it;
- create worktrees from it.

Treat it as unrelated local state for this task.

## Fresh canonical clone preparation

Use a unique temporary directory.

Example:

`root="$(mktemp -d)"`
`repo_dir="$root/secretary-prerelease"`

First verify the canonical URL advertises exact required refs:

`git ls-remote --heads https://github.com/d-yacenko/secretary-prerelease.git main production review/telegram-mtproto-m4am`

Require:

- production exactly:
  `23fa07df213d5a70a6dc1d3c8b32af39228107eb`
- review exactly:
  `48816aedd639268770b2fb67caa22e048ce03493`

If either is absent/mismatched: STOP.

Then clone canonical repo:

`git clone --no-checkout https://github.com/d-yacenko/secretary-prerelease.git "$repo_dir"`

Enter:

`cd "$repo_dir"`

Fetch exact refs if needed and verify:

- `origin` URL is exact canonical URL;
- `origin/production` exact production SHA;
- `origin/review/telegram-mtproto-m4am` exact diagnostic SHA.

Read current authorization from canonical main:

`git show origin/main:CURRENT_TASK.md`
`git show origin/main:PROJECT_STATE.md`
`git show origin/main:AGENTS.md`

Then checkout exact diagnostic SHA detached:

`git checkout --detach 48816aedd639268770b2fb67caa22e048ce03493`

Require:

- HEAD exact diagnostic SHA;
- worktree clean;
- target.json unchanged;
- origin URL exact canonical repo;
- origin/production exact production SHA;
- origin/review/telegram-mtproto-m4am exact diagnostic SHA.

No commit/branch/stash/ref mutation.

## Single authorized live execution

Only after all canonical-clone guards PASS:

`python3 ops/production/diagnose_mtproto_history_two_page.py`

Run exactly ONCE.

The two prior blocked preparations do not count because this diagnostic script was never executed.

Built-in max 3 SSH attempts are allowed only before remote begin.

After remote begin:
- no retry;
- no second run.

## Provider contract

Unchanged:

- fresh TelegramClient per required page;
- connect <=2;
- is_user_authorized <=2;
- iter_messages <=2;
- <=200 messages;
- <=6 bounded provider-operation calls;
- exact _history_entry_from_message conversion;
- no application fetch_history;
- no DB writes/materialization;
- no login/discovery/write RPC;
- no content/IDs/session/reference output.

## Strictly forbidden

Do NOT:
- change old checkout origin;
- use old checkout for probe;
- run probe twice;
- retry Secretary Sync;
- login/re-login;
- Apply Scope;
- mutate DB/production;
- change production refs;
- edit production files/env;
- restart/recreate services;
- run migrations;
- enable AI;
- change Bot API.

## Required report

### Canonical clone
- canonical URL ls-remote PASS/FAIL;
- advertised production SHA;
- advertised review SHA;
- fresh clone origin URL;
- detached HEAD;
- clean worktree;
- old checkout untouched.

### Probe
Return the approved sanitized M4AM2 fields:
- transport/guards;
- structural state;
- PAGE2_REQUIRED;
- page1/page2 pass/counts;
- totals;
- provider operation counts;
- FAILURE_STAGE / RAW_EXCEPTION_CLASS / MESSAGE_ORDINAL if any.

Confirm:
- script execution count exactly 1;
- no second run;
- no DB writes/materialization;
- no login/discovery/write RPC;
- no raw content/IDs/session/reference output;
- production unchanged.

Final marker:
`TELEGRAM_MTPROTO_M4AM2R2_LIVE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
