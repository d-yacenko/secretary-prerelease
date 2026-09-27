# Current task — Release R2: schema-neutral G1R backend rollout

Graph G1R is ACCEPTED.

This task authorizes one production application rollout only.

No client refresh is required because G1R changed backend product code only; the existing R1 client already contains the required renderer/UI.

Do not start S3 or H2D.

## Exact release contract

Release SHA:
`fccc2b4c1c01430721865bd118f7eb2bbd207b38`

Current production / rollback SHA:
`2a765d68ca8c7bc859e4902f00df6bb2d3b9bc6b`

Expected Alembic before and after:
`0050`

Deploy entrypoint:
`ops/production/deploy.py`

Do not deploy moving HEAD by name.

Do not use a migration harness.

## Release contents

Product-code delta from current production is bounded to:

- `backend/app/services/graph_workspace_service.py`: final persisted-edge closure among already admitted workspace nodes.

Additional files are tests/workflow documentation only.

No client product source changed.
No Alembic/schema change exists.

## 1. Bootstrap and fail-closed preflight

Follow `AGENTS.md` and `docs/executor_bootstrap.md`.

Canonical repository:
`https://github.com/d-yacenko/secretary-prerelease.git`

Use a clean canonical checkout.

Before any production mutation verify:

- local `main` == `origin/main`;
- release SHA resolves exactly to `fccc2b4c1c01430721865bd118f7eb2bbd207b38`;
- rollback SHA resolves exactly to `2a765d68ca8c7bc859e4902f00df6bb2d3b9bc6b`;
- rollback is an ancestor of release;
- `origin/production` is still exactly rollback SHA;
- rollback -> release contains no Alembic version file change and no migration infrastructure change;
- production target/pinned host-key contract remains valid.

If any condition fails, STOP with one sanitized blocker.

Do not repair or reinterpret production state.

## 2. Focused predeploy checks

At exact release SHA run:

- `backend/tests/test_graph_workspace_g1r.py`;
- `backend/tests/test_graph_workspace_g1.py`;
- `backend/tests/test_graph_workspace_part_of_closure.py`;
- relevant schema-neutral deploy guard in `backend/tests/test_production_migration_deploy.py`;
- `git diff --check`.

The two already documented bootstrap-user graph failures are not authorization to modify unrelated tests/code.

If any focused G1R test fails, STOP before moving production ref.

No client build is required in R2.

## 3. Promote production ref

Only after successful preflight, fast-forward `origin/production`:

from:
`2a765d68ca8c7bc859e4902f00df6bb2d3b9bc6b`

to:
`fccc2b4c1c01430721865bd118f7eb2bbd207b38`

No force-push.

If `origin/production` changed concurrently, STOP.

Verify after promotion that `origin/production` is exact release SHA.

## 4. Schema-neutral rollout

Run only:

```bash
python3 ops/production/deploy.py \
  --release-sha fccc2b4c1c01430721865bd118f7eb2bbd207b38 \
  --rollback-sha 2a765d68ca8c7bc859e4902f00df6bb2d3b9bc6b \
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

Do NOT inspect the human's actual Tasks/relations and do NOT create production data.

Verify read-only:

- deployed OpenAPI still registers `GET /graph/workspace`;
- deployed code SHA is exact release;
- Alembic is still `0050`.

Do not attempt to prove G1R using the user's production relation graph. Human validation owns that step.

## 7. Human gate after rollout

Executor must not perform this gate.

After R2 success, the HUMAN will use the existing exact R1 client and:

1. open Graph overview;
2. BEFORE pressing `Показать связи`, confirm whether the structural chain is already drawn:
   `Курс по траблшутингу -> Создание курсов -> Основная работа`;
3. select `Создание курсов` and verify the direct relation inventory still contains the same confirmed `part_of` relations;
4. only after recording the initial result, optionally press `Показать связи`.

Expected successful behavior:
the structural arrows are already visible in the initial overview; `Показать связи` is no longer required to make them appear.

## 8. Forbidden

Do NOT:

- change schema/Alembic;
- recreate DB;
- change production `.env`;
- inspect/mutate human production graph data;
- use bearer tokens;
- build/install/replace client;
- alter providers/Telegram;
- modify product code during rollout;
- fix unrelated tests;
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
- human gate pending.

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
