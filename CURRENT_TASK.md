# Current task — PL1-G3 client consumes canonical Task world-space

Authorized base: `2e98d2785b75a362e6b44089f4e383990b8f1b94`.
Production/runtime remains `666683134797948871266e84fd105f0ca0c43476`.
Repository Alembic head is `0052`; production Alembic remains `0051 / 0051`.

PL1-G2 is accepted. This slice makes the Flutter Task overview consume and, when required, produce the canonical persisted Task-center snapshot. It does **not** yet move People onto that world.

## Architectural invariant

There is one spatial world. Canonical Task centers define it. Task overview windows are subsets of that same world and must not repack the same Task differently because a different subset is loaded.

Persisted coordinates are Task **centers**. Rendering converts centers to card top-lefts according to the actual Task card size.

## 1. API/client contract

Add typed Flutter models and `SecretaryApiClient` methods for:

- `GET /graph/task-layout`;
- `PUT /graph/task-layout`;
- `GET /graph/task-layout/topology`.

Keep these separate from existing `GraphWorkspaceOut` / People workspace models.

Use one explicit client layout algorithm version constant for this producer, e.g. `task-map-v1`. Do not derive it from app version strings.

## 2. Canonical layout resolution

Add one bounded controller/helper path that resolves canonical Task centers for the unrooted Tasks overview.

Behavior:

1. Read `GET /graph/task-layout`.
2. If the returned snapshot is `usable=true` **and** its `algorithm_version` equals the current client layout algorithm version:
   - use its centers directly;
   - do not read topology;
   - do not recompute;
   - do not PUT.
3. Otherwise:
   - read `GET /graph/task-layout/topology`;
   - run the existing `projectTaskMapHierarchy` **once over that complete topology**, never over the current semantic-window subset;
   - convert every Task top-left to a center using the canonical Task card size;
   - PUT the complete center snapshot with the topology response's revision and current algorithm version;
   - install only the successful returned snapshot.
4. If PUT returns stale-revision conflict (409), perform at most one bounded re-read/recompute/retry cycle. A second conflict/failure must fail closed to the existing non-persisted Task overview behavior for that load and surface a non-destructive warning/error state; never loop.
5. Any malformed/incomplete client-side response must fail closed. Do not install partial centers.
6. Empty topology may persist an empty complete snapshot.
7. Do not calculate coordinates in backend code.

The old Task layout remains the temporary fallback only when canonical layout resolution fails. Fallback must not be persisted as if canonical unless it was computed from the complete topology endpoint and accepted by PUT.

## 3. Controller state

Store canonical Task centers separately from ordinary workspace `_positions`.

Expose read-only access suitable for rendering.

Clear canonical centers on session reset/auth reset. Do not discard them merely because:

- semantic overview window changes;
- Task search/filter changes;
- ordinary workspace reload occurs;
- title/body/due/status changes.

When backend topology revision changes, the next canonical layout resolution handles the stale snapshot through the contract above.

## 4. Task renderer

For unrooted Tasks overview only:

- Task cards use canonical persisted centers converted to top-lefts.
- The same Task id must have the same world position across semantic windows, filters, and rebuilds.
- Do not call `projectTaskMapHierarchy` on the current workspace subset when canonical centers are available.
- All Task cards, including ongoing/direction Tasks, remain at their canonical Task position. Hybrid/focus presentation may arrange Flow/satellite presentation around them, but must not relocate a Task anchor.
- Non-Task presentation may continue using existing hybrid/local derived geometry.
- Task relation semantics and card contents are unchanged.
- Manual Fit must fit the actual rendered scene based on canonical Task positions.
- Existing initial-load auto-fit may remain for now. Do not implement shared Tasks/People camera behavior in this slice.

Rooted Task view is unchanged in PL1-G3.

## 5. Preserve future single-world direction

Do not create a second world-space or People-specific coordinate store.

Do not add the future combined Tasks+People mode yet.

Do not redesign Person cards in this slice. The future People layer will consume the same Task centers.

## Explicitly out of scope

- No backend changes unless a tiny compatibility fix is strictly required and separately justified in PROJECT_STATE.
- No Alembic migration.
- No production migration/deploy.
- No People rendering changes.
- No People workspace contract cleanup.
- No shared Tasks/People viewport behavior yet.
- No combined view.
- No installed-client replacement.
- Do not start PL1-G4.

## Tests

Add focused Flutter tests proving at least:

- API models parse/serialize task-layout, replacement, and topology payloads;
- usable matching-version layout uses stored centers without topology read or PUT;
- stale/unusable layout reads complete topology, computes from `projectTaskMapHierarchy`, converts to centers, PUTs the full snapshot, and uses the accepted result;
- algorithm-version mismatch triggers one complete recompute even when backend says usable;
- first PUT 409 retries at most once; second conflict/failure does not loop and falls back safely;
- partial/malformed center set is never installed;
- same Task keeps the same rendered world position when the visible semantic-window subset changes;
- current-window unrelated membership no longer changes positions of Tasks with canonical centers;
- ongoing Task anchors are not moved by hybrid presentation;
- manual Fit uses the final canonical Task positions;
- rooted Task behavior remains unchanged;
- People overview behavior is unchanged in this slice.

Run focused Flutter API/controller/screen/layout tests, affected existing Graph regressions, `flutter analyze` for changed Dart files, and `git diff --check`.

## Completion contract

When complete:

- record implementation SHA, changed files, exact test/analyze/diff results, fallback behavior, and any known limitations in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-G3 summary;
- commit and push to `main`;
- STOP.

Do not deploy, migrate production, build a human-gate bundle, modify the installed client, or begin PL1-G4/later slices without a new explicit authorization in this file.
