# Current task — SW2-A-R1 schema-neutral production rollout for human gate

Human explicitly authorized this rollout on 2026-09-30.

Authorized release SHA:
`1b6943ba4f7cc49df1465791d812d45db6d26b52`

Current production / rollback SHA:
`ffccca38440d2e4eb93e8513a6cb29b4d27b4010`

Expected Alembic:
`0052`

SW2-A source is Architect-reviewed and SOURCE-ACCEPTED. This task authorizes only the schema-neutral production rollout needed for the user's manual verification of semantic-window membership. SW2-B remains unauthorized.

## Verified release facts

Architect review before authorization verified:

- release is a descendant of current production;
- production -> release is 64 commits ahead, 0 behind;
- there are no `backend/alembic/**` changes between rollback and release;
- canonical `ops/production/deploy.py` is unchanged between rollback and release;
- SW2-A runtime backend changes are limited to:
  - `backend/app/domain/task_map_topology.py`;
  - `backend/app/services/graph_workspace_service.py`;
- other post-production deltas are accepted client/test/ledger/ops artifacts and do not require schema migration;
- canonical Task layout remains `task-map-v2.1.1`;
- production database is already Alembic `0052 / 0052`.

## Goal

Promote exact release `1b6943ba4f7cc49df1465791d812d45db6d26b52` to production using the canonical fail-closed schema-neutral deployment harness, so the existing compatible TL2.1.1 client can human-test SW2-A on live data.

No client rebuild or install is part of this task.

## Mandatory preflight

Bootstrap exactly per `docs/executor_bootstrap.md`.

Before any production mutation, verify all of the following and fail closed on mismatch:

1. local canonical checkout is clean, on `main`, and exactly `origin/main`;
2. `origin/production == ffccca38440d2e4eb93e8513a6cb29b4d27b4010`;
3. release `1b6943ba4f7cc49df1465791d812d45db6d26b52` resolves and is a clean fast-forward descendant of rollback SHA;
4. merge-base(release, rollback) is exactly rollback SHA;
5. no Alembic migration infrastructure path changed between rollback and release;
6. `ops/production/deploy.py` is unchanged between rollback and release;
7. committed production target and host-key contract are intact;
8. production Alembic expectation remains `0052`.

Do not discover or guess alternate hosts, paths, credentials, repositories, Compose files, or environment values.

## Authorized production action

1. Fast-forward `refs/heads/production` from exactly
   `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`
   to exactly
   `1b6943ba4f7cc49df1465791d812d45db6d26b52`.

   - normal fast-forward only;
   - no force push;
   - if the old ref no longer matches, STOP.

2. Execute only the canonical deployment entrypoint:

```bash
python3 ops/production/deploy.py \
  --release-sha 1b6943ba4f7cc49df1465791d812d45db6d26b52 \
  --rollback-sha ffccca38440d2e4eb93e8513a6cb29b4d27b4010 \
  --expected-alembic 0052
```

Do not substitute direct SSH, direct Docker/Compose, migration harnesses, or ad-hoc recovery commands.

## Required successful result

The deploy harness must report and the Executor must record sanitized evidence for:

- `RELEASE_HEAD=1b6943ba4f7cc49df1465791d812d45db6d26b52`;
- `HEALTH=PASS`;
- `ALEMBIC=0052`;
- `DB_CONTAINER_UNCHANGED=true`;
- `DB_VOLUME_UNCHANGED=true`;
- `ENV_FILE_UNCHANGED=true`;
- `API_RECREATED=true`;
- `WORKER_RECREATED=true`;
- `DEPLOYMENT=PASS`;
- process exit status 0;
- rollback not used.

After success verify:

- runtime checkout == exact release SHA;
- `origin/production` == exact release SHA;
- production branch ref == exact release SHA;
- Alembic remains `0052 / 0052`;
- API health remains healthy;
- DB container/volume/.env are unchanged.

## Production safety boundaries

This authorization does NOT permit:

- Alembic upgrade/downgrade;
- schema changes;
- direct/manual DB writes;
- creating/editing/deleting/confirming/rejecting Task, Person, Flow, relation, layout, or other application facts for verification;
- changing `.env`;
- changing provider/OAuth/Telegram settings;
- replacing or installing the desktop client;
- moving any other refs;
- direct SSH or manual Compose;
- any break-glass repair;
- starting SW2-B.

If any preflight or invariant fails, STOP and report the sanitized blocker. If the canonical harness itself performs its built-in rollback after a failed recreate, record its result and STOP; do not add manual repair.

## Human gate after successful rollout

Do NOT perform the human acceptance yourself and do not manufacture production data.

After a successful rollout, leave the system ready for the user to open the already compatible TL2.1.1 client and inspect the existing Academic/Publications graph.

Expected manual observation:

- the Publications Direction and all its confirmed Task petals that are connected through visible confirmed Task relations should remain in one overview area under the soft pagination boundary;
- an unrelated Task component may move to another area;
- TL2.1.1 local geometry and short secondary links should remain as previously accepted;
- page navigation itself should continue to work.

The truly oversized single-component case remains SW2-B and is not part of this rollout.

## Completion contract

On successful rollout:

1. append to `PROJECT_STATE.md`:
   - authorization/release/rollback SHAs;
   - production ref fast-forward result;
   - exact sanitized deploy-harness evidence;
   - runtime/origin-production/release SHA equality;
   - Alembic before/after;
   - DB container/volume/.env invariants;
   - recreated services;
   - rollback status;
   - explicit confirmation that no application data was modified for validation;
   - human verification status: PENDING;
2. replace this file with `# Current task — HOLD` plus concise rollout result and explicit «await user human check of SW2-A»;
3. commit/push ledger changes to `main`;
4. STOP.

Do not begin SW2-B until the user completes the human gate and the Architect records the result.
