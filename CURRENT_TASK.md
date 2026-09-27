# Current task — Graph G1: stable relation truth + structural hierarchy visibility + visual relation chooser

Task/Direction S2R is ACCEPTED.

S2R implementation:
`f2469610e188072b7695b4dc43426e018a645f65`

Current production remains:
`fd45df20ff53ad973f22e461ff84f3cb5c251b8a`

Do NOT deploy production in this task.

This is one bounded Graph corrective discovered by the human while building a real Task/Direction tree.

Do not start S3 or H2D.

## Human evidence

The human created a Task/Direction relation and observed:

- manual relation creation reported success;
- the relation was visible immediately and after an initial revisit;
- after Secretary attached another related object, the previous Task/Direction connection was no longer visible on the Graph;
- a set that had shown five publication/evidence neighbors later appeared as four;
- the Graph banner already said that some related objects were hidden by the workspace limit.

Do not assume database loss from this observation.

Current code review shows:
- direct user relation creation writes `origin=user`, `state=confirmed`;
- successful API request sessions commit;
- Graph workspace defaults are seed=12, neighbor=12, node=80;
- ordinary neighbor membership is ranked by `edge_id` UUID;
- confirmed `part_of` closure is prioritized for initial root/seeds;
- a Task admitted later through ordinary neighbor expansion does not receive the same recursive structural closure;
- the desktop detail pane currently derives its visible relation list from current workspace edges;
- `GET /objects/{object_id}/neighbors` already provides direct relation truth independently of bounded Graph workspace projection.

## Architectural invariant

The Graph canvas is a bounded projection.

It must never be presented as the authoritative existence/non-existence of a relation.

Canonical relation truth comes from persisted edges.

Confirmed `part_of` is structural Task composition and must have stronger visibility guarantees than optional Flow/context neighbors.

Canonical `part_of` direction remains:

`child/source -> parent/target`

Do not reverse or reinterpret it.

Accepted relation grammar remains:

- `related_to`: solid, undirected;
- `references`: light solid directed arrow source -> target;
- `depends_on`: dashed directed arrow dependent/source -> prerequisite/target;
- `part_of`: stronger structural solid arrow child/source -> parent/target.

## Part A — prove persistence truth separately from canvas projection

Add focused backend/client tests that reproduce the human class of symptom without production data:

1. create two Tasks with a confirmed user `part_of`;
2. verify the relation through direct relation/neighbors readback;
3. add enough ordinary related/reference neighbors to trigger workspace truncation;
4. refresh/re-enter Graph workspace;
5. prove the persisted `part_of` edge still exists even if a bounded projection would otherwise omit an endpoint.

The test must distinguish:
- relation persisted;
- relation currently drawn on canvas.

Do not write a test that treats canvas membership as persistence truth.

## Part B — structural part_of must not be displaced by ordinary neighbor limits

Refine `GraphWorkspaceService` so confirmed Task `part_of` hierarchy has structural priority.

Required behavior:

- for a rooted Task, recursively close its confirmed active `part_of` component before ordinary neighbors;
- for overview seeds, do the same;
- if an additional Task is admitted later through ordinary neighbor expansion, its confirmed `part_of` component must also be closed before spending remaining budget on further optional ordinary neighbors;
- ordinary `neighbor_limit` must not hide a confirmed `part_of` edge whose Task endpoints fit inside `node_limit`;
- adding a new `references`, `related_to`, or other ordinary edge must not make an already-visible structural Task/Direction hierarchy disappear when `node_limit` still has room;
- overall `node_limit` remains authoritative; do not make workspace unbounded;
- if structural closure itself reaches the node limit, keep `truncated=true`; do not silently exceed the bound.

Do not create a second hierarchy model or cache.

## Part C — remove UUID-only ordinary neighbor membership

The current ordinary-neighbor ranking uses `edge_id` UUID, so adding a relation can arbitrarily change which existing neighbors fall inside the first N.

Replace UUID-only product membership ordering with a deterministic monotonic ordering.

For this task use:

`Edge.created_at ASC, Edge.id ASC`

for ordinary eligible neighbor candidates after existing eligibility filters.

The important invariant is:

**appending a newer unrelated ordinary edge must not evict an older already-visible ordinary edge solely because of UUID ordering.**

Do not add salience/AI ranking in this task.

## Part D — selected-object relation inventory must show relation truth, not only canvas edges

For the selected Graph object, use the existing:

`GET /objects/{object_id}/neighbors`

to load the direct relation inventory independently of the canvas workspace.

The desktop/mobile detail relation section must:

- show every direct relation returned by this canonical neighbors read;
- show relation semantic text/direction using the existing accepted relation grammar;
- remain able to show a relation even when the other endpoint is not currently drawn on the canvas;
- visually distinguish `не на карте` / equivalent when the related endpoint is outside the current bounded workspace;
- allow opening/centering that related object using the returned neighbor object id;
- keep proposal decision/removal actions only where already allowed by existing provenance rules.

Do not duplicate edges if the same relation is already in the workspace.

Do not make the whole canvas unbounded just to make the detail pane complete.

If the neighbors request fails, keep the Graph usable and show a bounded relation-section error/retry state; do not erase the canvas.

## Part E — truncation must stop looking like data loss

Keep the existing workspace limit warning, but make the wording explicit that:

- the canvas is showing only part of the graph;
- hidden relations/objects may still exist;
- the selected object's full direct relation list is available in the detail pane.

Do not claim an exact hidden count unless the API actually provides enough information to compute it correctly.

## Part F — visual relation chooser

Improve the `Добавить связь` type selector so the human does not have to remember abstract text labels.

For each available relation option show:

1. the relation name;
2. a compact mini-line preview using the SAME presentation semantics as `presentGraphMapEdge`;
3. one short directional meaning.

Required meanings:

- `Связано с` — symmetric association;
- `Ссылается на` — source -> referenced target;
- `Зависит от` — dependent/source -> prerequisite/target;
- `Входит в` — child/source -> parent/target.

The preview must reuse/shared-drive the accepted grammar rather than invent a parallel style table.

For `part_of`, keep the existing explanatory sentence that the selected Task enters the selected parent Task, but make the visual arrow reinforce child -> parent.

Do not add new relation types.

## Tests

Backend focused tests must include at least:

- confirmed `part_of` survives >neighbor_limit ordinary neighbors;
- a Task admitted as an ordinary neighbor brings its confirmed `part_of` component into the workspace when node budget allows;
- adding a newer ordinary edge does not evict an older visible ordinary edge under the new ordering;
- `truncated` remains true when limits are genuinely exceeded;
- direct neighbors readback still returns the persisted relation independently of workspace truncation.

Client focused tests must include at least:

- selected detail relation inventory includes a direct persisted relation absent from current workspace edges;
- out-of-canvas relation is marked as such;
- centering/opening an out-of-canvas neighbor uses its id correctly;
- Graph remains usable if relation-inventory load fails;
- truncation warning explains projection vs persistence;
- all four relation chooser options render the correct mini-preview semantics;
- `part_of` preview/direction is child -> parent;
- existing proposed relation confirm/reject/remove behavior is not regressed.

Run existing relevant:
- backend Graph workspace/caps/part_of/relations tests;
- client Graph workspace/controller/map relation/part_of/proposed relation/hybrid tests.

Run Flutter analyze on touched files and `git diff --check`.

Linux debug build required.

## Scope guard

Do NOT:

- inspect or mutate production data;
- use the user's bearer token;
- deploy backend or client;
- move `origin/production`;
- change Alembic/schema;
- change the four canonical relation types;
- reverse relation direction;
- add global graph pagination/virtualization;
- add AI/salience ranking;
- change Task/Direction ontology;
- fold in the separate `SECRETARY_API_BASE_URL` precedence issue;
- start S3;
- start H2D;
- fix unrelated failures.

If you discover evidence that persisted confirmed user relations are actually being deleted by some existing code path, STOP and report the exact bounded code path/test reproduction instead of broadening scope.

## Completion

On completion:

1. update `PROJECT_STATE.md` with root cause, implementation SHA, exact tests/results, and whether any backend/client application rollout is required;
2. return `CURRENT_TASK.md` to HOLD;
3. push normal implementation/HOLD commits to `main`;
4. do not deploy;
5. STOP.

Final report must state:

- whether the human symptom was reproduced as projection/truncation rather than DB deletion;
- structural `part_of` closure behavior after the fix;
- ordinary-neighbor ordering change;
- direct relation inventory behavior;
- truncation UX wording;
- relation chooser visual grammar;
- backend tests;
- client tests/analyze/build;
- implementation SHA;
- HOLD/main SHA;
- whether S2R + G1 can be rolled out together schema-neutrally.

Then STOP. Do not choose the next task yourself.
