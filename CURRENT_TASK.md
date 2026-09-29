# Current task — PL1-G1 canonical Task geography persistence foundation

Authorized base: `b0370046ccd3e220e271f7c39b418ea251e200c5`.
Production/runtime remains `666683134797948871266e84fd105f0ca0c43476`.
Production Alembic remains `0051 / 0051`.

This task supersedes the previously authorized but unstarted “PL1-G Task-window geography parity” approach. Do not implement semantic-window tiling.

## Goal

Add the backend persistence foundation for one canonical Task world-space layout. This slice establishes storage and revision semantics only. It must not change the Task or People UI yet.

## Canonical invariants

- Persist Task **center coordinates** in one user-scoped world coordinate system.
- Coordinates are presentation state, not semantic truth. Do not put them in `Object.metadata`.
- People do not receive persisted coordinates.
- Ordinary reads and ordinary Task field edits must not rewrite coordinates.
- The persistence layer must support explicit topology invalidation and atomic replacement of a complete layout snapshot.
- Stale/incomplete layout state must be detectable and fail closed.
- No layout algorithm is moved to the backend in this slice.

## Scope

1. Add Alembic migration `0052` for dedicated Task layout persistence.
2. Add SQLAlchemy models for:
   - one user-scoped Task layout state row containing at least:
     - `user_id`;
     - monotonically increasing `topology_revision`;
     - nullable/current `snapshot_revision`;
     - nullable `algorithm_version`;
     - timestamps;
   - Task layout positions containing at least:
     - `user_id`;
     - `task_id`;
     - finite `world_x` / `world_y` center coordinates;
     - the snapshot revision they belong to;
     - timestamps.
3. Use explicit PK/unique/FK/index constraints consistent with repository ownership patterns. Deleting a Task/user must not leave orphan layout rows.
4. Add a focused backend service (for example `TaskLayoutService`) with these internal operations:
   - read state/snapshot;
   - atomically replace the stored position snapshot for an expected `topology_revision`;
   - explicitly invalidate topology by incrementing `topology_revision`;
   - expose whether the stored snapshot is current/usable.
5. Snapshot replacement must fail closed:
   - reject stale expected revision;
   - reject duplicate Task ids;
   - reject non-Task or foreign-user ids;
   - reject non-finite coordinates;
   - never partially install a snapshot on validation failure.
6. A successful replacement must make `snapshot_revision == topology_revision` and store the supplied `algorithm_version`.
7. Invalidation must make the previous snapshot stale without deleting it. Coordinates remain available for diagnostics/possible future stable recomputation, but `usable == false` until a new snapshot for the current revision is installed.
8. Migration upgrade/downgrade must be deterministic and reversible.

## Explicitly out of scope for PL1-G1

- Do not wire topology invalidation into relation mutation paths yet.
- Do not add public API endpoints yet.
- Do not change `GraphWorkspaceOut` / `PeopleWorkspaceOut`.
- Do not change Flutter models/controllers/renderers.
- Do not change `projectTaskMapHierarchy`.
- Do not calculate or backfill production coordinates.
- Do not deploy or run the migration on production.
- Do not change production data or installed client.
- Do not start PL1-G2.

## Tests

Add focused backend tests proving at least:

- a user gets isolated layout state;
- valid complete snapshot replace/read round-trips exact centers;
- replacement at a stale expected topology revision fails with no partial writes;
- duplicate/foreign/non-Task ids fail closed;
- NaN/infinite coordinates fail closed;
- invalidation increments topology revision and makes the previous snapshot unusable while leaving stored rows intact;
- replacement after invalidation installs a new usable snapshot at the new revision;
- different users cannot read or overwrite each other’s layout state;
- migration head becomes `0052`.

Run the focused backend tests, relevant model/migration tests, and `git diff --check`.

## Completion contract

When complete:

- record implementation SHA, migration name/head, changed files, exact test results, and any known limitations in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-G1 summary;
- commit and push to `main`;
- STOP.

Do not deploy, do not migrate production, and do not begin PL1-G2 or later slices without a new explicit authorization in this file.
