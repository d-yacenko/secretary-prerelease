# Current task — GR1 relation repairability + attached-endpoint visibility

Authorized base: `a8925c21449c68cdd0708012529513612f4b4190`.

Production remains `1b6943ba4f7cc49df1465791d812d45db6d26b52`, Alembic `0052 / 0052`.

TL2.2 is HUMAN-ACCEPTED and CLOSED. Canonical Task layout remains `task-map-v2.2`.

This slice addresses two relation-management defects observed on the live Publications graph:

1. old confirmed agent-created relations are visible in the inspector but cannot be removed/corrected, so a wrong directed edge cannot be repaired from the UI;
2. a proposed relation can be listed in the inspector while its active endpoint is absent from the current canvas, which reads as a missing/broken relation even though the endpoint exists outside the current workspace.

## Verified current root causes

### Confirmed agent relations are a dead end

Client `_relationTrailing` currently exposes:
- confirm/reject only for `origin=agent, state=proposed`;
- delete only for `origin=user`;
- no action for `origin=agent, state=confirmed`.

Backend `DELETE /relations/{edge_id}` also rejects non-user origins.

However the domain already has the intended removal semantics in `relation_removal.py` / Assistant `remove_relation`:
- user/agent semantic relations are removable;
- removal deactivates the edge to `state=rejected`, preserving provenance;
- source/system and protected structural types remain protected.

The Graph UI and direct relation API therefore lag behind the existing domain correction model.

### “Relation exists but object is not on the map” — corrected diagnosis

`_DirectRelationInventory` calls `GET /objects/{object_id}/neighbors` and can therefore know about active direct neighbors absent from `controller.nodes`.

The live `Program_DYSC.pdf` case is not merely an inspector-labeling problem. The backend semantic overview currently builds each Task constellation from:
- all Tasks in the confirmed visible Task component;
- `_priority_flows_for_tasks()`.

But `_priority_task_flow_buckets()` currently requires `Edge.state == confirmed`.

Therefore an active **agent-proposed Task↔Flow/object relation is categorically omitted from unrooted semantic overview membership**, even though:
- the relation is active/non-rejected;
- the endpoint itself is active/readable;
- the inspector can see it through `/neighbors`.

This explains why `Program_DYSC.pdf` is absent from both overview pages rather than merely sitting in another area.

That is the defect. A normal direct visible relation must not exist only in the inspector while its non-Task endpoint is systematically absent from the canvas.

## Goal

Make direct relations human-repairable and make off-context relations self-explanatory, without introducing in-place relation editing.

For this slice, correcting type/direction is deliberately:
1. remove/deactivate the wrong relation;
2. create the correct relation with the existing “Добавить связь” flow.

Do NOT add a type/direction editor.

## A. Human removal of confirmed agent semantic relations

### UI behavior

For a direct relation in the inspector:

- `agent + proposed`:
  - keep current Confirm / Reject controls unchanged;
- `user + confirmed`:
  - keep current “Удалить связь” behavior through `DELETE /relations/{edge_id}`;
- `agent + confirmed` and relation is removable by the canonical domain rule:
  - show the same user-facing “Удалить связь” action;
  - require the same confirmation dialog;
  - execute a human rejection/deactivation, NOT physical deletion;
  - after success the relation disappears from the active inspector/map;
- source/system relations:
  - no generic removal action;
- protected relation types:
  - no generic removal action.

Use the canonical removal allowlist/semantics from backend `relation_removal.py`:
- removable semantic types include `references`, `related_to`, `depends_on`, `part_of`, `requested_by`, `delegated_to`, `waiting_on`, `involves`;
- `contains` and `labeled_with` remain protected;
- source/system origins remain protected.

Do not silently make all edges deletable.

### Backend behavior

Extend the existing human relation decision/removal path so an **agent-origin confirmed removable semantic edge** can be explicitly rejected by the user.

Preferred bounded contract:
- keep `POST /relations/{edge_id}/decision`;
- allow `decision=reject` for `origin=agent, state=confirmed` only when the edge is removable by the canonical `relation_removal` rule;
- preserve the edge row and set `state=rejected`;
- return the updated edge through the existing response shape.

Do NOT allow:
- confirmed agent -> confirmed no-op “confirm”;
- rejected -> anything;
- user/source/system edges through this agent-decision path;
- protected types through this correction path.

Do not globally weaken provenance state transitions for unrelated call sites. Keep the exception explicit to human correction of a removable confirmed agent relation.

Critically, the transition must invalidate Task-map topology when the edge participates in canonical Task geography, exactly as current proposed confirm/reject does. Do not copy the old Assistant helper’s bare state assignment if that would skip `note_task_map_participation_change`.

### Direction repair scenario

Regression fixture matching the user case:
- agent-created confirmed directed Task↔Task edge has source/target reversed;
- inspector exposes “Удалить связь”;
- user confirms;
- backend returns the same edge as rejected;
- active Graph removes the edge and canonical topology/layout refresh occurs;
- user can then use existing “Добавить связь” to create the desired opposite-direction edge.

No automatic reverse action is required.

## B. Attached relation endpoints must be visible by default

### Product invariant

For an admitted Task in Tasks overview, every active readable non-Task endpoint attached through a normal visible semantic Task relation must be admitted to the same overview constellation when the relation is active.

At minimum this applies to Task↔non-Task edges with:
- type `references`, `related_to`, or `depends_on`;
- origin `user` or `agent`;
- state `confirmed` **or `proposed`;
- active/readable non-Task endpoint.

Rejected edges do not admit endpoints.

This is presentation/read completeness only:
- a proposed edge must NOT join two Task semantic components;
- a proposed edge must NOT influence canonical Task centers;
- `part_of` structural semantics are unchanged;
- Person/actor-role, label, temporal, source/system structural relations are not broadened by this rule.

The concrete `Program_DYSC.pdf` behavior must become:
- selected/visible publication Task is in area 1;
- the active PDF endpoint is directly connected by an agent-proposed visible relation;
- the PDF node is therefore present on the same canvas automatically;
- the proposed edge/diamond is visible without opening the inspector first.

No extra “Показать на карте” click is required for this normal case.

### Backend overview admission

Generalize the existing Task↔Flow priority admission so both confirmed and proposed user/agent visible semantic evidence endpoints are carried with their Task component.

Requirements:
- preserve deterministic ordering;
- confirmed-before-proposed ordering is preferred when a deterministic state tie-break is needed, but **all** eligible endpoints under the emergency ceiling must be admitted;
- the soft window target may be exceeded to keep a Task semantic component together with its attached visible endpoints, exactly as SW2-A already keeps a component whole;
- shared non-Task endpoints may appear in more than one semantic window when they are genuinely linked to Tasks in different components; they must not glue those Task components together;
- if the complete component plus attached endpoints exceeds the existing emergency ceiling, preserve the explicit fail-closed error. Do not silently hide proposed endpoints.

Do not change the `task-map-v2.2` algorithm/version: non-Task endpoints do not participate in canonical Task center persistence.

### Rooted workspace

A rooted Task workspace should likewise not systematically hide an active direct proposed non-Task endpoint merely because it is proposed.

Preserve existing bounded rooted behavior and `truncated` semantics, but give active direct visible relations priority over unrelated ordinary neighbors.

Do not turn a bounded rooted workspace into unbounded graph closure.

### Remaining off-context cases are exceptional fallback

There can still be legitimate cases where `/neighbors` knows an endpoint absent from the current canvas, for example:
- a Task endpoint belongs to another semantic Task component/window and a proposed Task↔Task edge must not merge the components;
- a bounded rooted workspace is genuinely truncated;
- a race occurs between inventory and workspace reads.

For those exceptional rows:
- use explicit wording such as `вне текущей области` or `не показано в текущем контексте`;
- row-tap may continue to reroot/navigate;
- an explicit compact `Показать` action is acceptable as fallback;
- do not make this fallback the normal path for direct proposed Task↔Flow/object relations.

Do not claim the endpoint is deleted: `GraphService.get_neighbors` already filters hidden/deleted/rejected neighbor objects.

## C. Relation inventory correctness after mutation

After user/agent relation removal or proposal decision:

- the direct-relation inventory must reload/reflect the authoritative edge state;
- rejected edges must no longer appear in the active inventory;
- map edge selection must not remain stuck on a removed/rejected edge;
- if a visible Task↔Task edge affects canonical geography, refresh the authoritative Task workspace/layout as today;
- if it does not affect Task topology, remove/update locally without unrelated reload churn.

Preserve current SW2-A semantic-window behavior.

## Required backend tests

Update/add focused tests proving relation removal plus endpoint visibility.

### Relation repair

1. `agent + proposed` confirm and reject remain unchanged.
2. `agent + confirmed + removable type` accepts `decision=reject` and returns `state=rejected`.
3. Cover at least `related_to`, one directed secondary type (`references` or `depends_on`), and `part_of`.
4. Confirmed agent `decision=confirm` remains invalid.
5. Already rejected agent edge cannot transition.
6. User/source/system edges cannot use this agent decision correction path.
7. Protected edge type cannot be removed through this path.
8. Wrong-user edge remains 404.
9. For a Task↔Task confirmed edge participating in Task-map topology, confirmed -> rejected increments/invalidates topology revision exactly once.
10. For a non-Task-map edge, no spurious Task-layout invalidation.

Keep existing physical `DELETE /relations/{edge_id}` user-origin behavior unchanged.

### Attached endpoint visibility

11. Unrooted overview fixture: one visible Task + one active PDF/file/email-like non-Task endpoint connected by `agent + proposed + references`. Prove both nodes and the proposed edge are returned in the same semantic window.
12. Repeat for `related_to` and `depends_on`.
13. Confirmed user/agent Task↔non-Task behavior remains visible.
14. Rejected relation does not admit the endpoint.
15. Source/system or hidden relation types are not accidentally broadened by this change.
16. A proposed Task↔non-Task endpoint does not join two Task semantic components or affect Task-component membership.
17. Shared proposed Flow/non-Task endpoint linked to Tasks in different confirmed Task components does not glue those components; duplication across windows is allowed/expected.
18. Soft target does not split a Task component from its eligible proposed non-Task endpoints.
19. Complete component + attached endpoints beyond the emergency ceiling still fails closed rather than silently dropping proposed endpoints.
20. Rooted Task workspace prioritizes a directly proposed visible non-Task endpoint over unrelated ordinary neighbors under a tight bounded fixture and reports truncation honestly if further context is omitted.

## Required client tests

### Confirmed agent removal

Add a widget regression:
- selected Task has a confirmed agent-created `references` or `depends_on` edge;
- “Удалить связь” is visible;
- confirmation dialog displays the actual directed audit text;
- accepting sends `POST /relations/{edge_id}/decision` with `{"decision":"reject"}`;
- returned rejected edge disappears from active graph/inventory;
- no `DELETE /relations/{edge_id}` is sent for this agent edge.

Add a Task↔Task topology case proving the controller takes the authoritative topology-refresh path after rejection.

### User relation removal

Preserve the existing user-origin delete behavior:
- user-confirmed edge still uses `DELETE /relations/{edge_id}`;
- objects are not deleted.

### Protected/source relation controls

Prove:
- source/system relation has no generic remove control;
- protected relation has no newly introduced agent remove control.

### Proposed attached endpoint — primary user regression

Fixture matching `Program_DYSC.pdf`:
- selected publication Task is present in the overview workspace;
- active non-Task endpoint `Program_DYSC.pdf` is connected by an agent-proposed `references` relation;
- backend workspace response contains both endpoint and edge.

Prove:
- PDF node is visible on the graph canvas without opening the inspector;
- proposed diamond/edge is visible;
- inspector row still shows real endpoint title and proposal controls;
- no `вне текущего контекста` cue is shown for this normal case;
- Confirm/Reject remain usable;
- no side-panel overflow.

### Exceptional off-context fallback

Keep/adjust `graph_direct_relation_inventory_test.dart` with a deliberately exceptional fixture (for example another Task component omitted from the current semantic window or an explicitly truncated rooted workspace).

Prove:
- inspector still lists the active neighbor;
- wording clearly says it is outside/not shown in the current context;
- explicit navigation action or row-tap can reroot to it;
- this fallback is not used for the normal proposed Task↔non-Task case above.

Keep the failed-inventory retry behavior green.

## Preserve existing accepted behavior

Keep green:
- TL2.2 `task-map-v2.2` layout and snapshot behavior;
- TL2/TL2.1/TL2.1.1 geometry invariants;
- SW2-A whole-component pagination;
- GFX-A duplicate title disambiguation;
- GFX-B drag `part_of`;
- GFX-C rename and scrollable relation picker;
- proposed relation diamonds and confirm/reject UI;
- Tasks/People shared world/camera;
- People anchors/clusters/shelf/cue;
- Graph smoke/large-canvas.

## Build / human-gate boundary

This slice changes both backend and client.

After implementation/tests pass:
- produce a fresh self-contained Linux debug client bundle from a clean detached checkout of the exact implementation SHA;
- record exact source SHA, UTC build time, executable path, launcher SHA-256, kernel SHA-256 if present, and adjacent `BUILD_INFO.txt`.

Do NOT deploy backend or install the client automatically.

A true end-to-end human check of confirmed-agent removal requires the matching backend behavior in production. After Architect source review, production rollout will require a separate explicit user authorization.

The off-context client UI can be source/widget-tested before rollout, but do not claim the full human gate is complete against the old backend.

## Explicitly out of scope

- in-place editing of relation type;
- one-click reverse-direction mutation;
- bulk relation cleanup;
- automatic inference/correction of old wrong relations;
- changing real data during tests;
- SW2-B oversized-component splitting;
- Task layout algorithm/version changes;
- schema/Alembic changes;
- production deployment;
- client installation;
- GUX1 / Secretary Agent roadmap work.

## Completion contract

When complete:

1. record root cause, exact backend/client behavior, implementation SHA, tests, topology-invalidation evidence, bundle provenance/hashes, and limitations in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus concise GR1 source-ready summary and explicit note that production rollout/human gate is pending;
3. commit/push to `main`;
4. STOP.

Do not deploy production and do not start another Graph-cleanup slice.
