# Current task — Telegram MTProto M4ARR: distinguish Linux client crash from launcher/session lifetime

## Status

Production backend/runtime remains healthy at:
`8091736337689b68b4510126e74d9e409397f696`

Production Alembic:
`0046`

Telegram MTProto backend is configured and the human authorization is already complete.

M4AR built the exact Linux client successfully from:
`8091736337689b68b4510126e74d9e409397f696`

Focused Flutter tests:
87 passed.

Release bundle build:
PASS.

However the fresh client window closed twice during live human observation:
- once shortly after first rendering;
- once after opening Account/Profile and scrolling.

The prior launch was performed from Executor-controlled shell/process context, so this may be either:
1. a real client/native crash; OR
2. the GUI child being terminated when the execution shell/session/timeout ended.

M4AR is therefore NOT accepted.

This task authorizes only **M4ARR — process-lifetime-safe detached launch plus sanitized crash diagnosis**.

No product-code fix is authorized yet.

## No backend / production changes

Do NOT:
- deploy backend;
- move production ref;
- change production DB/schema/env/services;
- run Alembic;
- change Telegram auth/session;
- select sync scope;
- run history sync;
- retire Bot API.

## Exact client source

Use exact:
`CLIENT_RELEASE_SHA=8091736337689b68b4510126e74d9e409397f696`

Do not build or launch a newer moving `main`.

Reuse the exact M4AR bundle only if its source SHA and bundle integrity are still provable. Otherwise rebuild from a clean detached exact-SHA worktree.

Do not change source files.

## Preserve user state

Do NOT:
- delete/overwrite the installed client;
- clear SharedPreferences;
- clear secure storage;
- remove/reissue bearer token;
- redo Telegram auth unless the fresh UI itself reports disconnected;
- inspect or print bearer/session/code/password values.

## Diagnose process ownership first

Before launch, determine:
- whether any old `personal_secretary` process is still alive;
- whether the previously launched fresh process is gone;
- whether the prior execution mechanism attached the GUI process to a shell/process group that would be reaped on command completion.

Do not kill unrelated user processes.

Record only PID/path/process-group/session metadata. Do not inspect process environment.

## Stable detached launch

Launch the exact release bundle so it is NOT owned by the short-lived Executor command session.

Preferred pattern:
- use a persistent user-session mechanism such as `systemd-run --user` when available; OR
- use a properly detached `nohup + setsid` wrapper with stdin closed.

Requirements:
- command invocation returns while GUI process continues;
- process has its own session/process group independent of the Executor shell;
- keep old installed client untouched;
- do not create a permanent desktop launcher yet;
- do not use `flutter run`.

The wrapper must record:
- child PID;
- eventual exit code/signal marker to a temporary non-secret status file.

Stdout/stderr handling:
- never print the full log blindly;
- redirect to a temporary file if needed for crash diagnosis;
- if the process exits, inspect only sanitized crash/backtrace/error lines;
- redact bearer tokens, URLs containing credentials, provider/account/user identifiers, Telegram phone/session/auth material, and secret-like values before reporting;
- delete the temporary diagnostic log after extracting sanitized crash evidence, unless Architect explicitly asks to preserve it.

## Survival check before human interaction

After detached launch:
1. verify the exact executable path;
2. verify the process is alive after at least 15 seconds;
3. verify it remains alive after at least 90 seconds with no human interaction;
4. verify the Executor shell command/session can end without killing the GUI process.

If the process dies before human interaction:
- capture exit code/signal;
- capture sanitized crash evidence;
- report M4ARR blocked;
- do NOT attempt a code fix.

If the process survives:
return the marker:
`TELEGRAM_MTPROTO_M4ARR_HUMAN_UI_CHECK_READY`

and STOP while leaving the fresh client running for the human.

## Human verification stage

The human will then:
- bring the fresh Secretary window to front;
- open Account/Profile;
- scroll to the area between Connections and Sync;
- confirm whether `Telegram MTProto` is visible;
- spend at least ~30 seconds on the Account screen / scroll normally.

No folder/group selection and no sync yet.

If the window closes during human interaction, the next Executor cycle may inspect the previously prepared status/diagnostic evidence without relaunching blindly.

## If a real crash is proven

Report:
- executable path;
- source SHA;
- uptime before exit;
- exit code or terminating signal;
- whether it happened without interaction or during Account scroll;
- sanitized top crash/backtrace frames / native library involved when available;
- whether a core dump exists (metadata only; do not upload or inspect sensitive memory contents without separate authorization);
- source area plausibly implicated, if determinable from symbols/logs.

Then STOP with:
`TELEGRAM_MTPROTO_M4ARR_REAL_CRASH_CONFIRMED`

Do not modify code in this task.

## If no crash and MTProto UI is visible

Report:
- detached mechanism used;
- process survived shell completion + 90s idle;
- human Account/Profile interaction survived;
- Telegram MTProto section visible;
- connected status visible yes/no;
- installed old client untouched;
- user storage untouched;
- no secrets inspected/printed;
- production backend untouched.

Final marker:
`TELEGRAM_MTPROTO_M4ARR_CLIENT_STABLE_READY`

Then STOP for Architect review before returning to M4A scope selection.

## If UI survives but MTProto section is still absent

Report exact UI fact and stop:
`TELEGRAM_MTPROTO_M4ARR_UI_MISMATCH_BLOCKED`

No code changes.

`CURRENT_TASK.md` is the source of active authorization.
