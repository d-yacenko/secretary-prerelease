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
- the initial overview workspace/canvas edge set is incomplete.

Additional human evidence BEFORE Executor start:

- with `Создание курсов` still selected, the human pressed `Показать связи`;
- the previously missing structural arrows immediately appeared;
- no relation was created or edited during that action.

Code path already verified:

`Показать связи -> GraphWorkspaceController.expandSelected() -> GET /graph/workspace?root_id=<selected> -> _mergeWorkspace(...)`

This is NOT a painter visibility toggle. It fetches a rooted workspace and merges its returned nodes/edges into the existing overview.

Therefore the product reproduction is now stronger:

**overview contains the visible Task endpoints but omits one or more persisted edges; rooted workspace for one endpoint returns those edges; merging the rooted response makes the existing renderer draw them.**

The renderer/LOD is therefore already capable of drawing these edges once they are in the controller edge set.

Do not inspect or mutate the user's production data to reproduce this.

## Root cause to reproduce precisely

Current `GraphWorkspaceService` builds `edge_map` incrementally while:
- closing confirmed `part_of`;
- admitting ordinary neighbors.

After the final `node_map` is known, it only filters the already accumulated `edge_map` by endpoint membership.

The human behavior strongly indicates an overview/rooted divergence caused by that traversal-dependent edge accumulation:

- overview: endpoints present, edge absent;
- rooted workspace around selected endpoint: edge present;
- client merge: edge becomes visible without any write.

Before implementing the fix, add a minimal regression that reproduces this divergence against the service/API:

1. obtain an overview workspace in which the relevant Task endpoints are admitted;
2. assert a persisted eligible edge between those admitted endpoints is missing from the overview response;
3. request the rooted workspace for one endpoint;
4. assert the same persisted edge is returned there.

Then fix the service so step 2 is no longer possible.

If a clean minimal fixture cannot reproduce the traversal-dependent omission, inspect the exact overview seed/admission path and identify the smallest equivalent service-level case. Do not pivot to painter/LOD work: the human evidence proves the renderer draws the edge after rooted merge.

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

## Part C — client regression: Show relations must not be required for an already-admitted edge

The human evidence proves the existing renderer can draw the structural edge after `expandSelected()` merges a rooted workspace.

Add focused client/controller coverage for the contract, not a painter rewrite:

- initial overview payload contains child + parent Task and the eligible persisted `part_of` edge -> structural edge is visible immediately;
- selecting an endpoint alone does not remove it;
- calling `expandSelected()` with a rooted response containing the same edge does not duplicate it;
- finite/ongoing presentation does not change relation visibility;
- Preserve/Relax does not change relation visibility.

Keep the existing low-level assertions that:
- `focusLodEdgeIsVisible` retains Task<->Task edges;
- `presentGraphMapEdge` marks `part_of` visible, directed, structural.

Do NOT change painter/LOD unless these regressions expose a separate failure after backend workspace edge closure.

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
