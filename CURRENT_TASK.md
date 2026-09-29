# Current task — PT1-H2-R1: schema-neutral production rollout

## State

- PT1-H2 source-ready release: `44407ed6e972a05809d55874acaa966cc7e141c8`.
- Current production/runtime/origin-production: `02855ee49cc2fe31cd68f4649235d61665dbbcb1`.
- Alembic: `0051`.
- Compare production -> H2: 12 commits ahead, 0 behind.
- Changes since production are docs + Flutter UI/tests only.
- No backend or Alembic-path changes.
- Canonical `ops/production/deploy.py` is unchanged.
- PT1 is not yet human-accepted.
- People Landscape and later roadmap slices remain unauthorized.

## Goal

Perform the canonical schema-neutral production rollout of exact release:

`44407ed6e972a05809d55874acaa966cc7e141c8`

This is deployment/provenance only. Do not change product source.

## Rollout discipline

1. Verify current production and `origin/production` are still exactly `02855ee49cc2fe31cd68f4649235d61665dbbcb1`.
2. Verify `44407ed6e972a05809d55874acaa966cc7e141c8` is a clean non-force fast-forward.
3. Use canonical `ops/production/deploy.py`.
4. Require `DEPLOYMENT=PASS`, health PASS, and exact `RELEASE_HEAD=44407ed6e972a05809d55874acaa966cc7e141c8`.
5. Verify runtime/release/origin-production all resolve to exact H2 SHA.
6. Verify Alembic remains `0051 / 0051`.

## Production safety

Do not:
- create/remove/confirm/reject Task↔Person actor relations;
- write Person data;
- repair or alter the human tester's real relation;
- install or replace the client;
- build the new human-gate bundle;
- start People Landscape or later roadmap work.

DB container, DB volume, and `.env` must remain unchanged; if the canonical harness indicates otherwise, STOP rather than improvise.

## Completion

Record in `PROJECT_STATE.md`:
- previous/new production SHA;
- fast-forward result;
- deploy harness + health;
- runtime/release/origin-production SHA;
- Alembic before/after;
- DB container/volume/.env status;
- recreated services;
- rollback status;
- explicit confirmation of no Person or Task↔Person production writes.

Return `CURRENT_TASK.md` to HOLD, push documentation to `main`, report exact HOLD SHA, and STOP.

Do not build the new human-gate bundle until separately authorized.
