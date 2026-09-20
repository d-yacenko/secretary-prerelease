# Current task — Telegram MTProto M4AR2: reconstruct one-shot Sync outcome read-only

## Status

The single M4AR1 human Sync click was used after deploying:

`b7fbdc71584cfde042a998fbfefb06015175a205`

The user navigated away from the Account screen before observing the result and then returned.

The Flutter Account widget keeps the latest Sync summary only in local in-memory `_lastSync` state. Navigating away disposes that state, so no counters are expected after returning.

Do NOT perform a second Sync.

## Goal

Reconstruct whether the one-shot Sync advanced persistent Telegram history state, using the already-reviewed zero-provider human-shell structural probe.

No Telegram/provider calls.
No DB writes.
No production mutation.

## Authorization

BREAK-GLASS READ-ONLY human-shell SSH is explicitly authorized for exactly one run of:

`ops/production/manual_mtproto_structural_probe.sh`

against expected production release:

`b7fbdc71584cfde042a998fbfefb06015175a205`

This is HUMAN SHELL ONLY.

Executor subprocess SSH is not authorized.

## Exact command

From the proven human sandbox shell:

```bash
cd ~/work/secretary-prerelease
git fetch origin
git checkout --detach origin/main
git rev-parse HEAD
bash ops/production/manual_mtproto_structural_probe.sh b7fbdc71584cfde042a998fbfefb06015175a205
```

The local checkout may be current `origin/main`; the probe itself must require production HEAD/ref exact release SHA above.

## Interpretation

The important persisted fields are:

- `INITIAL_STATE`
- `HISTORY_COMPLETE_BEFORE`
- `BACKFILL_CURSOR_PRESENT_BEFORE`

Known pre-Sync state was:

- `INITIAL_STATE=true`
- `HISTORY_COMPLETE_BEFORE=false`
- `BACKFILL_CURSOR_PRESENT_BEFORE=false`

Earlier provider evidence proved the selected group has history. Therefore:

- if `INITIAL_STATE=false`, the one-shot Sync advanced persistent history state;
- if `INITIAL_STATE=true`, do not retry; report result and STOP for further read-only diagnosis.

Also require:
- `TELEGRAM_NETWORK_CALLS=0`
- `FAILURE_SUBSTAGE=NONE`
- production/runtime guards PASS.

## Strictly forbidden

Do NOT:
- click Sync again;
- run the two-page provider probe;
- connect to Telegram;
- construct TelegramClient;
- login/re-login;
- Apply Scope;
- change group/folder selection;
- write DB;
- materialize/upsert;
- restart/recreate services;
- run migrations;
- change production files/env/refs;
- enable MTProto AI;
- change Bot API.

## Required report

Paste the complete sanitized probe output back to the Architect.

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
