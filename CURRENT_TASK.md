# Current task — GR1 relation repairability + off-context clarity

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

### “Relation exists but object is not on the map”

`_DirectRelationInventory` intentionally calls `GET /objects/{object_id}/neighbors` to load direct active neighbors even when they are not present in `controller.nodes`.

Backend `GraphService.get_neighbors` filters neighbors to active readable objects and omits rejected/deleted endpoints.

Therefore an off-canvas neighbor returned by this API is not a deleted object. It is an active endpoint outside the current Graph workspace/window/evidence admission context.

The UI currently only appends a small `не на карте` subtitle and row-tap silently reroots to it. This cue is too weak.

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

## B. Explicit off-context relation cue

For a direct relation whose neighbor is returned by `/neighbors` but is absent from `controller.nodes`:

- replace the vague `не на карте` wording with a clear status such as `вне текущего контекста`;
- add an explicit compact action with tooltip/text semantics `Показать на карте`;
- activating it reroots/opens the neighbor using the existing Graph navigation path;
- keep row-tap navigation if desired, but the explicit action must exist;
- do not claim the object is deleted or broken.

This applies equally to Task and Flow/evidence endpoints.

The action must coexist with proposal controls. A proposed off-context relation may therefore show:
- status “вне текущего контекста”;
- “Показать на карте”;
- Confirm;
- Reject.

Keep the inspector compact and avoid horizontal overflow at the current narrow side-panel width.

### Active/deleted semantics

Do not add a speculative “deleted endpoint” state in this slice.

The current `neighbors` endpoint already filters hidden/deleted/rejected neighbor objects. If an endpoint is returned there, treat it as active.

If a race causes reroot to fail after inventory load, use existing fail-closed navigation/error behavior; do not invent stale object content.

## C. Relation inventory correctness after mutation

After user/agent relation removal or proposal decision:

- the direct-relation inventory must reload/reflect the authoritative edge state;
- rejected edges must no longer appear in the active inventory;
- map edge selection must not remain stuck on a removed/rejected edge;
- if a visible Task↔Task edge affects canonical geography, refresh the authoritative Task workspace/layout as today;
- if it does not affect Task topology, remove/update locally without unrelated reload churn.

Preserve current SW2-A semantic-window behavior.

## Required backend tests

Update/add focused tests proving:

1. `agent + proposed` confirm and reject remain unchanged.
2. `agent + confirmed + removable type` accepts `decision=reject` and returns `state=rejected`.
3. Cover at least `related_to`, one directed secondary type (`references` or `depends_on`), and `part_of`.
4. Confirmed agent `decision=confirm` remains rejected as invalid.
5. Already rejected agent edge cannot transition.
6. User/source/system edges cannot use this agent decision correction path.
7. Protected edge type cannot be removed through this path.
8. Wrong-user edge remains 404.
9. For a Task↔Task confirmed edge participating in Task-map topology, confirmed -> rejected increments/invalidates topology revision exactly once.
10. For a non-Task-map edge, no spurious Task-layout invalidation.

Keep existing physical `DELETE /relations/{edge_id}` user-origin behavior unchanged in this slice.

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

Preserve the existing user-origin delete behavior and regression:
- user-confirmed edge still uses `DELETE /relations/{edge_id}`;
- objects are not deleted.

### Protected/source relation controls

Prove:
- source/system relation has no generic remove control;
- protected relation has no newly introduced agent remove control.

### Off-context active endpoint

Extend `graph_direct_relation_inventory_test.dart`:

Fixture:
- selected Task is on canvas;
- active neighbor is returned by `/objects/{id}/neighbors` but absent from workspace nodes;
- use a proposed agent relation to match the user’s `Program_DYSC.pdf` case.

Prove:
- relation row is present with the real endpoint title;
- status says `вне текущего контекста` (or approved equivalent);
- explicit `Показать на карте` control is visible;
- proposal Confirm/Reject controls are still visible;
- no panel overflow at 1280x800 test viewport;
- activating “Показать на карте” calls/reloads the rooted workspace for that endpoint;
- once rooted and endpoint is present, the off-context cue disappears.

Keep the existing failed-inventory retry behavior green.

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
