# CURRENT_TASK

## Status

ACTIVE

## REL1D-R1 — exact REL1D production backend rollout

The user explicitly authorized the controlled REL1D rollout.

REL1D is ARCHITECT SOURCE-ACCEPTED.

This task is **only the production backend rollout stage**.

Do not build/install/replace the Linux client in this task. Client rollout is REL1D-R2 after R1 is reviewed successful. The existing user authorization covers R1 + R2 + the following human acceptance gate, but each stage remains separately bounded.

## Exact authorized release contract

```text
RELEASE_SHA=6693578d35c1ea1d6e25bf73768ca0cf6c07dac9
ROLLBACK_SHA=6f802d6959aca40758376a83d5bdfcbbd77fc537
EXPECTED_ALEMBIC=0054
```

- `RELEASE_SHA` is the exact REL1D source-accepted product release.
- Current `refs/heads/production` is expected to be exact `ROLLBACK_SHA`.
- Current production backend/runtime is expected to be exact `ROLLBACK_SHA`.
- Current production Alembic is expected to be `0054 / 0054`.
- Installed Linux client remains exact `ROLLBACK_SHA`.
- Current `main` is newer because it contains rollout-control/report-timestamp documentation; **do not substitute current main as the release SHA**.
- The accepted REL1D delta is schema-neutral. Do not run any migration harness or Alembic mutation.

## Mandatory bootstrap

Follow fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/deploy.py`
- files/tests directly required by this rollout.

Canonical repository only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Use only committed `ops/production/target.json` and the pinned host-key contract.

No target discovery. No alternative host/IP/path. No new SSH credentials. No private-key copying/requesting.

## Preflight before production ref mutation

From a clean canonical checkout with fresh `origin/main`:

1. Verify fresh `CURRENT_TASK.md` is this ACTIVE task.
2. Verify `origin/production == ROLLBACK_SHA`.
3. Verify `RELEASE_SHA` and `ROLLBACK_SHA` resolve exactly.
4. Verify rollback is an ancestor of release and rollback -> release is ahead-only.
5. Verify release repository Alembic head is exactly `0054`.
6. Verify no `backend/alembic/` migration revision/env/config/template change exists between rollback and release.
7. Verify the normal schema-neutral harness accepts this release/rollback pair.
8. Verify actual pinned public-key SSH readiness according to bootstrap/runbook.
9. Run focused pre-rollout source checks sufficient to catch release corruption:
   - `backend/tests/test_rel1d_role_import_extraction.py`
   - `backend/tests/test_rel1d_role_import_grounding.py`
   - `backend/tests/test_rel1d_role_import_batch.py`
   - `backend/tests/test_rel1c_assistant_role_reads.py`
   - `backend/tests/test_rel1c_assistant_role_writes.py`
   - focused ActionPlan tests affected by C1.2
   - Ruff on REL1D-touched backend Python if practical
   - `git diff --check`

Do not broaden into historical unrelated debt.

If any preflight fails before mutation:

- do not move `production`;
- do not deploy;
- do not touch client;
- record one sanitized blocker;
- return HOLD;
- STOP.

## Production ref gate

Immediately before the deploy harness:

- fast-forward `refs/heads/production` from exact `ROLLBACK_SHA` to exact `RELEASE_SHA`;
- no force;
- verify fresh `origin/production == RELEASE_SHA`.

If production is not exactly at `ROLLBACK_SHA` immediately before the move, STOP for Architect review. Do not reconcile an unexpected ref.

## Execute only the canonical schema-neutral deploy harness

Run exactly:

```bash
RELEASE_SHA=6693578d35c1ea1d6e25bf73768ca0cf6c07dac9
ROLLBACK_SHA=6f802d6959aca40758376a83d5bdfcbbd77fc537
EXPECTED_ALEMBIC=0054

python3 ops/production/deploy.py \
  --release-sha "$RELEASE_SHA" \
  --rollback-sha "$ROLLBACK_SHA" \
  --expected-alembic "$EXPECTED_ALEMBIC"
```

Do not substitute:

- migration harness;
- direct SSH;
- direct Docker Compose;
- direct Alembic;
- manual SQL;
- ad-hoc remote commands.

The committed deploy harness is the only authorized live backend mutation path.

## Success acceptance

R1 is successful only if the harness proves:

- `DEPLOYMENT=PASS`;
- production checkout/runtime exact `RELEASE_SHA`;
- fresh `origin/production == RELEASE_SHA`;
- Alembic exact `0054`;
- health PASS;
- DB container identity unchanged;
- DB volume identity unchanged;
- `.env` checksum unchanged;
- API recreated;
- worker recreated;
- no database migration executed;
- no production data intentionally created/edited by Executor;
- no model/provider call;
- no client replacement.

After success, do a sanitized read-only verification only as provided/required by the harness/runbook. Do not call role-import product endpoints merely to manufacture evidence.

## Failure / rollback handling

Obey `ops/production/deploy.py` fail-closed behavior.

If deployment fails before remote mutation after this task moved `production`:

- restore `refs/heads/production` to exact `ROLLBACK_SHA` only when production runtime remained rollback;
- no force if a normal fast-forward/backward update is unavailable: STOP rather than improvise;
- record sanitized blocker;
- HOLD;
- STOP.

If the harness performs/attempts automatic application rollback:

- accept only the harness-defined exact rollback;
- require runtime exact `ROLLBACK_SHA`, Alembic `0054`, health PASS, DB container/volume/.env preserved;
- restore production ref to rollback if safely required by the runbook/task;
- HOLD;
- STOP.

If there is any uncertain runtime/ref/schema state or a break-glass marker:

- no direct repair;
- no manual SSH/Compose/SQL;
- no client rollout;
- return HOLD with sanitized exact markers;
- STOP for Architect review.

## Explicitly authorized effects in R1

Authorized:

- exact no-force production branch fast-forward from rollback to release;
- exact schema-neutral production backend deploy through `ops/production/deploy.py`;
- API/worker rebuild and recreate performed by that harness;
- required sanitized read-only verification.

Not authorized in R1:

- Linux client build/install/replacement;
- Alembic migration/downgrade;
- real role-import extraction;
- real Assistant/model/provider call;
- upload of a human acceptance document;
- approve/reject of a role-import plan;
- product-data mutation;
- any new product slice.

## Completion protocol

On success:

1. append a compact factual `REL1D-R1` entry to `PROJECT_STATE.md` containing:
   - local/current main used to launch;
   - exact release and rollback SHAs;
   - production ref before/after;
   - exact deploy harness;
   - `DEPLOYMENT` result;
   - production runtime SHA;
   - Alembic result;
   - health result;
   - DB container/volume/.env preservation;
   - API/worker recreation;
   - rollback unused/used/blocked;
   - no migration;
   - installed client still exact `ROLLBACK_SHA`;
   - no model/provider/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - R1 succeeded;
   - production backend/source = `RELEASE_SHA`;
   - production branch = `RELEASE_SHA`;
   - Alembic = `0054 / 0054`;
   - installed client still = `ROLLBACK_SHA`;
   - REL1D-R2 exact-release Linux client build/install is the next stage under the already granted rollout authorization;
   - do not start R2 from this task.

3. commit + push ledger updates to `main`.

4. STOP.

On blocker/failure, record only accurate sanitized facts, return HOLD, commit/push ledger if appropriate, and STOP.

Every final report must end with:

`REPORT_TIME_MSK=HH:MM`
