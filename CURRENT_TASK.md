# Current task — Telegram MTProto M4ARR2: persistent human-session client launch

## Status

Production backend/runtime remains healthy at:
`8091736337689b68b4510126e74d9e409397f696`

Production Alembic:
`0046`

M4AR exact-SHA Linux client build:
PASS.

M4ARR established that the fresh Flutter client is not proven to crash:
- fresh client stays alive while Executor shell/session remains active;
- `systemd-run --user` is unavailable;
- `setsid + nohup` children are reaped when the Executor sandbox ends;
- a control detached `sleep` is terminated the same way;
- bundle logs contain no crash evidence.

Therefore the window closures are an Executor-sandbox lifetime limitation, not a confirmed Flutter crash.

Live human evidence now shows the fresh client DOES expose the MTProto controls, but the user cannot complete Telegram code entry before the Executor sandbox terminates the process. At least 2 minutes of uninterrupted human interaction is required.

Important correction: any earlier Executor claim that human MTProto authorization was already complete must NOT be treated as authoritative until the persistent client itself reaches and reports connected state. Current human evidence shows authorization is still in progress.

This task authorizes only **M4ARR2 — make the exact release bundle available in a stable user-owned preview location and hand off launch to the human's normal desktop session**.

No code change, backend deploy, schema change, production ref move, production env mutation, scope selection, or sync is authorized.

## Exact client source

Use only:
`CLIENT_RELEASE_SHA=8091736337689b68b4510126e74d9e409397f696`

Reuse the already-built exact-SHA release bundle only if its provenance is still verified. Otherwise rebuild from a clean detached worktree at that SHA.

## Stable preview location

Copy the complete release bundle, without altering its contents, to a stable user-owned preview path outside the Executor temp sandbox.

Preferred path:
`$HOME/.local/share/personal-secretary-preview/8091736337689b68b4510126e74d9e409397f696/bundle/`

Requirements:
- do not overwrite/remove the user's existing installed Secretary client;
- do not alter existing desktop launcher;
- do not clear SharedPreferences;
- do not clear secure storage;
- do not remove/reissue bearer tokens;
- do not inspect secrets;
- preserve executable permissions and bundle layout;
- verify the copied executable and required bundle libraries/assets exist;
- record a non-secret integrity check (for example executable SHA256) internally for source/copy comparison, but do not expose secret data.

## Human launch handoff

Do NOT launch the GUI from the Executor sandbox.

Instead, after preparing the stable preview bundle, return exactly one safe command for the human to run in their own normal terminal/session, for example:

`"$HOME/.local/share/personal-secretary-preview/8091736337689b68b4510126e74d9e409397f696/bundle/personal_secretary"`

The human terminal/session must remain open while using the app. The client may run for as long as needed.

Do not ask the human to run the command with sudo.

Do not include bearer tokens, API URLs with credentials, Telegram phone/code/password, or environment secrets in the command line.

## Human UI goal

After the human launches the preview client:

1. Open Account/Profile.
2. Confirm separate `Telegram MTProto` section is visible.
3. If disconnected:
   - human enters phone in UI;
   - human requests code;
   - human enters Telegram code in UI;
   - if prompted, human enters 2FA password in the obscured UI field.
4. Wait until the UI reports connected.

The human must have at least 2 minutes; preferably leave the app open indefinitely until they explicitly close it.

No scope selection or sync yet.

## Executor stop point

After preparing the stable preview bundle and returning the launch command, STOP.

Return:
- exact source SHA;
- stable preview bundle path;
- bundle copy/provenance verification PASS;
- existing installed client untouched;
- user storage untouched;
- production untouched;
- one exact human launch command.

Final marker:
`TELEGRAM_MTPROTO_M4ARR2_HUMAN_LAUNCH_READY`

Then STOP.

## After human connected

The human will report back that the preview UI shows connected. Only then may Architect authorize continuation of M4A scope selection / first controlled sync.

`CURRENT_TASK.md` is the source of active authorization.
