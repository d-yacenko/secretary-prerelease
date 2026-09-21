# Current task — Telegram MTProto M4AT1R: fix/review visibility probe Alembic guard

## Status

M4AT2 one-shot human live visibility probe was consumed and stopped before any application-state query.

Observed:
- production repo/ref/worktree guards PASS;
- Compose/db/api/worker/DB health PASS;
- `ALEMBIC_0046_PASS=false`;
- `FAILURE_STAGE=STAGE_0_ALEMBIC`;
- `RAW_EXCEPTION_CLASS=RuntimeError`;
- `TELEGRAM_NETWORK_CALLS=0`.

This is a probe defect, not evidence of a production schema regression.

Root cause in:
`ops/production/manual_mtproto_visibility_state.py`

The current Alembic check runs:

`psql -At -c 'SELECT version_num FROM alembic_version'`

inside the DB container without the production DB credential/host contract.

The already accepted structural human-shell probe uses the correct read-only production pattern:

`PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "${POSTGRES_USER:-secretary}" -d "${POSTGRES_DB:-secretary}" -At -c "SELECT version_num FROM alembic_version"`

with stdin isolated from the streamed helper.

Production runtime/ref remains:
`b7fbdc71584cfde042a998fbfefb06015175a205`

Expected Alembic remains:
`0046`

## Goal

BUILD / REVIEW ONLY.

Correct the visibility-state probe's Alembic guard to use the same accepted production DB credential/host semantics as `manual_mtproto_structural_probe.sh`.

Do NOT run the live probe in this task.

## Executor workspace

Work only from:

`~/work/secretary-executor`

Canonical origin:
`https://github.com/d-yacenko/secretary-prerelease.git`

Do not use:
- `~/work/secretary`
- `~/work/secretary-prerelease`

for Executor implementation work.

## Required bootstrap

```bash
git fetch origin
git switch main
git pull --ff-only
git remote get-url origin
git rev-parse HEAD
git status --short
```

Require exact canonical origin, current `origin/main`, clean worktree.

Read:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/manual_mtproto_visibility_state_probe.sh`
- `ops/production/manual_mtproto_visibility_state.py`
- `ops/production/tests/test_manual_mtproto_visibility_state.py`
- accepted Alembic check in `ops/production/manual_mtproto_structural_probe.sh`.

## Required fix

Use the accepted production DB Alembic query semantics:
- inside the existing DB container;
- `PGPASSWORD="$POSTGRES_PASSWORD"`;
- host `127.0.0.1`;
- user `${POSTGRES_USER:-secretary}`;
- database `${POSTGRES_DB:-secretary}`;
- `SELECT version_num FROM alembic_version`;
- require exact stdout `0046`;
- stdin isolated so the command cannot consume streamed helper input;
- do not print credentials, command stderr, or connection strings.

Do not alter the actual visibility-state query semantics.

## Required regressions

Add/update local-only tests proving:

1. Alembic success transcript with exact `0046`.
2. Alembic wrong revision fails closed at `STAGE_0_ALEMBIC`.
3. Alembic command uses the production credential/host contract without exposing values.
4. Alembic exec stdin is isolated / cannot consume helper input.
5. Existing inactive-scope, active-scope, zero-object, EOF, unsafe-output, no-provider, and no-DB-write tests remain PASS.

Run:
- focused probe tests;
- `bash -n`;
- bundled helper compile;
- Ruff;
- diff-check.

No production SSH.
No Telegram/provider calls.
No production mutation.

## Deliverable

If PASS:
- commit/push canonical main;
- update `PROJECT_STATE.md`;
- do NOT run live probe.

Report:
- commit SHA;
- changed files;
- test counts/results;
- lint/diff-check;
- production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_M4AT1R_VISIBILITY_PROBE_FIX_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
