# Current task — Telegram MTProto M4AN2R: fresh Executor workspace + manual bridge completion fix

## Status

Executor now has a dedicated clean workspace:

`~/work/secretary-executor`

Canonical repository:
`https://github.com/d-yacenko/secretary-prerelease.git`

Do not use:
- `~/work/secretary`
- `~/work/secretary-prerelease`

for Executor implementation work.

The human sandbox shell remains the only proven production SSH credential context.

A first human-shell run of:
`ops/production/manual_mtproto_structural_probe.sh`

proved:
- canonical repo PASS;
- target pin PASS;
- remote HEAD PASS;
- remote production ref PASS;
- remote worktree clean;
- Compose config PASS;
- db/api/worker running PASS;
- DB health PASS.

However the script then emitted `MANUAL_M4AN2_END=true` without emitting:
- `ALEMBIC_0046_PASS`;
- child structural booleans;
- `M4AM_GENERIC_DB_STAGE_CAUSE`;
- `TELEGRAM_MTPROTO_M4AN2_STRUCTURAL_READY`.

Therefore the manual bridge has a completion-validation defect. That run is NOT a completed M4AN2 structural localization.

## Goal

From the clean Executor workspace, fix and review the manual bridge so it cannot report a successful end unless the full zero-provider structural localization completed or an explicit sanitized blocker/cause was emitted.

This task is implementation/review only.

Do NOT execute production SSH from the Executor subprocess.

## Required bootstrap

Work only from:
`~/work/secretary-executor`

Verify:
- origin is exact canonical repo;
- `git status --short` empty;
- fetch `origin/main`;
- current worktree is current `origin/main`.

Read:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/manual_mtproto_structural_probe.sh`
- the accepted M4AM diagnostic helper only as needed for semantic comparison.

## Required fix

Update `ops/production/manual_mtproto_structural_probe.sh` so:

1. The remote helper emits an explicit terminal marker only after one of these outcomes:
   - full structural localization completed;
   - explicit allowlisted outer blocker/cause completed.

2. The local wrapper captures/validates remote stdout and MUST NOT print `MANUAL_M4AN2_END=true` unless a valid remote terminal outcome is present.

3. If remote output ends prematurely after any stage, local wrapper returns a sanitized blocker such as:
   `MANUAL_M4AN2_BLOCKED=remote_incomplete`

4. Add safe stage-localization around the Alembic check so the next human run can distinguish:
   - Alembic check started;
   - Alembic PASS/FAIL;
   - child start;
   - child terminal result;
without printing secrets, SQL credentials, IDs, raw stderr, or tracebacks.

5. Keep the remote execution strictly zero-provider:
   - no TelegramClient construction;
   - no Telegram connect;
   - no `is_user_authorized`;
   - no `iter_messages`;
   - no application `fetch_history`;
   - no Sync/login/discovery;
   - no DB writes/materialization.

6. Keep production immutable:
   - no service restart/recreate;
   - no migration write;
   - no ref change;
   - no env/file mutation.

7. Do not weaken host-key pinning or public-key-only auth in the human bridge.

## Tests/review

Run local-only checks:
- `bash -n ops/production/manual_mtproto_structural_probe.sh`;
- focused shell/unit checks sufficient to prove:
  - premature remote EOF does not yield `MANUAL_M4AN2_END=true`;
  - valid full terminal marker does;
  - explicit outer failure is surfaced;
  - unknown/unsafe child output fails closed;
  - no Telegram/provider call path exists in the script.

Do not connect to production during these tests.

## Deliverable

Commit/push the fix to canonical main only if local review/checks PASS.

Update `PROJECT_STATE.md` with the factual bridge-fix result.

Do not execute the live probe.

Report:
- commit SHA;
- changed files;
- local checks;
- confirmation production SSH = 0;
- confirmation Telegram/provider calls = 0;
- confirmation production mutation = 0.

Final marker:
`TELEGRAM_MTPROTO_M4AN2R_BRIDGE_READY`

Then STOP.

The next human step will be one manual execution of the corrected bridge from the working human sandbox shell.
