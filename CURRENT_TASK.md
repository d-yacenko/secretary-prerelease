# Current task — Telegram MTProto M4AM2R: run the unused single probe from a fresh clean worktree

## Status

M4AM2 did NOT start the live probe.

Local preflight stopped because the Executor's reused checkout:
- was on `review/yandex-sync-resilience-a`;
- had numerous untracked `.tmp_*` files;
- did not yet have the approved review branch resolved as a local remote ref.

No SSH, production, DB, Telegram, or provider operation occurred.

Therefore the exactly-one live probe authorization remains UNUSED.

Architect rechecked GitHub-side refs:
- `refs/heads/review/telegram-mtproto-m4am = 48816aedd639268770b2fb67caa22e048ce03493`
- `refs/heads/production = 23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Do NOT delete or clean unknown files from the reused checkout.
Do NOT switch that dirty checkout.

Use a fresh detached Git worktree for the diagnostic.

## Approved diagnostic

Exact SHA:
`48816aedd639268770b2fb67caa22e048ce03493`

Expected production runtime/ref:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

## Local-only preparation authorization

From the existing repository, local-only Git operations are authorized:

1. fetch only the required refs;
2. create one fresh temporary detached worktree at the exact diagnostic SHA;
3. run all diagnostic preflight and the one probe from that worktree.

Do not modify/delete/stash/clean files in the reused original worktree.

Preferred commands:

`git fetch origin refs/heads/main:refs/remotes/origin/main refs/heads/production:refs/remotes/origin/production refs/heads/review/telegram-mtproto-m4am:refs/remotes/origin/review/telegram-mtproto-m4am`

Verify exact refs before worktree creation.

Create a unique temporary worktree outside the existing checkout, for example:

`probe_dir="$(mktemp -d)"`
`git worktree add --detach "$probe_dir" 48816aedd639268770b2fb67caa22e048ce03493`

Then enter that worktree and require:
- HEAD exact approved SHA;
- worktree clean;
- `origin/review/telegram-mtproto-m4am` exact approved SHA;
- `origin/production` exact production SHA;
- target.json unchanged.

Do not create commits, branches, stashes, or ref updates.

## Single authorized execution

Only after all fresh-worktree guards PASS, run exactly once:

`python3 ops/production/diagnose_mtproto_history_two_page.py`

The previous blocked attempt does NOT count as the live execution because the script was not run.

Built-in max 3 SSH attempts remain allowed only before remote execution begins.
After remote begin: no retry and no second execution.

## Provider and safety contract

Unchanged from M4AM2:

- fresh TelegramClient per required page;
- <=2 connect;
- <=2 is_user_authorized;
- <=2 iter_messages;
- <=200 messages;
- <=6 bounded provider-operation calls;
- exact conversion helper;
- no DB writes/materialization/application fetch_history;
- no login/discovery/write RPC;
- no content/IDs/session/reference output;
- no production mutation.

## Forbidden

Do NOT:
- run `git clean` in the reused checkout;
- delete the existing `.tmp_*` files;
- switch/reset the reused dirty branch;
- run the probe from the reused dirty checkout;
- run the probe more than once;
- retry Secretary Sync;
- login/re-login;
- Apply Scope;
- mutate DB/production;
- change refs;
- edit env/files;
- restart services;
- run migrations;
- enable AI;
- change Bot API.

## Required report

First report fresh-worktree preparation:
- required refs fetched;
- approved review ref exact;
- production ref exact;
- detached worktree HEAD exact;
- new worktree clean;
- original reused checkout left untouched.

Then return the same sanitized M4AM2 transport/structural/page/failure fields.

Also confirm:
- execution count exactly 1;
- no second run;
- no DB writes/materialization;
- no login/discovery/write RPC;
- production unchanged.

Final marker:
`TELEGRAM_MTPROTO_M4AM2R_LIVE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
