# Current task — PL1-R1 execute exact 0051 -> 0052 production rollout

Authorized base: `5043aef59908347073551ac7a3fde89cf31ee1f5`.
Authorized product release: `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.
Authorized rollback/runtime base: `666683134797948871266e84fd105f0ca0c43476`.
Authorized schema transition: `0051 -> 0052`.
Authorized harness: `ops/production/migrate_task_layout_0052.py` as present on authorized main.

PL1-R0 harness is accepted. This task is the explicit production migration/deploy authorization for the exact release above.

## Goal

Advance production from rollback release + Alembic 0051 to the exact PL1 single-world release + Alembic 0052 using only the dedicated fail-closed harness.

## Preflight before moving production ref

From a clean canonical local `main` equal to `origin/main`:

1. Verify `origin/production == 666683134797948871266e84fd105f0ca0c43476`.
2. Verify the authorized release and rollback SHAs resolve and rollback is an ancestor of release.
3. Verify compare rollback -> release is ahead-only and its only Alembic delta is additive `backend/alembic/versions/0052_task_layout_positions.py`.
4. Verify repository Alembic head is 0052.
5. Re-run the focused harness tests and `git diff --check` if the checkout has changed since R0; fail closed on any unexpected failure.
6. Do not alter production data or client state during preflight.

## Production ref gate

Immediately before running the migration harness:

- fast-forward `refs/heads/production` from the rollback SHA to the exact authorized release SHA only;
- verify `origin/production` is exactly the release SHA;
- do not point production at main/HOLD/harness commits.

## Execute only the canonical harness

Run exactly the dedicated migration entrypoint with:

- release SHA `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`;
- rollback SHA `666683134797948871266e84fd105f0ca0c43476`;
- from Alembic `0051`;
- to Alembic `0052`.

Do not use `deploy.py`, direct SSH, direct Compose, direct Alembic, or improvised commands as a substitute for the harness.

## Success acceptance

Treat rollout as successful only if the harness proves all of the following:

- migration deployment PASS;
- runtime checkout is the exact authorized release;
- Alembic is exactly 0052;
- API health passes;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- API and worker are the release runtime and were recreated as expected;
- both layout tables and required structure exist;
- no unexpected production application data mutation was performed by the rollout.

After success, verify `origin/production` remains the exact release SHA.

Do not call task-layout product endpoints merely to populate layout state during rollout verification.

## Failure / rollback handling

Obey the harness result exactly.

- If failure happens before any remote production mutation and runtime/DB are still rollback+0051, restore `refs/heads/production` to the rollback SHA and STOP.
- If the harness reports a completed safe automatic rollback and you independently verify runtime is rollback SHA + Alembic 0051 + health PASS, restore `refs/heads/production` to rollback SHA and STOP.
- If the harness reports `BREAK_GLASS_REQUIRED=true`, rollback blocked, unknown DB state, or cannot prove exact runtime/schema state: do **not** perform manual downgrade, delete rows, reset DB state, or improvise recovery. Leave the production ref unchanged from its current value, record the exact output/state, and STOP for Architect review.
- Never drop non-empty layout tables automatically.

## Explicitly out of scope

- No client bundle in this task.
- No installed-client replacement.
- No human visual gate.
- No manual creation/editing of Task, Person, or layout rows.
- No combined Tasks+People view.
- No later PL1 slice.

## Completion contract

Record in `PROJECT_STATE.md`:

- exact local main SHA used to launch the harness;
- production ref before/after;
- release and rollback SHAs;
- pre/post Alembic revisions;
- harness exit/result markers;
- health result;
- DB container/volume/`.env` preservation;
- whether API/worker were recreated;
- whether rollback path was unused, safely used, or blocked;
- confirmation that installed client and application data were not intentionally changed.

Then replace this file with `# Current task — HOLD`, commit/push ledger changes to `main`, and STOP.

Do not build the human-gate bundle or begin any further work without a new authorization.
