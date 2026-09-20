# Current task — Telegram MTProto M4AI2: integrate accepted taxonomy fix and verify release candidate

## Status

M4AI1 is ARCHITECT ACCEPTED.

Accepted review branch:
`review/telegram-mtproto-m4ai`

Accepted exact implementation SHA:
`0cc9353e9263f97b461b4e0c0b3186dcc9f3d88b`

Parent at implementation time:
`1720f646312a95b49651814140909e52998d9f00`

Reviewed changes:
- `fetch_history()`: non-auth `ValueError/TypeError` -> provider-unavailable, genuine auth/session exceptions -> authorization-invalid;
- `AuthKeyError` included consistently with existing mutation/read semantics;
- `discover_groups()` equivalent correction;
- `discover_folders()` / `fetch_dialog_universe()` explicitly classify `AuthKeyError` as auth-invalid while other unexpected read errors remain provider-unavailable;
- shared API provider 503 detail changed to `Telegram provider is temporarily unavailable`;
- no schema/migration/login/write/scope/AI/Bot API changes.

Reported verification:
- M4AI focused: 10 passed;
- existing A2/A3/A4 transport regressions: 8 passed;
- A1 transport/migration checks: 3 passed;
- Ruff PASS;
- git diff --check PASS;
- Alembic head 0046.
- broader DB-dependent local tests were blocked only by unavailable local PostgreSQL host; production was not used.

This task authorizes integration + local/repository verification only.

NO production deploy or production runtime mutation is authorized.

## Goal

Integrate the accepted M4AI implementation into current main without altering its code, then identify one exact deployable candidate SHA and verify it locally as far as the available environment permits.

## Integration

1. `git fetch origin`.
2. Verify:
   - `origin/review/telegram-mtproto-m4ai == 0cc9353e9263f97b461b4e0c0b3186dcc9f3d88b`;
   - accepted implementation commit has no unexpected files beyond the reviewed diff.
3. Start from current `origin/main`.
4. Integrate the accepted implementation using the repository's normal non-destructive workflow.
5. Do not modify the accepted transport/API/test code during integration.
6. If integration is not clean, STOP and report conflict; do not resolve creatively.

## Candidate requirements

The resulting candidate must include exactly the accepted M4AI code plus current main documentation/state/task history.

No:
- migration 0047;
- schema changes;
- dependency changes;
- Telegram login changes;
- sync limit/page-size changes;
- scope changes;
- AI enablement;
- Bot API retirement;
- diagnostic review-branch harnesses unless they were already present on current main.

Report exact candidate SHA.

## Required verification

Run from integrated candidate:

### Static / focused
- M4AI focused tests;
- relevant non-DB MTProto transport tests from A1/A2/A3/A4;
- Ruff on changed Python files;
- `git diff --check`;
- Alembic heads check => exactly `0046`.

### Broader backend

Run the broadest practical Telegram MTProto test selection available locally.

If PostgreSQL is available through the repository's normal test setup, run DB-dependent suites too.

If DB-dependent tests fail only because no local PostgreSQL/test DB is reachable:
- classify as environment-only;
- include the exact test selection and failure category;
- do not use production DB as a substitute;
- do not start/change production.

### Candidate diff audit

Compare candidate against production release:
`8091736337689b68b4510126e74d9e409397f696`

Confirm functional runtime delta relevant to this phase is limited to:
- MTProto read-path taxonomy correction;
- provider-neutral 503 wording;
plus previously accepted main-only documentation/state metadata.

Explicitly report whether any other backend/client/infra functional files differ from production candidate. Do not assume none.

## Forbidden

Do NOT:
- deploy;
- SSH to production for mutation;
- change origin/production;
- restart/recreate services;
- run production migrations;
- use production DB for tests;
- retry Telegram Sync;
- login/re-login;
- change Telegram scope;
- change target.json or SSH trust;
- enable MTProto AI;
- retire/change Bot API.

## Handoff

Commit/push integration to main using the repository's normal workflow.

Report:
- integration/full candidate SHA;
- exact parent(s);
- origin/main SHA after push;
- test selections + pass/fail counts;
- any environment-only failures;
- Ruff;
- diff-check;
- Alembic head;
- candidate-vs-production functional diff summary;
- worktree clean;
- confirmation production untouched.

Final marker:
`TELEGRAM_MTPROTO_M4AI2_CANDIDATE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
