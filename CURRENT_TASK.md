# Current task — PL1-A: deterministic People-from-Task spatial projection primitive

## State

- PT1 Task↔Person bridge: COMPLETE / human accepted.
- Production application/runtime and `origin/production`: `44407ed6e972a05809d55874acaa966cc7e141c8`.
- Production Alembic: `0051 / 0051`.
- Current Task geography is client-derived through the existing Graph layout / Task-map projection.
- Current People overview still uses the independent `projectPeopleOverview` ranked grid.
- People Landscape UI/API wiring is NOT yet authorized.

## Goal

Implement and test a pure deterministic client-side projection primitive that derives Person positions from existing Task coordinates and explicit Task↔Person participation.

This slice establishes only the spatial contract. Do not wire it into the People screen yet.

Suggested home:

`client/lib/graph/people_landscape.dart`

Equivalent focused placement is acceptable if it keeps the primitive isolated and reusable.

## Spatial contract

Inputs must be equivalent to:

- visible Person ids;
- Task top-left positions in the existing Task-map coordinate system;
- explicit Task ids linked to each Person.

The helper must return derived Person top-left positions only for People with at least one usable Task anchor.

Rules:

1. **One Task**
   - Person base position is derived directly from that Task coordinate.
   - Use the existing graph node dimensions/center convention rather than inventing a second coordinate system.

2. **Multiple Tasks**
   - Use the simple arithmetic/geometric centroid of the distinct linked Task coordinates.
   - No role weighting.
   - No salience weighting.
   - No recency weighting.
   - No manager/authority weighting.

3. **Duplicate roles on one Task**
   - The same Task id counts once even if the Person has multiple actor roles on that Task.
   - PT1 explicitly permits multiple roles; they must not pull the Person twice toward the same Task.

4. **Missing / unusable Task anchors**
   - Ignore Task ids that have no supplied Task position.
   - If no usable Task anchor remains, emit no Person position.
   - Do not invent a fallback spatial truth inside this helper.

5. **Deterministic local de-collision**
   - If multiple People resolve to overlapping base positions, separate them locally and deterministically.
   - Result must not depend on input iteration order.
   - Use stable Person-id ordering and fixed search/ring ordering.
   - Reuse existing graph node dimensions / overlap semantics where practical.
   - Keep movement local to the derived base point; this is not a new global layout engine.

6. **Derived projection only**
   - Do not persist Person coordinates.
   - Do not add DB columns, migrations, or write APIs.
   - Do not mutate Task coordinates.
   - Do not infer any Person relation beyond the explicit Task ids supplied to the helper.

## Tests

Add focused tests proving at minimum:

- one Person + one Task anchors deterministically to that Task geography;
- one Person + two Tasks lands at the unweighted geometric midpoint/centroid;
- three Tasks use the arithmetic centroid;
- duplicate Task ids for multiple actor roles are deduplicated before centroid calculation;
- unknown/missing Task ids do not affect the centroid;
- a Person with no usable Task anchor is omitted;
- two or more People with the same base point receive non-overlapping deterministic positions;
- reversing/shuffling Person input order produces exactly the same result;
- no role type can alter weighting because the primitive consumes Task identity/coordinates, not social semantics.

## Scope guard

Do not:

- change `projectPeopleOverview` behavior yet;
- wire the projection into `GraphWorkspaceScreen` or `GraphWorkspaceController`;
- change People/Graph backend APIs;
- add a new endpoint;
- deploy;
- build a human-gate bundle;
- change Task Graph layout semantics;
- start social/authority ontology;
- start Secretary Person context;
- start final Graph stabilization.

This is a source-only geometry primitive + tests.

## Completion

1. Commit/push implementation to `main`.
2. Record exact implementation SHA and test results in `PROJECT_STATE.md`.
3. Return `CURRENT_TASK.md` to HOLD.
4. Report:
   - implementation SHA;
   - HOLD SHA;
   - files changed;
   - focused test result;
   - relevant Flutter analyze result;
   - `git diff --check`;
   - confirmation that People UI/API behavior and production remain unchanged.
5. STOP.
