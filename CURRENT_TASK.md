# Current task — PL1-B: bounded confirmed Task-anchor truth for People overview

## State

- PT1 Task↔Person bridge: COMPLETE / human accepted.
- PL1-A spatial primitive: ACCEPTED / source ready at `679c8af09073e768c39fd34dc1d0192706be347d`.
- Production application/runtime and `origin/production`: `44407ed6e972a05809d55874acaa966cc7e141c8`.
- Production Alembic: `0051 / 0051`.
- People overview currently does not expose the Task ids needed by PL1-A.
- People Landscape UI wiring and Task-geography context wiring are NOT yet authorized.

## Goal

Extend the existing People workspace read model so every returned Person carries a bounded, deterministic set of **confirmed canonical Task anchors** suitable for later People Landscape projection.

This slice is anchor truth only. Do not change the People screen or compute positions yet.

## Anchor semantics

A Task may anchor a Person only when all of the following are true:

- edge direction is canonical Task -> Person;
- edge type is one of:
  - `requested_by`
  - `delegated_to`
  - `waiting_on`
  - `involves`
- edge state is exactly `confirmed`;
- Task belongs to the current user;
- Task is active/read-visible;
- Task status is not terminal-for-reads.

Do NOT spatially anchor from:

- proposed actor edges;
- rejected actor edges;
- generic `related_to` or any non-actor edge;
- social/authority edges;
- terminal/inactive Tasks.

The same Task id must appear once even if multiple confirmed actor roles exist for that Person/Task.

## Read-model contract

Add to `PersonPresentation` (backend schema + client model) fields equivalent to:

- `landscape_task_ids: list[UUID]`
- `landscape_task_ids_complete: bool`

Semantics:

- `[] + complete=true` = genuinely unanchored Person;
- non-empty + `complete=true` = complete confirmed Task-anchor set;
- `complete=false` = the set was bounded/truncated and MUST NOT later be used to compute a partial centroid.

Use a deterministic per-Person cap:

`PEOPLE_LANDSCAPE_TASK_ANCHOR_CAP = 64`

If a Person has more than 64 distinct usable anchors:
- return the first 64 in deterministic Task-id order;
- set `landscape_task_ids_complete=false`.

For 64 or fewer:
- return all distinct ids in deterministic Task-id order;
- set `landscape_task_ids_complete=true`.

## Query discipline

Collect anchors in a bounded **batch** for all People being returned by the workspace result.

Do not add one Task-anchor query per Person.

The existing `task_involvement` detail surface remains unchanged and may still include proposed rows for review; it is not the spatial truth source.

The existing `open_task_count` semantics remain unchanged and must not be reused as the landscape anchor list.

## Backend / client scope

Expected touched areas may include:

- `backend/app/api/schemas.py`
- `backend/app/services/person_graph_workspace_service.py`
- focused People workspace tests
- `client/lib/api/api_models.dart`
- focused API/model tests as needed

Do not add a new endpoint in this slice.

Do not return Task geometry/nodes/edges yet.

## Tests

Add focused coverage proving at minimum:

1. one confirmed actor relation yields that Task id;
2. two confirmed roles on the same Person/Task yield one Task id;
3. two different confirmed Tasks yield two deterministic ids;
4. proposed actor relation does not anchor;
5. rejected actor relation does not anchor;
6. generic `related_to` does not anchor;
7. terminal-for-reads and inactive Tasks do not anchor;
8. no usable anchors returns `[]` with `complete=true`;
9. more than 64 distinct usable Tasks returns exactly 64 deterministic ids with `complete=false`;
10. multiple visible People are populated correctly by the shared batch path;
11. client parsing preserves ids and completeness exactly.

Run focused backend People workspace/truth tests, relevant Flutter model/API tests, Ruff, relevant Flutter analyze, and `git diff --check`.

## Scope guard

Do not:

- wire PL1-A into `GraphWorkspaceScreen` or `GraphWorkspaceController`;
- change `projectPeopleOverview`;
- add Task geography context to People workspace yet;
- compute or persist Person coordinates;
- deploy;
- build a human-gate bundle;
- change Task Graph layout semantics;
- start social/authority ontology;
- start Secretary Person context;
- start final Graph stabilization.

## Completion

1. Commit/push implementation to `main`.
2. Record exact implementation SHA, contract, cap and test results in `PROJECT_STATE.md`.
3. Return `CURRENT_TASK.md` to HOLD.
4. Report:
   - implementation SHA;
   - HOLD SHA;
   - files changed;
   - backend focused test result;
   - client focused test result;
   - Ruff/analyze result;
   - `git diff --check`;
   - confirmation People UI and production remain unchanged.
5. STOP.
