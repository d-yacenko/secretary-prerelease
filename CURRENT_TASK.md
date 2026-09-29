# Current task — PL1-D: client landscape projection bridge + unanchored shelf

## State

- PT1 Task↔Person bridge: COMPLETE / human accepted.
- PL1-A spatial primitive: ACCEPTED at `679c8af09073e768c39fd34dc1d0192706be347d`.
- PL1-B anchor truth + H1: ACCEPTED at `cafcf5627ac4051ebe0deeaba3a08f72f96571c6`.
- PL1-C Task-geography context: ACCEPTED at `6babdd490cdc4bc64a60eeb762967a383f9c19b1`.
- Production application/runtime and `origin/production`: `44407ed6e972a05809d55874acaa966cc7e141c8`.
- Production Alembic: `0051 / 0051`.
- People overview still renders through the old `projectPeopleOverview` grid.
- Screen rendering changes are NOT authorized in this slice.

## Goal

Add a client-only read/projection bridge that composes the accepted PL1 layers without changing what the user sees yet:

1. retain the PL1-C Task context in `GraphWorkspaceController`;
2. run the existing `projectTaskMapHierarchy` on that context;
3. validate Person anchor completeness fail-closed;
4. derive anchored Person positions through existing `projectPeopleFromTasks`;
5. derive deterministic peripheral positions for genuinely unanchored People.

No coordinates are persisted.

## Controller read bridge

Retain authoritative workspace fields equivalent to:

- `landscapeTasks`
- `landscapeTaskEdges`
- `landscapeTaskContextComplete`

Expose read-only getters.

When an authoritative workspace replace occurs, replace these fields from that response; do not merge/accumulate Task context across unrelated People workspace responses.

Reset/clear them consistently with existing controller reset/mode/workspace replacement behavior.

Do not change ordinary `nodes`, `edges`, or `visiblePositions` semantics in this slice.

## Pure overview projection

Add a pure helper, preferably in `client/lib/graph/people_landscape.dart`, equivalent to:

`projectPeopleLandscapeOverview(...)`

It may return a small immutable result object carrying at least:

- whether the landscape projection is usable;
- derived Person positions;
- anchored Person ids;
- genuinely unanchored Person ids;
- unresolved/incomplete Person ids;
- Task bounds or equivalent geometry needed later by the renderer.

### Canonical Task geography

When `landscapeTaskContextComplete == true`, derive Task positions only with:

`projectTaskMapHierarchy(nodes: landscapeTasks, edges: landscapeTaskEdges)`

Do not use hybrid Flow display coordinates and do not create another Task layout.

### Person classification

For each visible Person:

1. If no matching `PersonPresentation` exists: mark unresolved.
2. If `landscapeTaskIdsComplete == false`: mark unresolved.
3. If `landscapeTaskIdsComplete == true` and the anchor list is empty: this Person is genuinely **unanchored**.
4. If the complete anchor list is non-empty, every distinct anchor id must exist in the derived Task-position map.
5. If even one supposedly complete anchor is missing, mark unresolved. Do NOT compute a centroid from the remaining Tasks.

If:
- global `landscapeTaskContextComplete == false`, or
- any visible Person is unresolved,

then the overall projection is unusable and must emit **no partial Person positions**.

The later screen slice will fall back to the current People overview grid in this state.

### Anchored People

When the projection is usable:

- pass only fully validated complete anchor sets to `projectPeopleFromTasks`;
- preserve PL1-A semantics:
  - one Task -> that Task geography;
  - several distinct Tasks -> unweighted arithmetic centroid;
  - duplicate Task ids do not double-weight;
  - stable deterministic local Person de-collision.

Do not modify PL1-A weighting semantics.

## Unanchored peripheral shelf

When the projection is usable, People with a complete empty anchor set must remain visible in a deterministic non-semantic peripheral area.

Rules:

- place the shelf outside the right side of the canonical Task bounds when Task context is non-empty;
- leave a fixed gap large enough that generic 186x100 Person cards cannot overlap Task bounds;
- order unanchored People by stable Person id, not salience, title, relationship, role, or recency;
- use fixed deterministic rows/columns and existing Graph node dimensions/gaps;
- unanchored placement must not move anchored Person positions;
- if there are no Task nodes at all (for example every visible Person is unanchored), use a neutral deterministic origin/grid for the shelf;
- these coordinates are presentation-only and are never persisted;
- shelf position means only “no current Task anchor”. It must not encode closeness, family, hierarchy, authority, or social relation.

Keep constants named/documented so the later renderer can label/style this zone without reverse-engineering geometry.

## Tests

Add focused Flutter coverage proving at minimum:

1. controller retains PL1-C Task context exactly after an authoritative People workspace load;
2. controller replacement clears/replaces stale Task context rather than accumulating it;
3. complete one-Task Person lands at the position produced by `projectTaskMapHierarchy`;
4. complete multi-Task Person uses the centroid of the canonical Task positions;
5. genuinely unanchored Person is placed outside Task bounds;
6. unanchored Person does not change an anchored Person's position;
7. multiple unanchored People are non-overlapping and deterministic under reversed input order;
8. all-unanchored + empty complete Task context still yields a usable deterministic peripheral/neutral layout;
9. global Task context `complete=false` makes the projection unusable with no Person positions;
10. a Person with `landscapeTaskIdsComplete=false` makes the projection unusable with no partial positions;
11. a supposedly complete Person anchor missing from Task context makes the projection unusable with no partial centroid;
12. existing PL1-A tests continue to pass unchanged.

Run focused Flutter tests, relevant controller/workspace tests, relevant Flutter analyze, and `git diff --check`.

## Scope guard

Do not:

- change `GraphWorkspaceScreen` rendering;
- replace or modify `projectPeopleOverview`;
- show Task cards in People mode;
- add visual shelf labels yet;
- persist coordinates;
- change backend/API/schema;
- add migrations;
- deploy;
- build a human-gate bundle;
- change Task Graph layout semantics;
- start social/authority ontology;
- start Secretary Person context;
- start final Graph stabilization.

## Completion

1. Commit/push implementation to `main`.
2. Record exact implementation SHA and focused test results in `PROJECT_STATE.md`.
3. Return `CURRENT_TASK.md` to HOLD.
4. Report:
   - implementation SHA;
   - HOLD SHA;
   - files changed;
   - focused Flutter test result;
   - analyze result;
   - `git diff --check`;
   - confirmation People screen and production remain unchanged.
5. STOP.
