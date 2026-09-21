# Current task — Telegram MTProto M4AT2: one human-shell visibility-state probe

## Status

M4AT1 probe build/review is complete at canonical main commit:

`bee127cef18297e512dd94e5d2f4a5f8f1e164ea`

Reviewed artifacts:
- `ops/production/manual_mtproto_visibility_state_probe.sh`
- `ops/production/manual_mtproto_visibility_state.py`
- `ops/production/tests/test_manual_mtproto_visibility_state.py`

Local evidence:
- 9 focused tests PASS;
- inactive/active scope transcripts PASS;
- zero imported objects PASS;
- premature EOF / unsafe output fail-closed PASS;
- no provider-call path PASS;
- no DB write/flush/commit path PASS;
- `bash -n` PASS;
- bundled helper compile PASS;
- Ruff PASS;
- diff-check PASS;
- production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Production runtime/ref remains exact:

`b7fbdc71584cfde042a998fbfefb06015175a205`

## Authorization

Authorize exactly ONE manual live execution of the reviewed visibility-state probe from the proven human sandbox shell.

BREAK-GLASS READ-ONLY human-shell SSH is explicitly authorized for this one run.

This authorization is HUMAN-SHELL ONLY.

The Executor subprocess must NOT execute production SSH.

## Exact human command

From the canonical human-shell checkout:

```bash
cd ~/work/secretary-prerelease
git fetch origin
git checkout --detach origin/main
git rev-parse HEAD
bash ops/production/manual_mtproto_visibility_state_probe.sh
```

Important: the probe takes NO arguments.

Before running:
- `git rev-parse HEAD` must equal current `origin/main`;
- the probe itself pins production release `b7fbdc71584cfde042a998fbfefb06015175a205`.

## One-shot semantics

Run exactly once.

A local pre-SSH failure does not consume the live read-only run.

If remote execution starts and any stage fails:
- do not retry;
- paste the sanitized output;
- STOP.

## Allowed read-only work

The probe may:
- verify production target/pin/ref/worktree/services/DB/Alembic;
- read exactly one MTProto account;
- read exactly one `manual_selected=true` selection;
- read manual/scope/history booleans;
- count exact persisted MTProto objects for that account+peer;
- count exact objects passing canonical active visibility predicate.

## Required safe fields

Expected diagnostic fields include:
- `ACCOUNT_EXACTLY_ONE`
- `MANUAL_SELECTED_EXACTLY_ONE`
- `MANUAL_SELECTED`
- `SCOPE_ACTIVE`
- `HISTORY_COMPLETE`
- `BACKFILL_CURSOR_PRESENT`
- `IMPORTED_OBJECT_COUNT`
- `ACTIVE_VISIBLE_OBJECT_COUNT`
- `TELEGRAM_NETWORK_CALLS=0`
- failure stage/class if any;
- explicit terminal marker.

## Strictly forbidden

Do NOT:
- construct TelegramClient;
- connect to Telegram;
- make provider calls;
- click Sync;
- login/re-login;
- Apply Scope;
- change selections/folders;
- write/flush/commit DB;
- materialize/upsert;
- restart/recreate services;
- run migrations;
- change production files/env/refs;
- enable MTProto AI;
- change Bot API;
- print IDs/content/session/reference/credentials/raw stderr/tracebacks.

## Interpretation

- `IMPORTED_OBJECT_COUNT > 0` + `SCOPE_ACTIVE=false`:
  import is present and Inbox invisibility is expected because scope is inactive.

- `IMPORTED_OBJECT_COUNT > 0` + `SCOPE_ACTIVE=true` + `ACTIVE_VISIBLE_OBJECT_COUNT > 0`:
  proceed to human Inbox verification in a later task.

- `IMPORTED_OBJECT_COUNT == 0`:
  STOP for read-only diagnosis; do not Sync again.

## Required report

Paste the complete sanitized probe output back to the Architect.

Then STOP.

Final marker after reporting:
`TELEGRAM_MTPROTO_M4AT2_VISIBILITY_PROBE_COMPLETE`

`CURRENT_TASK.md` is the source of active authorization.
