# Current task — PL1-C: bounded Task-geography context for People workspace

## State

- PT1 Task↔Person bridge: COMPLETE / human accepted.
- PL1-A spatial primitive: ACCEPTED at `679c8af09073e768c39fd34dc1d0192706be347d`.
- PL1-B anchor truth + H1: ACCEPTED / source ready at `cafcf5627ac4051ebe0deeaba3a08f72f96571c6`.
- Production application/runtime and `origin/production`: `44407ed6e972a05809d55874acaa966cc7e141c8`.
- Production Alembic: `0051 / 0051`.
- People UI still uses the old ranked grid.
- PL1 spatial UI wiring is NOT authorized in this slice.

## Goal

Extend the existing People workspace read model with a separate bounded **Task-geography context** that later lets the client run the existing `projectTaskMapHierarchy` and then PL1-A.

Do not compute Person coordinates and do not change the People screen yet.

## Response contract

Add fields equivalent to these on `PeopleWorkspaceOut` and the Flutter `GraphWorkspaceOut` model:

- `landscape_tasks: list[ObjectOut]`
- `landscape_task_edges: list[EdgeOut]`
- `landscape_task_context_complete: bool`

These fields are separate from ordinary People `nodes/edges`.

Semantics:

- empty tasks/edges + `complete=true` is valid when there are no complete usable Person anchors;
- non-empty + `complete=true` is a complete bounded Task context for the complete anchor sets in this People response;
- `complete=false` means the context must NOT later be used for Person projection;
- whenever `complete=false`, return **no partial Task context**: both task and edge arrays must be empty.

## Which Person anchors request context

Use only a Person's PL1-B anchor list when:

`landscape_task_ids_complete == true`

If a Person has `landscape_task_ids_complete == false`, ignore that Person's returned partial ids entirely for context membership. That Person is not placeable yet and must never cause a partial centroid later.

Union the distinct anchor ids from the complete Person anchor sets in the current People response.

## Task-context membership

For each requested anchor Task:

1. Resolve it inside the same visible Task universe used by `GraphWorkspaceService`.
2. Find the confirmed-`part_of` Task constellation containing it.
3. Include the **full Task-only constellation**: root plus all visible Task descendants in that confirmed `part_of` tree.
4. Include terminal Task members when they are part of such an active anchor constellation. They are presentation context, not Person anchors.
5. Union/deduplicate constellations across all requested anchors.

Do not include Flow/Person/Label objects in `landscape_tasks`.

The implementation should live in/reuse `GraphWorkspaceService` rather than duplicate Task visibility / confirmed-`part_of` forest semantics inside `PersonGraphWorkspaceService`.

Use one shared Task visibility/forest pass for the anchor set; do not perform one workspace query per Person or per anchor.

## Task edges

Return Task↔Task edges whose endpoints are both in `landscape_tasks`, using the existing Graph workspace edge-completion semantics.

Requirements:

- rejected edges stay excluded;
- confirmed `part_of` is present for hierarchy;
- other existing Task↔Task presentation relations among the included Tasks remain available for the later existing client projector;
- do not invent or rewrite edge types;
- Person actor edges cannot appear because Person nodes are not in this context.

Order tasks deterministically by Task id and edges deterministically by edge id in the response.

## Bounded / fail-closed contract

Define:

`PEOPLE_LANDSCAPE_TASK_CONTEXT_CAP = 500`

The cap counts distinct Task nodes after full anchor-constellation expansion.

If expansion would exceed the cap:

- `landscape_tasks = []`
- `landscape_task_edges = []`
- `landscape_task_context_complete = false`

Do not truncate to the first N Tasks.

If any requested anchor cannot be resolved inside the Task-visible universe, also fail closed with empty context + `complete=false`.

This is intentionally different from PL1-B's per-Person 64-id diagnostic cap: partial Task geometry is never valid.

## Important geography rule

Do not return coordinates.

The client will later derive canonical Task presentation coordinates by calling the existing:

`projectTaskMapHierarchy(nodes: landscapeTasks, edges: landscapeTaskEdges)`

PL1-C only transports the complete structural context required for that later projection.

Do not introduce a second Task layout algorithm on the backend.

## Tests

Add focused backend coverage proving at minimum:

1. no complete usable Person anchors -> empty context with `complete=true`;
2. one anchor in a confirmed `part_of` tree returns the full Task tree, not only the anchor;
3. a sibling/parent in that tree is present even when it is not itself a Person anchor;
4. a terminal Task member of an otherwise active anchor constellation is present as geometry context;
5. multiple anchors in one constellation do not duplicate Tasks;
6. anchors in two constellations return the deterministic union;
7. Task↔Task edges among returned Tasks are present and rejected edges are absent;
8. no Person/Flow object appears in `landscape_tasks`;
9. a Person whose `landscape_task_ids_complete=false` contributes none of its partial ids;
10. unresolved requested anchor fails closed with empty arrays + `complete=false`;
11. cap overflow fails closed with empty arrays + `complete=false` rather than partial geometry;
12. Flutter parsing preserves tasks, edges, and completeness exactly.

It is acceptable for a focused service-level test to use a reduced injected/monkeypatched cap rather than create 501 fixture Tasks, as long as production constant remains 500.

Run:
- focused new PL1-C backend tests;
- existing PL1-B anchor tests;
- relevant Graph workspace / `part_of` tests;
- focused Flutter API/model tests;
- Ruff;
- relevant Flutter analyze;
- `git diff --check`.

## Scope guard

Do not:

- change `projectPeopleOverview`;
- call `projectPeopleFromTasks` from the screen/controller;
- change People rendering;
- implement the unanchored shelf/halo yet;
- persist coordinates;
- add a new endpoint;
- add a migration;
- deploy;
- build a human-gate bundle;
- change Task Graph layout semantics;
- start social/authority ontology;
- start Secretary Person context;
- start final Graph stabilization.

## Completion

1. Commit/push implementation to `main`.
2. Record exact implementation SHA, context contract, cap and tests in `PROJECT_STATE.md`.
3. Return `CURRENT_TASK.md` to HOLD.
4. Report:
   - implementation SHA;
   - HOLD SHA;
   - files changed;
   - backend focused results;
   - Flutter focused result;
   - Ruff/analyze;
   - `git diff --check`;
   - confirmation People UI and production remain unchanged.
5. STOP.
