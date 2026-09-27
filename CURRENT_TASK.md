# Current task — Release R1: schema-neutral S2R + G1 rollout and exact-release Linux client build

Graph G1 is ACCEPTED.

This task authorizes one schema-neutral production application rollout and one Linux client build from the SAME exact release.

Do not start S3 or H2D.

## Exact release contract

Release SHA:
`2a765d68ca8c7bc859e4902f00df6bb2d3b9bc6b`

Current production / rollback SHA:
`fd45df20ff53ad973f22e461ff84f3cb5c251b8a`

Expected Alembic before and after:
`0050`

Normal schema-neutral deploy entrypoint:
`ops/production/deploy.py`

Do not deploy moving `HEAD` by name.

Do not use a migration harness.

## What this release contains

Application changes since current production are bounded to the accepted S2R + Graph G1 line plus workflow documentation:

- S2R Task/Direction human presentation and truthful finite <-> ongoing UI;
- converged manual Capture form;
- optional Capture `due_at`, `planned_start_at`, `planned_end_at`;
- G1 stable ordinary-neighbor ordering;
- G1 structural `part_of` closure for admitted Tasks;
- direct selected-object relation inventory;
- truncation explanation;
- visual relation chooser previews.

No Alembic migration is authorized or expected.

## 1. Bootstrap / fail-closed preflight

Follow `AGENTS.md` and `docs/executor_bootstrap.md`.

Canonical repository:
`https://github.com/d-yacenko/secretary-prerelease.git`

Use a clean canonical `main` checkout.

If the current checkout is dirty, wrong-origin, stale, or otherwise unsafe, leave it untouched and use a fresh temporary canonical clone.

Before any production mutation verify:

- local `main` == `origin/main`;
- exact release SHA resolves to `2a765d68ca8c7bc859e4902f00df6bb2d3b9bc6b`;
- exact rollback SHA resolves to `fd45df20ff53ad973f22e461ff84f3cb5c251b8a`;
- rollback is an ancestor of release;
- `origin/production` is still exactly rollback SHA;
- diff rollback -> release changes no Alembic migration file or migration infrastructure;
- production target/pinned host-key contract remains valid.

If any condition fails, STOP with one sanitized blocker.

Do not repair production state by improvisation.

## 2. Release verification before promotion

At exact release SHA run focused backend checks:

- `backend/tests/test_capture_s2_completion_mode.py`;
- `backend/tests/test_direct_tasks_api.py`;
- `backend/tests/test_task_completion_mode.py`;
- `backend/tests/test_graph_workspace_g1.py`;
- relevant production schema-neutral deploy guard from `backend/tests/test_production_migration_deploy.py`.

Run the focused client checks covering:

- Capture S2R;
- Task Direction edit;
- Graph direct relation inventory;
- Graph part_of chooser;
- Graph workspace/controller/map relation/proposed relation/hybrid paths;
- API client request serialization used by S2R.

Known unrelated/baseline-dependent failures already recorded in PROJECT_STATE are not authorization to modify unrelated code. If a focused S2R/G1 regression fails, STOP.

Also run:

`git diff --check`

and verify no migration delta.

Build the Linux debug client BEFORE production promotion:

```bash
cd client
flutter pub get
flutter build linux --debug
```

Do not install or launch it yet.

## 3. Promote production ref

Only after all required preflight checks pass, fast-forward `origin/production`:

from:
`fd45df20ff53ad973f22e461ff84f3cb5c251b8a`

to:
`2a765d68ca8c7bc859e4902f00df6bb2d3b9bc6b`

No force-push.

If `origin/production` changed concurrently, STOP.

After promotion verify it resolves exactly to release SHA.

## 4. Schema-neutral application rollout

Run ONLY:

```bash
python3 ops/production/deploy.py \
  --release-sha 2a765d68ca8c7bc859e4902f00df6bb2d3b9bc6b \
  --rollback-sha fd45df20ff53ad973f22e461ff84f3cb5c251b8a \
  --expected-alembic 0050
```

Do not use direct production SSH/Compose outside the normal harness.

Do not run Alembic manually.

The harness owns application rollback.

## 5. Required successful rollout facts

Require:

- `DEPLOYMENT=PASS`;
- production checkout/runtime exact release SHA;
- `origin/production` exact release SHA;
- health PASS;
- Alembic remains `0050`;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- api recreated;
- worker recreated;
- no schema migration occurred.

If automatic application rollback happens, report the final checkout/runtime and STOP.

If rollback fails or state is uncertain, STOP; do not retry or improvise.

## 6. Post-deploy read-only contract verification

Without creating user data and without printing tokens/PII, verify deployed application contracts:

- OpenAPI `POST /capture/task` includes optional `due_at`, `planned_start_at`, `planned_end_at`;
- existing `completion_mode` remains present;
- `GET /objects/{object_id}/neighbors` remains registered;
- `GET /graph/workspace` remains registered.

Use read-only OpenAPI/import-level verification where possible.

Do NOT create production Tasks, Directions, relations, publications, or other test objects.

Do not inspect the user's real relation data as part of Executor verification.

## 7. Exact-release Linux client artifact

The prebuilt client artifact must correspond to exact release SHA:
`2a765d68ca8c7bc859e4902f00df6bb2d3b9bc6b`

Expected executable:
`client/build/linux/x64/debug/bundle/personal_secretary`

Verify the executable and bundle assets/libraries exist.

Do not replace a permanently installed client.

Do not clear or inspect secure storage, bearer tokens, or user credentials.

Do not change the saved API URL or preferences.

### Launch boundary

Do NOT perform the human UI gate.

If a graphical session is available and launching the fresh bundle does not require changing client configuration, you MAY launch it once and only verify that the process/window starts without an immediate crash.

Do not click Capture, Graph, Secretary, Account, People, Inbox, or mutate product data.

If launch would require disconnecting, editing the saved API URL, entering a token, or changing preferences, do not launch. Report the bundle path and leave launch to the human.

The separate `SECRETARY_API_BASE_URL` precedence issue remains out of scope.

## 8. Forbidden

Do NOT:

- change Alembic/schema;
- recreate DB;
- modify production `.env`;
- rotate secrets;
- inspect bearer tokens;
- use production data for testing;
- alter Telegram/provider configuration;
- fix unrelated test failures;
- modify product code during rollout;
- start S3;
- start H2D.

## 9. Completion

On complete success update `PROJECT_STATE.md` with:

- exact release SHA;
- previous/rollback SHA;
- production ref/runtime SHA;
- Alembic revision;
- deploy harness result;
- health result;
- DB container/volume/`.env` preservation;
- deployed read-only contract verification;
- exact Linux client bundle path;
- whether launch was attempted;
- confirmation no human product interaction or production test-data creation occurred.

Return `CURRENT_TASK.md` to HOLD and push the normal documentation completion commit to `main`.

Final report:

1. SUCCESS or BLOCKED;
2. release SHA;
3. production SHA;
4. Alembic;
5. deploy harness result;
6. health;
7. DB container/volume/`.env` preservation;
8. post-deploy contract checks;
9. Linux bundle path/build result;
10. launch status;
11. rollback status;
12. documentation/HOLD commit SHA.

Then STOP. Do not choose the next task yourself.
