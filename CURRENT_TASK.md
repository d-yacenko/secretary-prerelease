# Current task — Release R4: Graph G3A semantic-window rollout

Graph G3A is ACCEPTED.

This task authorizes:
1. one schema-neutral production application rollout;
2. one exact-release Linux debug client build for the human gate.

Do not start G3B.
Do not start S3 or H2D.

## Exact release contract

Release SHA:
`489741540e30a775e2ea086f3976d7305512afe2`

Current production / rollback SHA:
`6a38a22303c0af882fcb32c4a7ac91b708cb52f4`

Expected Alembic before and after:
`0050`

Deploy entrypoint:
`ops/production/deploy.py`

Do not deploy moving HEAD by name.
Do not use a migration harness.

## Release contents

G3A changes both backend and client product code.

Backend:
- Tasks overview uses whole semantic constellations/windows;
- additive `window_index` paging contract and semantic-window metadata;
- rooted Task includes its full structural constellation before optional bounded context;
- emergency complete-constellation ceiling returns explicit error instead of partial data.

Client:
- parses semantic-window metadata;
- next/previous overview area controls;
- `Область N из M`;
- semantic completeness banner;
- overview window replacement semantics.

No Alembic/schema migration.

## 1. Bootstrap / fail-closed preflight

Follow `AGENTS.md` and `docs/executor_bootstrap.md`.

Canonical repository:
`https://github.com/d-yacenko/secretary-prerelease.git`

Use a clean canonical checkout.

Before production mutation verify:

- local `main` == `origin/main`;
- release SHA resolves exactly to `489741540e30a775e2ea086f3976d7305512afe2`;
- rollback SHA resolves exactly to `6a38a22303c0af882fcb32c4a7ac91b708cb52f4`;
- rollback is an ancestor of release;
- `origin/production` is still exactly rollback SHA;
- rollback -> release contains no Alembic version-file change and no migration-infrastructure change;
- production target/pinned host-key contract remains valid.

If any condition fails, STOP with one sanitized blocker.

Do not repair or reinterpret production state.

## 2. Focused predeploy checks

At exact release SHA run backend coverage at minimum:

- `backend/tests/test_graph_workspace_g3a.py`;
- `backend/tests/test_graph_workspace_g2.py`;
- `backend/tests/test_graph_workspace_g1r.py`;
- `backend/tests/test_graph_workspace_g1.py`;
- `backend/tests/test_graph_workspace_part_of_closure.py`;
- relevant schema-neutral deploy guard from `backend/tests/test_production_migration_deploy.py`;
- Ruff on touched backend files;
- `git diff --check`.

Run focused client coverage at minimum:

- semantic-window tests;
- Graph workspace controller;
- Graph workspace/screen;
- G1R;
- relation map/inventory;
- part_of;
- hybrid/focus LOD.

Run Flutter analyze on touched G3A client files.

The already documented bootstrap-user backend failures and object-detail client failures are not authorization to change unrelated code.

If a focused G3A/G2/G1R/G1 regression fails, STOP before moving production ref.

## 3. Promote production ref

Only after successful preflight, fast-forward `origin/production`:

from:
`6a38a22303c0af882fcb32c4a7ac91b708cb52f4`

to:
`489741540e30a775e2ea086f3976d7305512afe2`

No force-push.

If `origin/production` changed concurrently, STOP.

Verify exact release ref after promotion.

## 4. Schema-neutral backend rollout

Run only:

```bash
python3 ops/production/deploy.py \
  --release-sha 489741540e30a775e2ea086f3976d7305512afe2 \
  --rollback-sha 6a38a22303c0af882fcb32c4a7ac91b708cb52f4 \
  --expected-alembic 0050
```

Do not use direct production SSH/Compose outside the harness.
Do not run Alembic manually.
The harness owns application rollback.

Require:

- `DEPLOYMENT=PASS`;
- runtime and `origin/production` exact release SHA;
- health PASS;
- Alembic `0050`;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- api and worker recreated;
- no migration.

If automatic rollback occurs, report and STOP.
If state is uncertain, STOP and do not improvise.

## 5. Exact-release Linux client build

After successful backend rollout, from a clean checkout of EXACT:

`489741540e30a775e2ea086f3976d7305512afe2`

build:

```bash
cd client
flutter build linux --debug
```

Run the focused client tests/analyze before or as part of this exact-release build gate.

Record the exact absolute bundle path ending in:

`build/linux/x64/debug/bundle/personal_secretary`

Do NOT install over the user's existing client.
Do NOT change saved API URL, preferences, secure storage, or token.
A startup-only launch is allowed if existing release procedure supports it; do not click through product UI.

## 6. Read-only postdeploy verification

Do NOT inspect or mutate human production Tasks/relations.

Verify read-only:

- deployed code SHA exact release;
- OpenAPI registers `GET /graph/workspace`;
- OpenAPI exposes additive `window_index`;
- Alembic remains `0050`.

Do not create production test data.

## 7. Human G3A gate

Executor must not perform this gate.

After R4 success, the HUMAN launches the exact R4 Linux bundle.

Validate:

1. ordinary Tasks overview loads;
2. if only one semantic window exists, no false implication of hidden partial constellations;
3. if multiple windows exist, toolbar shows `Область N из M` and previous/next controls;
4. within the visible area, inspect at least one Direction with descendants and confirm its Task hierarchy is whole;
5. inspect a Task with confirmed user/agent Flow evidence and confirm that evidence belonging to the constellation is present;
6. move to next area and verify the previous area is replaced rather than accumulated;
7. move back and verify deterministic membership;
8. direct relation inventory may show `не на карте` only for another semantic area or optional local context;
9. `Показать связи` remains local/rooted expansion and does not redefine overview membership.

The key acceptance question is NOT node count. It is:

**Can the human trust that every constellation currently shown is semantically complete?**

Do not start G3B before this gate.

## 8. Forbidden

Do NOT:

- implement pan-trigger loading;
- add a raw Node Limit setting;
- change schema/Alembic;
- recreate DB;
- change production `.env`;
- inspect/mutate human production graph data;
- use bearer tokens;
- install/replace user's existing client;
- modify product code during rollout;
- fix unrelated baseline failures;
- start G3B;
- start S3;
- start H2D.

## 9. Completion

On success update `PROJECT_STATE.md` with:

- release and previous SHA;
- production ref/runtime SHA;
- Alembic;
- harness and health;
- DB container/volume/`.env` preservation;
- no migration/no production test data;
- exact Linux bundle path;
- client startup result if performed;
- human G3A gate pending.

Return `CURRENT_TASK.md` to HOLD and push the documentation completion commit to `main`.

Final report:

1. SUCCESS or BLOCKED;
2. release SHA;
3. production SHA;
4. Alembic;
5. deploy harness;
6. health;
7. DB container/volume/`.env` preservation;
8. exact Linux bundle path;
9. client test/analyze/build result;
10. rollback status;
11. documentation/HOLD commit SHA.

Then STOP. Do not start G3B yourself.
