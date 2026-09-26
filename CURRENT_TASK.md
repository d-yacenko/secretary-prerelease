# Current task — Task Map V8E1: bounded confirmed part_of workspace closure

Relation Direction V8D1 is accepted as a code-level audit. Do not start relation-row repair or direction migration.

This phase completes the backend read model needed by the already accepted V8B2 radial Task hierarchy.

Backend Graph workspace only. No client production-code changes are expected. No schema/migration. No production deploy. People workspace is out of scope.

## Problem

`GraphWorkspaceService` currently returns:
- overview: active Task seeds plus one generic neighbor hop;
- rooted workspace: the root plus one generic neighbor hop.

The client V8B2 renderer can draw a multi-level confirmed `part_of` hierarchy, but it can only draw nodes returned by the workspace API. A grandchild or ancestor beyond the current one-hop expansion can therefore be absent.

## Required behavior

Add a deterministic, bounded closure over **confirmed Task->Task `part_of` edges**.

Canonical composition remains:
- child/source -> parent/target;
- one active parent per child is enforced elsewhere;
- traversal for workspace visibility is bidirectional so the user can see hierarchy context from any task in the tree;
- renderer direction remains child -> parent.

### Rooted workspace

When `root_id` is a Task:

1. Start with the root as today.
2. Before ordinary generic neighbor expansion, traverse the connected component formed only by:
   - `Edge.type == "part_of"`;
   - `Edge.state == confirmed`;
   - both endpoints kind `task`;
   - same user;
   - visible/non-rejected endpoints;
   - deleted/tombstoned neighbors excluded under the same active-neighbor rule used by the current workspace.
3. Traverse both outgoing parent edges and incoming child edges until:
   - the confirmed composition component is exhausted, or
   - `node_limit` is reached.
4. Include every traversed confirmed `part_of` edge whose two endpoints are included.
5. Then spend any remaining node budget on the existing ordinary one-hop neighbor expansion from the **original root only**.

If the root is not a Task, rooted behavior stays exactly as it is now.

### Overview workspace

1. Fetch the existing active Task seeds exactly as today. Do not change seed ordering, seed eligibility, or `seed_ids`.
2. Before ordinary generic neighbor expansion, compute the union of the confirmed `part_of` components reachable from those original seed Tasks.
3. Add hierarchy Tasks/edges within the global `node_limit`.
4. Then spend remaining budget on the existing ordinary one-hop neighbor expansion from the **original seed_ids only**.

Do not turn hierarchy-added Tasks into new generic Flow-expansion centers in V8E1. This avoids an accidental recursive Flow explosion.

## Priority and limits

Confirmed composition context has priority over ordinary Flow neighbors inside the existing global `node_limit`.

The existing `neighbor_limit` applies to the ordinary one-hop neighbor expansion. It must NOT truncate confirmed composition closure per parent.

Closure must still be bounded by `node_limit`; never exceed the existing maximum.

Set `truncated = true` when eligible confirmed hierarchy nodes/edges exist beyond the available node budget.

Keep existing truncation behavior for seeds and ordinary neighbors.

## Determinism

Traversal/output must be deterministic for identical database state.

Prefer a simple breadth-first traversal:
- initial frontier follows existing root/seed order;
- hierarchy edges are processed in a stable order (edge id is acceptable);
- each Task is added at most once;
- each edge is added at most once.

Do not add a recursive SQL dependency if a small bounded iterative implementation is clearer and easier to test.

## Important state semantics

Only **confirmed** `part_of` drives closure.

- proposed `part_of`: MUST NOT pull another Task into the workspace solely through hierarchy closure;
- rejected `part_of`: MUST NOT pull another Task into the workspace;
- proposed edges may still appear through the existing generic one-hop behavior when both endpoints are otherwise reached; do not broaden this phase to redesign edge inclusion.

Do not change V8B2's client rule that only confirmed `part_of` moves Task geography.

## Preserve existing contracts

Do not change:
- `GET /graph/workspace` request/response schema;
- default/max seed, neighbor, or node limits;
- seed ranking/order;
- root behavior for non-Task objects;
- user isolation;
- Telegram active-visibility predicates;
- deleted-object policy;
- relation direction or type semantics;
- Task Profile;
- People workspace/service;
- Flutter layout, shell, painters, proposal cues, or transforms.

No new dependency.

## Tests

Add focused backend tests proving at minimum:

1. rooted Task at hierarchy root returns child and grandchild through confirmed `part_of` even when the grandchild is more than one generic hop away;
2. rooted Task at a descendant traverses upward to parent/ancestor and can reach the rest of the same confirmed tree within budget;
3. overview seed includes a depth-2 confirmed hierarchy even when descendants are not selected as seeds;
4. hierarchy closure is not capped by a small `neighbor_limit`;
5. proposed `part_of` alone does not expand hierarchy;
6. rejected `part_of` does not expand hierarchy;
7. non-Task root behavior remains one-hop as before;
8. ordinary one-hop neighbors are still added after hierarchy closure when budget remains;
9. node_limit is never exceeded;
10. hierarchy overflow sets `truncated=true`;
11. repeated calls return the same node/edge ids/order;
12. no duplicate node or edge ids;
13. every returned edge still has both endpoints in returned nodes;
14. user isolation remains intact;
15. existing overview seed behavior/caps tests remain green.

Also run existing:
- `backend/tests/test_graph_workspace.py`;
- `backend/tests/test_graph_workspace_active_seeds.py`;
- `backend/tests/test_graph_workspace_caps.py`;
- `backend/tests/test_task_composition.py`;
- any focused Graph workspace tests affected by the helper.

Run Ruff/format checks used by the repo and `git diff --check`.

Because this phase should not change Flutter production code, do not run a Linux Flutter build unless you unexpectedly touch client production code. If you do touch it, explain why and run the relevant client tests/analyze/build.

## Completion

Record in `PROJECT_STATE.md`:
- implementation SHA;
- exact closure ordering/limit behavior;
- rooted and overview semantics;
- proposed/rejected behavior;
- test counts;
- whether client code changed.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start relation repair/migration.
Do not start V8E2.
Do not deploy production.
