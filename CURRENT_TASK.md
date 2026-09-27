# Current task — Release R3: schema-neutral Graph G2 backend rollout

Graph G2 is ACCEPTED.

This task authorizes one production backend/application rollout only.

No client refresh is required because G2 changed no client product code.

Do not start S3 or H2D.

## Exact release contract

Release SHA:
`6a38a22303c0af882fcb32c4a7ac91b708cb52f4`

Current production / rollback SHA:
`fccc2b4c1c01430721865bd118f7eb2bbd207b38`

Expected Alembic before and after:
`0050`

Deploy entrypoint:
`ops/production/deploy.py`

Do not deploy moving HEAD by name.
Do not use a migration harness.

## Release contents

Product-code delta from current production is bounded to Graph workspace admission:

- priority admission of confirmed explicit Task<->Flow evidence before ordinary neighbors;
- deterministic fair round-robin allocation;
- part_of-admitted Tasks participate;
- shared Flow consumes one node slot;
- global node cap and ordinary neighbor limits remain unchanged.

Additional changes are tests/workflow documentation.

No client product source change.
No Alembic/schema change.

## 1. Bootstrap / fail-closed preflight

Follow `AGENTS.md` and `docs/executor_bootstrap.md`.

Canonical repository:
`https://github.com/d-yacenko/secretary-prerelease.git`

Use a clean canonical checkout.

Before any production mutation verify:

- local `main` == `origin/main`;
- exact release SHA resolves to `6a38a22303c0af882fcb32c4a7ac91b708cb52f4`;
- rollback SHA resolves to `fccc2b4c1c01430721865bd118f7eb2bbd207b38`;
- rollback is an ancestor of release;
- `origin/production` is still exactly rollback SHA;
- rollback -> release contains no Alembic version change and no migration infrastructure change;
- production target/pinned host-key contract remains valid.

If any condition fails, STOP with one sanitized blocker.

Do not repair or reinterpret production state.

## 2. Focused predeploy checks

At exact release SHA run:

- `backend/tests/test_graph_workspace_g2.py`;
- `backend/tests/test_graph_workspace_g1.py`;
- `backend/tests/test_graph_workspace_g1r.py`;
- `backend/tests/test_graph_workspace_part_of_closure.py`;
- relevant schema-neutral deploy guard from `backend/tests/test_production_migration_deploy.py`;
- Ruff on touched backend files;
- `git diff --check`.

The two documented bootstrap-user overview failures are not authorization to modify unrelated code.

If any focused G2/G1/G1R regression fails, STOP before moving production ref.

No client build is required.

## 3. Promote production ref

Only after successful preflight, fast-forward `origin/production`:

from:
`fccc2b4c1c01430721865bd118f7eb2bbd207b38`

to:
`6a38a22303c0af882fcb32c4a7ac91b708cb52f4`

No force-push.

If `origin/production` changed concurrently, STOP.

Verify after promotion that `origin/production` is exact release SHA.

## 4. Schema-neutral rollout

Run only:

```bash
python3 ops/production/deploy.py \
  --release-sha 6a38a22303c0af882fcb32c4a7ac91b708cb52f4 \
  --rollback-sha fccc2b4c1c01430721865bd118f7eb2bbd207b38 \
  --expected-alembic 0050
```

Do not use direct production SSH/Compose outside the harness.
Do not run Alembic manually.
The harness owns application rollback.

## 5. Required successful result

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
- no migration occurred.

If automatic rollback occurs, report final state and STOP.

If rollback fails or state is uncertain, STOP and do not retry/improvise.

## 6. Read-only postdeploy verification

Do NOT inspect the human's actual Tasks/Flow relations.
Do NOT create production data.

Verify read-only:

- deployed code SHA is exact release;
- OpenAPI still registers `GET /graph/workspace`;
- Alembic remains `0050`.

Do not prove G2 with user data; human validation owns that step.

## 7. Human gate after rollout

Executor must not perform this gate.

After R3 success the HUMAN will use the existing R1 client.

Primary case:
`Публикация статьи в Pattern Recognition`

Before pressing `Показать связи`:

1. open ordinary Tasks overview;
2. locate/select that Task;
3. verify confirmed user/agent Flow evidence that previously appeared in the direct relation inventory as `не на карте` now appears as compact Flow satellites / Task-Flow map connections when node budget allows;
4. compare the direct relation inventory with the map;
5. record any remaining `не на карте` entries.

Expected successful behavior:
- meaningful confirmed user/agent Task<->Flow evidence is admitted before incidental source/system neighbors;
- no manual relation recreation is required;
- `не на карте` remains possible only because of the genuine global bounded workspace, not because the ordinary per-center neighbor window consumed the evidence first.

Do not require every source/system relation to appear.

## 8. Forbidden

Do NOT:

- change schema/Alembic;
- recreate DB;
- change production `.env`;
- inspect/mutate human production graph data;
- use bearer tokens;
- build/install/replace client;
- raise Graph limits;
- alter provider/Telegram configuration;
- modify product code during rollout;
- fix unrelated failures;
- start S3;
- start H2D.

## 9. Completion

On success update `PROJECT_STATE.md` with:

- exact release and previous SHA;
- production ref/runtime SHA;
- Alembic;
- deploy harness result;
- health;
- DB container/volume/`.env` preservation;
- confirmation no migration and no production test data;
- confirmation client was not changed;
- human G2 gate pending.

Return `CURRENT_TASK.md` to HOLD and push the normal documentation completion commit to `main`.

Final report:

1. SUCCESS or BLOCKED;
2. release SHA;
3. production SHA;
4. Alembic;
5. deploy harness;
6. health;
7. DB container/volume/`.env` preservation;
8. rollback status;
9. documentation/HOLD commit SHA.

Then STOP. Do not choose the next task yourself.
