# Current task — Graph G1R: complete persisted edges among admitted workspace nodes

Release R1 is accepted and production remains exact:
`2a765d68ca8c7bc859e4902f00df6bb2d3b9bc6b`

Alembic remains:
`0050`

This task authorizes one bounded Graph corrective on `main` only.

NO production deploy is authorized.

Do not start S3 or H2D.

## Human evidence

On the exact R1/G1 client, the human selected the ongoing Direction:

`Создание курсов`

The new direct relation inventory, which reads `GET /objects/{id}/neighbors`, showed persisted confirmed user relations including:

- `Курс по траблшутингу —[входит в]→ Создание курсов`;
- `Создание курсов —[входит в]→ Основная работа`;
- a direct ordinary relation between `Создание курсов` and `Основная работа`.

The corresponding other endpoints are visibly present on the current Graph canvas.

For `Основная работа`, the relation inventory does NOT mark the endpoint `не на карте`.

Yet the structural `part_of` lines are absent from the canvas.

This proves:
- persistence truth exists;
- both endpoints are admitted to the current workspace;
- the workspace/canvas edge set is incomplete.

Do not inspect or mutate the user's production data to reproduce this.

## Root-cause hypothesis to verify

Current `GraphWorkspaceService` builds `edge_map` incrementally while:
- closing confirmed `part_of`;
- admitting ordinary neighbors.

After the final `node_map` is known, it only filters the already accumulated `edge_map` by endpoint membership.

It does NOT guarantee:

**for every persisted active/non-rejected relation whose source and target are both in the final admitted node set, the workspace response contains that edge.**

Verify this hypothesis with a minimal failing test before fixing it.

If the failing test disproves this hypothesis, identify the smallest actual cause and keep the same product invariant below.

## Product invariant

The Graph canvas is bounded by NODES, not by arbitrary omission of relations among already admitted nodes.

If both endpoints of a persisted active/non-rejected relation are already present in the workspace, the workspace edge set must include that relation, subject only to canonical relation visibility/state rules.

Node limits must remain unchanged.

Do not admit extra nodes merely to complete edges.

Client presentation may still intentionally hide canonical relation types through `presentGraphMapEdge`; backend workspace must not silently omit a persisted eligible edge merely because it was not encountered during node admission.

## Part A — backend final edge closure

Refactor `GraphWorkspaceService` so after the final node set is determined, the returned edge set is completed from persisted DB relations between those nodes.

Required behavior:

1. compute/finalize bounded `node_map` exactly as today;
2. query persisted edges for current user where:
   - `source_id` is in admitted node ids;
   - `target_id` is in admitted node ids;
   - edge state is not rejected;
3. merge those persisted edges into the returned edge set;
4. preserve proposed edges where existing product semantics already allow them;
5. never include another user's edge;
6. never use this edge closure to admit another node;
7. keep existing `node_limit`, `neighbor_limit`, seed behavior, G1 created_at ordering, and structural closure behavior unchanged.

Prefer one bounded query over per-node N+1 reads.

If there are existing special exclusions required for source/system/private relations, preserve them deliberately and cover them with tests rather than relying on traversal accident.

## Part B — explicit regression for visible endpoints + missing edge

Add a backend regression that fails on R1 behavior:

- create three Tasks: grandchild, child, parent;
- persist confirmed user `part_of` grandchild -> child;
- persist confirmed user `part_of` child -> parent;
- arrange the workspace so all three Task nodes are admitted;
- exercise the actual overview/rooted workspace path that previously can contain all nodes but omit one or both structural edges;
- assert the returned workspace contains BOTH `part_of` edges.

Also cover:
- a persisted `related_to` between two already-admitted Tasks appears in workspace edges;
- adding an eligible edge between already-admitted nodes does not change node membership;
- rejected edge between admitted nodes is not returned;
- another user's edge is not returned.

The test should make the distinction explicit:
`nodes complete -> edges must be complete among those nodes`.

## Part C — client drawing regression

Add focused client coverage using a workspace payload where:

- child Task and parent Task are both present;
- confirmed `part_of` edge is present;
- both are ongoing Directions in one case;
- finite/ongoing mixed case in another.

Prove:
- `focusLodEdgeIsVisible` does not hide Task<->Task edges;
- `presentGraphMapEdge` marks `part_of` visible, directed, structural;
- the Graph painter receives/draws the structural edge;
- selecting either endpoint does not remove the edge;
- Preserve/Relax mode does not change relation visibility.

Do not rewrite the painter unless the regression shows a separate client defect.

## Part D — parallel relation sanity

The human data currently contains both:
- `related_to`;
- `part_of`;

between the same two visible Task endpoints.

Do NOT delete or rewrite either relation.

Add one small test proving multiple persisted relation types between the same admitted endpoints are both returned by workspace.

If two coincident edges overlap visually, that is acceptable for G1R as long as the structural arrow remains visibly present.

Do not add parallel-edge routing in this task.

## Tests

Run relevant backend suites at minimum:

- `backend/tests/test_graph_workspace_g1.py`;
- `backend/tests/test_graph_workspace_part_of_closure.py`;
- `backend/tests/test_graph_workspace.py`;
- `backend/tests/test_graph_workspace_caps.py`;
- `backend/tests/test_relations_api.py`;
- new G1R regression file.

Run relevant client suites at minimum:

- graph workspace;
- workspace controller;
- map relation;
- part_of;
- hybrid/focus LOD;
- direct relation inventory.

Run Flutter analyze on touched files.

Run:
`git diff --check`

Linux debug build required.

Known pre-existing/baseline-dependent unrelated test failures already recorded in PROJECT_STATE are not authorization to modify unrelated code.

## Scope guard

Do NOT:
- inspect or mutate production user data;
- use bearer tokens;
- deploy backend/client;
- move `origin/production`;
- change Alembic/schema;
- change relation ontology;
- reverse `part_of`;
- remove duplicate user relations;
- add parallel-edge routing;
- change workspace node limits;
- add graph pagination;
- add AI/salience ranking;
- fold in `SECRETARY_API_BASE_URL` precedence;
- start S3;
- start H2D;
- fix unrelated failures.

If the actual minimal reproduction shows persisted edges are being rejected/deleted rather than merely omitted from workspace, STOP and report that exact integrity path instead of implementing this presentation corrective.

## Completion

On completion:

1. update `PROJECT_STATE.md` with confirmed root cause, implementation SHA, exact tests/results, and rollout requirement;
2. return `CURRENT_TASK.md` to HOLD;
3. push normal implementation/HOLD commits to `main`;
4. do not deploy;
5. STOP.

Final report must state:

- confirmed root cause;
- failing regression reproduced before fix;
- final edge-closure behavior;
- `part_of` visible-endpoint regression result;
- multiple-relation same-endpoint result;
- backend tests;
- client tests/analyze/build;
- implementation SHA;
- HOLD/main SHA;
- whether G1R can be deployed schema-neutrally from current production.

Then STOP. Do not choose the next task yourself.
