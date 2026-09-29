# Current task — PT1-R1: schema-neutral production rollout

## State

- PT1 source-ready release: `02855ee49cc2fe31cd68f4649235d61665dbbcb1`.
- Current production/runtime/origin-production: `93dd1e923dfd8df2860db390bf81cf8a0cc80802`.
- Alembic: `0051`.
- Compare production -> release: 18 commits ahead, 0 behind.
- No Alembic-path changes.
- Canonical `ops/production/deploy.py` is unchanged.
- PT1 is not yet human-accepted.
- People Landscape and later roadmap slices remain unauthorized.

## Goal

Perform the canonical schema-neutral production rollout of exact release:

`02855ee49cc2fe31cd68f4649235d61665dbbcb1`

This is deployment/provenance only. Do not change product source.

## Rollout discipline

1. Verify current production and `origin/production` are still exactly `93dd1e923dfd8df2860db390bf81cf8a0cc80802`.
2. Verify release `02855ee49cc2fe31cd68f4649235d61665dbbcb1` is a clean fast-forward from production.
3. Use canonical `ops/production/deploy.py`.
4. Promote only by normal fast-forward. No force push.
5. Require deployment harness PASS and health PASS.
6. Verify runtime/release/origin-production all resolve to exact `02855ee49cc2fe31cd68f4649235d61665dbbcb1`.
7. Verify Alembic remains `0051 / 0051`.

## Production safety

Do not:
- create/remove/confirm/reject Task↔Person actor relations during rollout;
- write Person data;
- install or replace the client;
- start People Landscape or any later roadmap slice.

DB container, DB volume, and `.env` must remain unchanged unless the canonical harness proves an unexpected requirement; if so, STOP instead of improvising.

## Completion

Record in `PROJECT_STATE.md`:
- previous and new production SHA;
- fast-forward result;
- deploy harness result;
- health result;
- runtime/release/origin-production SHA;
- Alembic before/after;
- DB container/volume/.env status;
- recreated services;
- rollback status;
- explicit confirmation that no production Person or Task↔Person write occurred.

Return `CURRENT_TASK.md` to HOLD, push documentation to `main`, report facts, and STOP.

Do not build the human-gate client yet. That will be separately authorized after rollout acceptance.
