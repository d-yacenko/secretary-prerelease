# Current task — GR1-R1 schema-neutral production rollout for human gate

Human explicitly authorized this rollout on 2026-10-01.

Authorized release SHA:
`0719e9bf5af75a8065a9916d8e27c0247a3921ec`

Current production / rollback SHA:
`1b6943ba4f7cc49df1465791d812d45db6d26b52`

Expected Alembic:
`0052`

GR1 source is Architect-reviewed and SOURCE-ACCEPTED. This task authorizes only the schema-neutral production backend rollout required for end-to-end human verification of relation repairability and attached-endpoint visibility.

Canonical Task layout remains `task-map-v2.2`. No client installation is authorized.

## Verified release facts

Architect preflight verified:

- release is a clean descendant of current production;
- merge-base(production, release) is exactly `1b6943ba4f7cc49df1465791d812d45db6d26b52`;
- production -> release is 14 commits ahead, 0 behind;
- there are no changes under `backend/alembic/**`, `backend/alembic.ini`, or other migration infrastructure between rollback and release;
- `ops/production/deploy.py` is unchanged between rollback and release;
- runtime backend changes after current production are limited to GR1:
  - `backend/app/services/graph_service.py`;
  - `backend/app/services/graph_workspace_service.py`;
  - `backend/app/services/relation_decision_service.py`;
- intervening TL2.2 changes are client-side canonical-layout work and do not require server schema migration;
- production is already Alembic `0052 / 0052`.

## Goal

Promote exact release `0719e9bf5af75a8065a9916d8e27c0247a3921ec` to production using the canonical fail-closed schema-neutral deployment harness so the GR1 debug client can be human-tested against matching backend behavior.

## Mandatory preflight

Bootstrap exactly per `docs/executor_bootstrap.md`.

Before any production mutation, verify and fail closed on any mismatch:

1. canonical local checkout is clean, on `main`, and exactly equals `origin/main`;
2. `origin/production == 1b6943ba4f7cc49df1465791d812d45db6d26b52`;
3. release `0719e9bf5af75a8065a9916d8e27c0247a3921ec` resolves locally;
4. release is a fast-forward descendant of rollback SHA and merge-base is exactly rollback SHA;
5. no migration infrastructure changed between rollback and release;
6. canonical `ops/production/deploy.py` is unchanged;
7. committed production target / host-key contract is intact;
8. expected production Alembic is `0052`.

Do not discover or guess alternate hosts, paths, credentials, Compose files, environment values, or deployment methods.

## Authorized production action

1. Fast-forward `refs/heads/production` from exactly:

`1b6943ba4f7cc49df1465791d812d45db6d26b52`

to exactly:

`0719e9bf5af75a8065a9916d8e27c0247a3921ec`

Rules:
- normal fast-forward only;
- no force push;
- if old production ref no longer matches, STOP.

2. Execute only the canonical deployment entrypoint:

```bash
python3 ops/production/deploy.py \
  --release-sha 0719e9bf5af75a8065a9916d8e27c0247a3921ec \
  --rollback-sha 1b6943ba4f7cc49df1465791d812d45db6d26b52 \
  --expected-alembic 0052
```

Do not substitute direct SSH, direct Docker/Compose, migration harnesses, or ad-hoc commands.

## Required successful result

The canonical harness must exit 0 and report sanitized evidence including:

- `RELEASE_HEAD=0719e9bf5af75a8065a9916d8e27c0247a3921ec`;
- `HEALTH=PASS`;
- `ALEMBIC=0052`;
- `DB_CONTAINER_UNCHANGED=true`;
- `DB_VOLUME_UNCHANGED=true`;
- `ENV_FILE_UNCHANGED=true`;
- `API_RECREATED=true`;
- `WORKER_RECREATED=true`;
- `DEPLOYMENT=PASS`;
- rollback not used.

After success verify:

- runtime checkout == exact release SHA;
- `origin/production` == exact release SHA;
- production branch ref == exact release SHA;
- Alembic remains `0052 / 0052`;
- API health remains healthy;
- DB container / DB volume / `.env` remain unchanged.

## Safety boundaries

This authorization does NOT permit:

- Alembic upgrade/downgrade;
- schema changes;
- direct/manual DB writes;
- manually creating, editing, deleting, confirming, rejecting, or rewiring application objects/relations for validation;
- changing `.env`;
- changing provider/OAuth/Telegram settings;
- installing or replacing the desktop client;
- direct SSH or manual Compose;
- moving unrelated refs;
- break-glass repair;
- starting another Graph-cleanup slice;
- starting SW2-B.

If any preflight or invariant fails, STOP and report the sanitized blocker.

If the canonical harness itself performs its built-in rollback after a failed recreate, record that result and STOP. Do not add manual recovery.

## Human gate after successful rollout

Do not perform human acceptance yourself and do not manufacture test data.

After rollout, leave production ready for the user to run the workstation-local GR1 debug client manually:

`/home/d.yacenko/tmp/gr1-0719e9b-artifact/bundle/personal_secretary`

The Executor must NOT install or replace the client.

Human verification should use existing live data and check:

1. Select a Task/Direction with old confirmed agent-created relations. Removable confirmed agent relations show “Удалить связь”.
2. Removing one such relation preserves provenance by rejecting it; it disappears from active map/inspector.
3. For a wrong directed edge, user can remove the wrong edge and then recreate the correct direction with existing “Добавить связь”.
4. A proposed endpoint such as `Program_DYSC.pdf` is already visible on the same Graph canvas as its Task; no inspector-first discovery or extra “show” action is needed.
5. Proposed Confirm/Reject controls remain available.
6. Exceptional genuinely off-area rows remain labeled `вне текущей области` and navigable.
7. TL2.2 geometry and SW2-A whole-component pagination do not regress.

Do not automatically perform relation deletion/confirmation during deployment. Those are human-gate actions.

## Completion contract

On successful rollout:

1. append to `PROJECT_STATE.md`:
   - authorization/release/rollback SHAs;
   - production fast-forward result;
   - exact sanitized deploy-harness evidence;
   - runtime/origin-production/release equality;
   - Alembic before/after;
   - DB container/volume/.env invariants;
   - recreated services;
   - rollback status;
   - explicit confirmation that no application data was modified for validation;
   - human verification status: PENDING;
2. replace this file with `# Current task — HOLD` plus concise rollout result and explicit “await user GR1 human check”;
3. commit/push ledger changes to `main`;
4. STOP.

Do not begin another slice until the user completes the GR1 human gate and the Architect records the result.
