# Current task — PC1-H2-R1: schema-neutral production rollout

## State

- Source-ready release: `93dd1e923dfd8df2860db390bf81cf8a0cc80802`.
- Current production/runtime/origin-production: `a3d546b069e7e05d68fd42906c662c3ba34caef5`.
- Alembic: `0051`.
- Compare production -> release: 15 commits ahead, 0 behind.
- No Alembic-path changes.
- Canonical `ops/production/deploy.py` is unchanged.
- PC1 is not yet human-accepted.
- PT1 and later roadmap work remain unauthorized.

## Goal

Perform the canonical schema-neutral production rollout of exact release:

`93dd1e923dfd8df2860db390bf81cf8a0cc80802`

This task is deployment/provenance only. Do not change product source.

## Rollout discipline

1. Verify current production and `origin/production` are still exactly `a3d546b069e7e05d68fd42906c662c3ba34caef5`.
2. Verify release `93dd1e923dfd8df2860db390bf81cf8a0cc80802` is a clean fast-forward from production.
3. Use the repository's canonical `ops/production/deploy.py` procedure.
4. Promote only by normal fast-forward. No force push.
5. Require deployment harness PASS and health PASS.
6. Verify runtime/release/origin-production all resolve to exact `93dd1e923dfd8df2860db390bf81cf8a0cc80802`.
7. Verify Alembic remains `0051 / 0051`.

## Production safety

Do not:
- run Person merge/undo;
- create, rename, confirm, reject, restore, or otherwise mutate Person data;
- repair the human tester's previous Person state;
- install or replace the client;
- start PT1 or any later roadmap slice.

DB container, DB volume, and `.env` must remain unchanged unless the canonical harness itself proves an unexpected requirement; if so, STOP instead of improvising.

## Completion

Record in `PROJECT_STATE.md`:
- exact previous and new production SHA;
- fast-forward result;
- deploy harness result;
- health result;
- runtime/release/origin-production SHA;
- Alembic before/after;
- DB container/volume/.env status;
- recreated services;
- rollback status;
- explicit confirmation that no production Person write occurred.

Return `CURRENT_TASK.md` to HOLD, push documentation to `main`, report facts, and STOP.

Do not build the human-gate client yet. That will be a separately authorized exact-release build after rollout acceptance.
