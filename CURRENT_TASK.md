# Current task — ACTIVE

## AH2-ROLL1 — schema-neutral backend rollout of accepted remediation

User explicitly authorized this production operation on 2026-10-02.

Authorization scope is exactly:

- roll out the accepted backend from the current accepted main snapshot;
- no Alembic migration;
- no database recreation;
- no client build/install;
- no mobile/desktop/web client rollout;
- no real model/provider behavior test by Executor.

After a successful backend rollout, return to HOLD for the human AH2-PER1 behavior gate.

## Exact authorized release

```
RELEASE_SHA=943281190b386bbe22c4631709635883c950b459
ROLLBACK_SHA=aa3f475a3a0ee49b938364e6d53f3657711b1a9b
EXPECTED_ALEMBIC=0052
```

Facts verified by Architect before authorization:

- `origin/production = aa3f475a3a0ee49b938364e6d53f3657711b1a9b`;
- `RELEASE_SHA` is 58 commits ahead of `ROLLBACK_SHA` and not behind;
- there are no changed files under `backend/alembic/` in that transition;
- the accepted release contains FIN1, FIN2, AP1, STG1, SEM1 and PER1 backend remediation;
- AH2-PER1 is ARCHITECT SOURCE-ACCEPTED;
- current production Alembic is `0052` and health is PASS.

The task-authorization commit on `main` is operational ledger only and is intentionally newer than `RELEASE_SHA`. Do not substitute a newer SHA as the production release.

## Mandatory bootstrap

Follow `docs/executor_bootstrap.md` and `docs/deploy.md`.

Use only the canonical repository:

`https://github.com/d-yacenko/secretary-prerelease.git`

For runtime work:

- use only `ops/production/target.json`;
- use the committed pinned SSH host key;
- use the pre-existing Executor/workstation SSH credential integration;
- do not create/copy/request credentials;
- do not probe alternate hosts, paths, origins or environment files.

Before changing `production`, prove a read-only SSH no-op to the canonical pinned target succeeds as defined by the bootstrap runbook.

If bootstrap or SSH readiness fails, STOP with one sanitized blocker. Do not move the `production` branch.

## Preflight — no production mutation yet

From a clean canonical local `main` checkout:

1. fetch `origin/main` and `origin/production`;
2. verify local `main` equals `origin/main`;
3. verify `origin/production` is exactly `ROLLBACK_SHA`;
4. verify both exact SHAs resolve;
5. verify `ROLLBACK_SHA` is an ancestor of `RELEASE_SHA`;
6. verify there is no diff between rollback and release in:
   - `backend/alembic/versions/`
   - `backend/alembic/env.py`
   - `backend/alembic.ini`
   - `backend/alembic/script.py.mako`;
7. run the relevant deployment-harness tests if they are available without real production mutation.

Any mismatch: STOP. Do not repair or bypass it.

## Production ref promotion

Only after bootstrap and all preflight checks pass:

Fast-forward `origin/production` from exactly `ROLLBACK_SHA` to exactly `RELEASE_SHA`.

Use a normal fast-forward push. Do not force-push the forward promotion.

Immediately verify:

`origin/production == RELEASE_SHA`.

Do not push `main` itself to production and do not select any SHA other than `RELEASE_SHA`.

## Mandatory deployment entrypoint

Run the committed normal schema-neutral harness only:

```bash
python3 ops/production/deploy.py \
  --release-sha 943281190b386bbe22c4631709635883c950b459 \
  --rollback-sha aa3f475a3a0ee49b938364e6d53f3657711b1a9b \
  --expected-alembic 0052
```

Direct ad-hoc SSH deployment commands and direct production Compose commands are forbidden.

The harness is expected to:

- build only `api` and `worker`;
- recreate only `api` and `worker`;
- keep `db` container unchanged;
- keep DB volume unchanged;
- keep `.env` unchanged;
- keep Alembic exactly `0052`;
- verify health;
- auto-attempt application rollback to `ROLLBACK_SHA` if a post-recreate invariant fails.

No migration command is authorized.

## Success gate

Treat rollout as successful only if the harness reports all of the following:

- `RELEASE_HEAD=943281190b386bbe22c4631709635883c950b459`
- `HEALTH=PASS`
- `ALEMBIC=0052`
- `DB_CONTAINER_UNCHANGED=true`
- `DB_VOLUME_UNCHANGED=true`
- `ENV_FILE_UNCHANGED=true`
- `API_RECREATED=true`
- `WORKER_RECREATED=true`
- `DEPLOYMENT=PASS`

Then verify `origin/production` still equals `RELEASE_SHA`.

Do not call OpenAI or any external messaging/provider action as a smoke test.

## Failure handling and production-ref coherence

Do not perform ad-hoc repair.

If the production ref was promoted but the deployment does not succeed:

### Safe ref restoration is authorized only when runtime rollback is proven

You may restore `production` back to `ROLLBACK_SHA` only if one of these is explicitly proven:

- deployment was blocked before application recreation and the production runtime remained/restored at `ROLLBACK_SHA`; or
- the harness reports `ROLLBACK=PASS`.

In that case, restore the branch only with an exact lease requiring the current remote production ref to still equal `RELEASE_SHA`, then verify it equals `ROLLBACK_SHA`.

This backward ref move is authorized solely to make the Git production ref match the proven rolled-back runtime.

If runtime state is uncertain, automatic rollback fails, the remote ref changed unexpectedly, or any invariant cannot be proven:

- do not force a ref;
- do not repair;
- STOP and report a sanitized blocker for Architect review.

## Explicit non-goals

Do not:

- run Alembic upgrade/downgrade;
- modify schema;
- recreate or restart `db`;
- alter DB volume;
- change `.env`;
- rotate credentials;
- install/rebuild the Flutter client for the user;
- deploy a web/mobile/desktop client;
- change product code;
- clean up stale M1 or Person tests;
- run real-model AH2-M evaluation;
- perform the manual PER1 prompt on behalf of the user;
- start Scheduled Activity work or another remediation slice.

## Completion protocol

On successful rollout:

1. append a compact factual AH2-ROLL1 result to `PROJECT_STATE.md`, including:
   - release and rollback SHAs;
   - production-ref promotion;
   - exact harness result markers;
   - health and Alembic result;
   - DB/container/env preservation;
   - no migration/client/model/provider statement;
2. record AH2-PER1 Architect source acceptance if not already present in the ledger;
3. return `CURRENT_TASK.md` to HOLD for the manual AH2-PER1 behavior gate;
4. set the HOLD text to state that production backend now runs `RELEASE_SHA`, Alembic remains `0052`, and the next action belongs to the human tester;
5. commit + push the ledger update to `main`;
6. STOP.

On failure/blocker:

- record only sanitized facts;
- return `CURRENT_TASK.md` to HOLD with the exact safe state that is known;
- commit/push ledger only if doing so does not misstate production;
- STOP.

Do not start any further code or deployment work from HOLD.
