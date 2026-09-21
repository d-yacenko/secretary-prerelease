# Current task — Telegram MTProto M4AT2R: one corrected human-shell visibility-state probe

## Status

M4AT1R corrective is complete at canonical main commit:

`287b402075528a7094da34c67c9a7e26882444e9`

The prior M4AT2 live run stopped at a false-negative Alembic guard before any application-state query and made no Telegram/provider calls or production mutations.

The corrected visibility probe now uses the accepted production DB Alembic contract:
- `PGPASSWORD="$POSTGRES_PASSWORD"`;
- host `127.0.0.1`;
- user `${POSTGRES_USER:-secretary}`;
- database `${POSTGRES_DB:-secretary}`;
- exact revision `0046`;
- isolated stdin;
- no credential/stderr output.

Local review:
- 12 focused tests PASS;
- `bash -n` PASS;
- bundled helper compile PASS;
- Ruff PASS;
- diff-check PASS;
- production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Production runtime/ref remains:

`b7fbdc71584cfde042a998fbfefb06015175a205`

## Authorization

Authorize exactly ONE new manual live execution of the corrected visibility-state probe from the proven human sandbox shell.

BREAK-GLASS READ-ONLY human-shell SSH is explicitly authorized for this one run.

This authorization is HUMAN-SHELL ONLY.

Executor subprocess SSH is not authorized.

## Exact human command

```bash
cd ~/work/secretary-prerelease
git fetch origin
git checkout --detach origin/main
git rev-parse HEAD
bash ops/production/manual_mtproto_visibility_state_probe.sh
```

The probe takes NO arguments.

The local checkout may be current `origin/main`; the probe itself pins production runtime/ref exact:
`b7fbdc71584cfde042a998fbfefb06015175a205`

## One-shot semantics

Run exactly once under this renewed authorization.

If remote execution starts and any stage fails:
- do not retry;
- paste the complete sanitized output;
- STOP.

## Allowed read-only work

The corrected probe may:
- verify target/pin/ref/worktree/services/DB/Alembic;
- read exactly one MTProto account;
- read exactly one `manual_selected=true` selection;
- read `MANUAL_SELECTED`, `SCOPE_ACTIVE`, `HISTORY_COMPLETE`, and backfill-cursor presence;
- count exact imported MTProto objects for that account+peer;
- count exact objects passing the canonical active-visibility predicate.

## Strictly forbidden

Do NOT:
- construct TelegramClient;
- connect to Telegram or make provider calls;
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

## Required report

Paste the complete sanitized output back to the Architect.

Important fields:
- `MANUAL_SELECTED`
- `SCOPE_ACTIVE`
- `HISTORY_COMPLETE`
- `BACKFILL_CURSOR_PRESENT`
- `IMPORTED_OBJECT_COUNT`
- `ACTIVE_VISIBLE_OBJECT_COUNT`
- `TELEGRAM_NETWORK_CALLS=0`
- terminal marker.

Interpretation:
- imported > 0 + scope_active=false => import succeeded; Inbox invisibility is expected until separately authorized scope activation;
- imported > 0 + scope_active=true + active visible > 0 => proceed to human Inbox verification;
- imported == 0 => STOP for read-only diagnosis.

Final marker after reporting:
`TELEGRAM_MTPROTO_M4AT2R_VISIBILITY_PROBE_COMPLETE`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
