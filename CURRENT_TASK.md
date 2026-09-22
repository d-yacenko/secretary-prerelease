# Current task — Capture exit status of completed Telegram rehearsal attempt

## Status

The single authorized invocation:

`python3 ops/production/telegram_production_rehearsal_remote.py --run-id tgprod0922a`

has already been attempted.

Observed stdout was completely empty.

This is NOT a PASS and the rehearsal must NOT be repeated.

## Authorized next action

Capture only the exit status of the immediately preceding shell command, with no network/process retry:

```bash
printf 'REHEARSAL_WRAPPER_EXIT=%s\n' "$?"
```

This must be run before any other shell command, otherwise `$?` no longer refers to the rehearsal wrapper.

## Interpretation

- exit 0 with empty stdout would violate the reviewed wrapper protocol and require local code diagnosis before any further runtime action;
- exit nonzero with empty stdout strongly indicates the outer SSH/remote-command subprocess failed before remote stdout, because local/remote fail-closed branches otherwise emit sanitized public markers.

## Hard prohibition

Do NOT:
- rerun the rehearsal;
- run ad-hoc SSH;
- inspect hidden SSH stderr by bypassing the wrapper;
- deploy/restart/recreate services;
- change AI flags/env;
- clean synthetic rows.

Return only the captured exit-status line.

`CURRENT_TASK.md` remains the source of active authorization.
