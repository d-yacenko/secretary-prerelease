# Current task — Telegram MTProto M4BE1R: correct post-deploy acceptance aggregate SQL

## Status

M4BE1 live read-only acceptance probe executed once and stopped safely.

Production evidence already confirmed:
- runtime/ref `c69d2353c19c4958e1fb60aac69466fcf6ac1482`;
- Alembic `0046`;
- account count 1;
- configured folder count 1;
- active scope count 28;
- manual-active count 0;
- folder-only active count 28;
- latest cursor present count 28;
- history complete count 28;
- backfill cursor present count 0;
- history cutoff present count 0;
- Telegram network calls 0;
- DB writes 0.

The probe then failed at the peer-object aggregate with:
`FAILURE_STAGE=STAGE_1_DB_SESSION`
`RAW_EXCEPTION_CLASS=ProgrammingError`

## Architect root-cause localization

In `ops/production/manual_mtproto_postdeploy_acceptance.py`, the peer-count query currently builds:

- one `Object.metadata_["peer_id"].as_string()` expression in SELECT;
- a second independently-created expression in GROUP BY.

With SQLAlchemy/PostgreSQL this can compile to two separate JSON path bind parameters, e.g. SELECT using `metadata_1` and GROUP BY using `metadata_2`. PostgreSQL can therefore reject the selected expression as not identical to the grouping expression.

The correction must construct the peer-id SQL expression exactly once and reuse the same expression object in both SELECT and GROUP BY.

## Goal

Make the smallest probe-only correction so the read-only object-count/AI aggregate section can execute on PostgreSQL.

Do not change Telegram product behavior.

## Required implementation

1. In the bundled child source, define one reusable peer-id SQL expression, for example:
   `peer_expr = Object.metadata_["peer_id"].as_string()`
2. Use that same expression object in both:
   - `select(peer_expr, func.count())`
   - `.group_by(peer_expr)`
3. Keep all existing account/object filters and folder-only >20 semantics unchanged.
4. Keep the probe read-only.
5. Do not add Telegram/provider imports or calls.
6. Do not add DB flush/commit/write behavior.
7. Preserve the pinned production release and Alembic guards.

## Required regression coverage

Add a focused regression that proves the PostgreSQL-compiled peer-count query reuses one JSON-path bind parameter rather than two independent peer-id bind parameters.

The test may construct the exact SQLAlchemy expression/query locally and compile it with the PostgreSQL dialect; no database connection is required.

Also retain all existing protocol/static tests.

## Optional narrow hardening

If needed while touching the aggregate block, exact inbound/outbound counts may use explicit equality checks for `direction == "inbound"` and `direction == "outbound"`. Do not broaden beyond this probe.

## Required local validation

Run:
- focused probe tests;
- helper compile;
- bundled helper compile;
- Bash syntax;
- Ruff on changed Python;
- `git diff --check`.

## Authorization

AUTHORIZED:
- local changes only to the M4BD1/M4BE1 acceptance probe and its tests;
- update `PROJECT_STATE.md`;
- commit and push to canonical `main`.

NOT AUTHORIZED:
- production SSH;
- live probe rerun;
- Telegram/provider calls;
- Sync;
- Apply Scope;
- reconciliation;
- production DB/file mutation;
- deploy/rollback/ref changes;
- MTProto AI changes;
- Bot API changes.

## Required report

Return:
- corrective commit SHA;
- files changed;
- exact SQL-expression correction;
- PostgreSQL compile regression result;
- complete focused test/compile/Ruff/diff-check results;
- production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_M4BE1R_PROBE_FIX_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
