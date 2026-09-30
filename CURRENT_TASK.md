# Current task — SW2-A semantic windows keep confirmed Task components whole

Authorized base: `5ca7e5feb2cca87410246f7cfed71f3fbf71e5a0`.

TL2.1.1 human gate: ACCEPTED from the user's real Academic-map screenshot on 2026-09-30 for the geometry target under review:
- the previously long dashed relation between «Трудоустройство в МФТИ» and «Преподавание Java в МФТИ» is now local/short;
- the Teaching branch remains a coherent local flower;
- the remaining visibly torn Publications flower is a semantic-window/page-membership problem, not a canonical Task-layout problem.

Canonical Task layout remains `task-map-v2.1.1`.
Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`.

This task is **Semantic Windows v2 — slice A**. It fixes the observed page tearing for ordinary connected Task constellations. It does NOT yet implement emergency branch splitting / continuation connectors for one truly oversized Task component; that is reserved for SW2-B after this slice is reviewed.

## Root cause

Current overview pagination in `GraphWorkspaceService._overview_constellations` treats only a confirmed `part_of` tree as one indivisible page unit.

A Task that is visually attached to that tree by another confirmed Task↔Task relation such as `related_to`, `depends_on`, or `references` can therefore become a separate constellation/page unit.

That disagrees with the canonical Tasks map, where confirmed visible Task↔Task relations form one visual/semantic component. It allows a flower to be torn across areas even though the linked Tasks are one connected Task graph.

The user's Publications example demonstrates this: several publication Tasks remain in area 1 while two linked publication petals move to area 2.

## Goal

For **unrooted Tasks overview semantic windows**, make the indivisible soft-pagination unit a complete connected component of the **confirmed visible Task map**, not merely one `part_of` tree.

A normal soft window boundary must not cut through such a Task component.

## Canonical Task-component membership

Build overview Task components over the current visible Task universe.

Two Tasks belong to the same semantic component when connected transitively by a Task↔Task edge that is allowed to influence the confirmed canonical Tasks map:

- both endpoints are visible Tasks owned by the current user;
- edge state is exactly `confirmed`;
- relation type is visible on the Tasks map (same hidden relation-type boundary as Task-map topology/presentation);
- confirmed `part_of` participates normally and keeps child/source -> parent/target semantics;
- confirmed non-`part_of` Task relations such as `depends_on`, `references`, and `related_to` may glue Tasks into the same semantic component.

Must NOT glue components:

- proposed edges;
- rejected edges;
- actor-role edges (`requested_by`, `delegated_to`, `waiting_on`, `involves`);
- label/temporal hidden relation types;
- Task↔Flow edges;
- Person edges.

Use one clear backend predicate/helper for overview component membership. Keep it semantically aligned with the accepted TL2.1.1 rule that only confirmed Task relations affect canonical geography. Do not rely on the older broader non-rejected behavior where it disagrees.

## Component contents

For each Task semantic component:

1. include all Task members of that component;
2. attach the same existing priority Task↔Flow evidence/context policy for those Tasks;
3. Flow evidence may belong to more than one component if it is genuinely shared; Flow must **not** glue Task components together;
4. complete returned edges only among nodes actually present in the selected window, as today.

The component's deterministic ordering key should remain based on the best/minimum existing Task seed key among its overview-eligible Task members, with a stable Task-id tie-breaker/representative.

Legacy response fields such as `seed_ids` / `constellation_root_ids` may keep their shape. If one semantic component has several structural `part_of` roots, choose/document one deterministic representative rather than inventing hierarchy.

## Soft-window packing

Preserve the useful existing soft-budget behavior:

- independent Task semantic components are packed in stable order into windows until the soft target is reached;
- a component that by itself exceeds the soft target is kept **whole** in one window rather than sliced;
- shared Flow ids are deduplicated when several components land in the same window;
- adding a later unrelated component should not reshuffle earlier windows unnecessarily.

For SW2-A, the existing emergency complete-window ceiling remains a hard fail-closed safety boundary.

If one semantic Task component (Tasks + admitted priority evidence under the current policy) exceeds the emergency ceiling, keep the current explicit error behavior. Do NOT implement arbitrary node slicing.

That future oversized-component case belongs to SW2-B, which will split by semantic branches and add continuation markers.

## Rooted workspace is unchanged

Do not broaden rooted/focused Task workspaces to the whole confirmed Task connected component in this slice.

Existing rooted behavior, local expansion, neighbor limits, and confirmed `part_of` closure remain as they are.

SW2-A changes only **unrooted overview window membership/packing**.

## People/shared world

Do not change People workspace semantics.

Canonical Task centers remain `task-map-v2.1.1`, and Tasks/People continue to share that one world.

No Task-layout algorithm/version bump is needed for SW2-A because this changes which canonical Tasks are exposed in an overview area, not their persisted centers.

## Required backend regressions

Add deterministic tests that make the old page tear fail.

### A. Publication flower across secondary Task edges

Fixture:
- one Direction Task;
- five publication Task leaves;
- connect the five leaves to the Direction with confirmed visible non-`part_of` Task relations (use `related_to` for the primary fixture);
- add at least one unrelated later Task/component;
- use a soft target small enough that the old part_of-only constellation logic would split the publication leaves across windows.

Prove:
- Direction + all five publication Tasks are in the same overview window;
- none of those five petals appears alone on a neighboring window;
- the unrelated component may move to the next window;
- `semantic_window_complete` remains true.

### B. Mixed Academic component

Fixture:
- Academic;
- Publications, Teaching, Courses attached structurally with confirmed `part_of`;
- publication/teaching leaf Tasks attached through confirmed visible secondary Task relations.

Prove the entire connected Academic Task component is an indivisible soft-pagination unit even though it contains both structural and secondary Task edges.

### C. Proposed/rejected do not glue pages

For each of `depends_on`, `references`, and `related_to`:
- absent/proposed/rejected between two otherwise separate Task components must leave them separate;
- confirmed must merge them into one semantic component.

### D. Hidden relations do not glue

At minimum cover one actor-role relation and one label/temporal hidden type between Tasks. They must not merge overview components.

### E. Flow does not glue Task components

Two unrelated Tasks/components referencing the same Flow remain separate Task semantic components.

The shared Flow may appear according to the existing priority-evidence policy, but its existence must not force those Tasks onto one page.

### F. Soft target versus whole component

A single confirmed Task component larger than the soft target remains whole in one window.

Independent later components begin in a later window when necessary.

### G. Emergency ceiling stays fail-closed

A semantic component beyond the existing emergency ceiling raises the explicit complete-overview error. Do not silently truncate or split it in SW2-A.

### H. Stable window behavior

Keep/adjust existing pagination tests so:
- previous/next flags and invalid index behavior remain correct;
- later unrelated additions preserve already-earlier stable component ordering where possible;
- returned edges never reference nodes outside the current window;
- duplicate shared Flow nodes are not duplicated within one response.

## Required client regressions

The response shape should preferably remain unchanged.

Keep green:
- `graph_semantic_window_test.dart`;
- page previous/next navigation;
- overview -> rooted -> overview behavior;
- current compact banner;
- selected-object reset/preservation semantics;
- canonical Task layout resolution;
- TL2/TL2.1/TL2.1.1 geometry tests;
- GFX-A/B/C;
- Tasks<->People shared-world/camera;
- People shelf/cue;
- Graph smoke/large-canvas.

If backend semantics require a minimal wording correction in the existing overview banner, keep it concise and do not redesign the toolbar.

## Human validation / deployment boundary

SW2-A changes backend overview membership. **Do not deploy it to production in this task.**

Completion of source/tests is not the human gate because the currently installed/debug client will still talk to the old production backend until a backend rollout is separately authorized.

Do not:
- move `production`;
- run Alembic;
- restart/replace production services;
- install a client automatically.

If no client source changes are necessary, no redundant client bundle is required for SW2-A source completion. If client source does change, record that fact, but do not present the bundle as a valid end-to-end human check against the old backend.

After Architect review, production/backend rollout for manual verification requires separate explicit user authorization.

## Explicitly out of scope — reserved for SW2-B

- splitting one truly oversized connected Task component into branches/subtrees;
- continuation/page connector markers;
- duplicated boundary context nodes;
- page-to-page jump anchors;
- changing the emergency ceiling;
- screen-size-driven partitioning;
- canonical Task layout changes;
- manual positioning;
- new relation types or ontology changes;
- schema/Alembic changes;
- production deploy/ref movement;
- old GUX1 / Secretary Agent work.

## Completion contract

When complete:

1. record root cause, implementation SHA, changed files, semantic-component rules, old-vs-new publication fixture behavior, exact backend/client regression checks, and known limitations in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus concise SW2-A summary and a clear note that production rollout/human verification is NOT performed;
3. commit/push to `main`;
4. STOP.

Do not begin SW2-B and do not deploy production.
