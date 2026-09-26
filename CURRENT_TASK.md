# Current task — Visual Task Map V8B2: task-only global packing + radial part_of hierarchy

V8B1 canonical `part_of` semantics are accepted.

This task changes CLIENT PRESENTATION GEOGRAPHY only.

Goal:
- stop letting old full-size Flow card positions determine Task spacing;
- compact independent Task clusters into a useful 2D map;
- use confirmed `part_of` as radial hierarchy geometry;
- preserve the accepted V7/V8 near-field hybrid Flow behavior around the resulting Task centers.

Do NOT change backend/API/schema.
Do NOT add hierarchy status semantics.
Do NOT deploy production.
No new dependency.

## 1. New task-map presentation projection

Introduce a client helper/module equivalent to:

- `TaskMapHierarchyProjection`;
- `TaskMapHierarchyLayout`.

Input:
- visible nodes;
- visible edges;
- current canonical/base positions;
- optional workspace/root id if useful.

Output:
- presentation top-left positions for visible Task nodes;
- deterministic component/tree metadata useful for tests;
- presentation bounds for Task geography if useful.

Do not mutate `GraphWorkspaceController.positions`.

This is a presentation projection only.

## 2. Task geography must ignore Flow canonical positions

The current excessive spacing comes from `GraphLayout` laying out full-size Flow nodes before hybrid LOD collapses them.

V8B2 Task presentation geography must be computed from:
- Task nodes;
- Task↔Task map-visible relations;
- confirmed `part_of` hierarchy.

Do NOT use canonical Flow positions to decide:
- Task centers;
- Task component spacing;
- global Task packing.

Flow is attached AFTER Task positions are chosen.

## 3. Base task-only graph

Build a deterministic task-only baseline from visible Tasks.

Use only Task↔Task edges that are visible in the Tasks map presentation.

Do not include:
- Task↔Flow;
- actor-role;
- labels;
- temporal;
- Flow↔Flow;
- hidden relation classes.

For Tasks that have no confirmed `part_of` hierarchy, preserve a compact version of the current graph topology using Task↔Task adjacency only.

Reuse/refactor current `GraphLayout` primitives if practical, but do not change People mode behavior.

## 4. Confirmed part_of controls hierarchy geography

Only CONFIRMED `part_of` edges affect Task placement.

A proposed `part_of`:
- remains visible with its proposed styling/arrow;
- occupies the semantic parent slot per V8B1;
- MUST NOT move Task geography until confirmed.

Rejected edges never affect layout.

This distinction is deliberate: an AI proposal must not physically reorganize the user's map before confirmation.

## 5. Radial hierarchy model

For each visible confirmed `part_of` tree:

- parent/root is geometrically inward;
- children are placed outward around the parent/root;
- grandchildren are farther outward than children;
- deeper descendants inherit an angular sector from their ancestor branch;
- canonical arrows remain child/source -> parent/target and therefore naturally point inward.

Do not reverse an edge based on geometry.

If a visible Task's true parent is outside the current workspace, treat that visible Task as a local cut-root for this projection.

## 6. Root / child ordering

Hierarchy placement must be deterministic.

For sibling ordering:
1. prefer their existing TASK-ONLY baseline polar order around the parent when it is unambiguous;
2. tie-break by stable id.

Use subtree weight (for example leaf count / descendant weight) to allocate angular sector width so a large branch gets more space than a one-node branch.

Do not order by current Flow geometry.

## 7. Node sizes

Use actual Task presentation sizes:

- finite Task: 186×100;
- ongoing Task: 144×144 centered on the same Task center convention.

Hierarchy collision/bounds calculations must respect these actual presentation rects.

Do not treat ongoing as 186×100 for overlap proof.

## 8. Hierarchy radial separation

Choose one deterministic radial spacing rule derived from:
- actual Task rect sizes;
- a compact-halo clearance allowance;
- existing accepted visual density.

Do not introduce per-object hand tuning.

Target behavior:
- parent and children are visibly grouped;
- compact Flow halos have room;
- hierarchy is much denser than the current Flow-inflated global layout.

Record exact constants/rule in PROJECT_STATE.

## 9. Reserve local halo envelope during Task packing

When computing Task-component bounds / inter-component separation, treat each Task as its presentation rect inflated by:

- 80 px on each side.

This is a simple first-stage allowance for the accepted compact Flow halo.

Use the inflated rect for:
- component bounds;
- component-to-component packing collision checks.

Do NOT render the envelope.

Selected finite expanded flower may exceed this envelope; existing local obstacle handling remains responsible for focus-time Flow cards.

## 10. Non-hierarchy Task components

Tasks with no confirmed `part_of` incident edges should not become arbitrary isolated points if they have normal visible Task↔Task relations.

Use their normal Task↔Task connected component and keep a compact deterministic topology.

The current accepted generic geometry may be reused on TASKS ONLY.

Do not let references/Flow create a component.

## 11. Hierarchy cross-links

Non-`part_of` Task↔Task relations such as:
- `related_to`;
- `depends_on`;
- legacy `contains`;

remain visible semantic cross-links but do NOT define hierarchy parentage.

They may connect different hierarchy trees/components.

Do not use them to reverse or reshape the confirmed `part_of` tree.

## 12. Global 2D component packing

After each Task hierarchy/free component has local positions:

- compute local bounds from inflated Task envelopes;
- pack components deterministically in 2D;
- avoid the current long vertical-column behavior;
- prefer a roughly landscape / near-square occupied region;
- do not depend on viewport size for normal placement so resizing does not reshuffle geography.

Use a deterministic shelf/row or similarly simple packer.

A suggested target row width:
- derive from total local component area / sqrt;
- apply a fixed modest landscape factor around 1.3–1.5.

Exact implementation may differ if deterministic and well-tested.

Component gap after the 80 px inflation should be modest; do not recreate huge legacy spacing.

## 13. Component order / stability

Pack order must be deterministic.

Prefer:
1. larger component area descending;
2. stable component key / root id as tie-break.

If a composition component contains an ongoing root, do not arbitrarily move it because focus changes.

Selection must not affect component order.

## 14. Task center stability after projection

V8B2 intentionally changes Task display positions relative to the old canonical/base graph.

Therefore old “Task drift = 0 versus GraphLayout” is NO LONGER the invariant.

New invariants:

- same nodes + same confirmed hierarchy => exact deterministic Task positions;
- focus A -> B => Task movement 0 px;
- select/unselect => Task movement 0 px;
- Preserve -> Relax => Task movement 0 px;
- expanded/collapsed Flow => Task movement 0 px;
- proposed `part_of` added/removed => Task movement 0 px;
- confirmed `part_of` change MAY intentionally reproject affected Task geography.

Record these metrics.

## 15. Hybrid integration

Construct a presentation position map:

- start from existing positions for non-Task objects only as needed;
- override every visible Task with V8B2 task-map presentation position.

Then feed this map into the existing hybrid presentation.

Required:
- compact halos anchor to V8B2 Task centers;
- finite selected flowers anchor to V8B2 Task centers;
- ongoing circles use V8B2 centers;
- Task↔Task edge endpoints use V8B2 positions;
- semantic arrows keep V8A-R/V8B1 direction.

Do not persist the new positions.

## 16. Presentation bounds / fit

Tasks-map fit and canvas bounds must use the FINAL hybrid presentation generated from V8B2 Task positions.

Do not let old canonical Flow positions inflate fit.

Keep the V6+ hybrid presentation-bounds invariant.

Expected human result:
- clusters occupy materially more of the viewport;
- no tiny graph caused by distant old Flow geography.

## 17. Preserve / Relax

Preserve/Relax remains only the Flow refinement choice.

It must NOT:
- move Task centers;
- change hierarchy sectors;
- repack Task components.

Both modes consume the same Task geography.

## 18. Rooted/focus workspace

Do not invent a second semantic hierarchy when user roots/focuses a Task.

Within the currently loaded workspace:
- confirmed `part_of` remains the same parent/child structure;
- if the actual ancestor is not loaded, visible node becomes local cut-root;
- selecting a child does not make arrows or hierarchy reverse.

Rooting/focus can change the loaded node set through existing behavior; given a fixed loaded set, projection stays deterministic.

## 19. Required fixtures

Add deterministic geometry fixtures.

### A. Distant Flow does not move Task

Two Tasks have compact Flow whose canonical positions are thousands of px away.

Expected:
- Task presentation positions equal the task-only baseline;
- moving Flow canonical coordinates changes Task display positions by 0 px;
- final bounds do not inherit the distant Flow coordinate.

### B. Independent clusters

At least 5 independent Task clusters / singletons.

Expected:
- global packing uses at least 2 columns;
- not a single vertical column;
- no inflated component-bounds overlaps.

### C. Simple hierarchy

One parent + 4 children.

Expected:
- parent inward/center;
- children distributed around it;
- child->parent arrows point inward;
- no Task rect overlaps.

### D. Two-level hierarchy

Root -> 3 children, one child -> 3 grandchildren.

Expected:
- grandchildren farther from root than their parent;
- grandchildren remain inside that branch angular sector;
- no intentional branch interleaving.

### E. Ongoing root

144×144 ongoing parent with finite/ongoing children allowed by V8B1 fixture data.

Expected:
- correct circular center;
- hierarchy clearance uses 144×144 presentation rect.

### F. Proposed part_of

Same Tasks with proposed child->parent edge only.

Expected:
- edge visible;
- Task positions identical to no-proposal geometry.

Then mark it confirmed.

Expected:
- hierarchy geography changes deterministically.

### G. Cross-link

A `depends_on` or `related_to` connects two Tasks in different hierarchy branches/components.

Expected:
- semantic cross-link renders;
- it does not become hierarchy parentage;
- confirmed `part_of` sectors remain unchanged.

## 20. Required metrics

Record for fixtures:

- Task count;
- hierarchy tree count;
- free-component count;
- max hierarchy depth;
- Task rect overlap count;
- inflated-envelope inter-component overlap count;
- old canonical-all-node bounds width/height/area;
- V8B2 Task-only bounds width/height/area;
- final hybrid presentation bounds width/height/area;
- bounds area ratio old -> V8B2;
- component occupied-row count / column spread;
- deterministic repeat max Task movement;
- focus A -> B Task movement;
- Preserve -> Relax Task movement;
- proposed part_of Task movement;
- confirmed part_of affected Task movement.

## 21. Human screenshot target

The implementation should make the previously reported real-data view materially better:

- collapsed Task/Flow clusters are closer together;
- separate clusters use horizontal space rather than forming a long vertical column;
- the whole map no longer fits as a tiny island because of old full-Flow positions;
- once real `part_of` links exist, each hierarchy reads as an inward-rooted radial cluster.

Do not tune specifically to one screenshot.

## 22. Scope exclusions

Do NOT implement:

- backend workspace hierarchy closure;
- extra ancestor/descendant fetch depth;
- persistence of graph positions;
- drag-to-pin;
- tree collapse/expand;
- status propagation;
- parent completion rules;
- due-date inheritance;
- operational-state inheritance;
- multiple parents;
- migration of legacy `contains`;
- right detail-pane collapse/slide behavior;
- far semantic zoom;
- Areas/islands;
- new layout dependency;
- production deploy;
- DuckDB fix.

The right-side panel collapse remains a separate shell-polish task after hierarchy geometry.

## 23. Focused proof

At minimum prove:

1. V8B1 `part_of` semantics untouched.
2. Task presentation positions do not depend on Flow canonical coordinates.
3. Confirmed `part_of` controls hierarchy.
4. Proposed `part_of` does not move geography.
5. Child/source -> parent/target arrow direction remains exact.
6. Hierarchy is radial/inward-rooted.
7. Grandchildren are farther outward than parents.
8. Sibling sectors deterministic.
9. Ongoing 144×144 geometry is respected.
10. Non-hierarchy Task component uses Tasks only.
11. Cross-links do not become hierarchy.
12. 5-component fixture is not packed as one vertical column.
13. Inflated component envelopes do not overlap.
14. Same-input repeatability is exact.
15. Focus A -> B Task movement is 0 px.
16. Preserve -> Relax Task movement is 0 px.
17. Distant Flow does not inflate final hybrid bounds.
18. Finite selected flower still works.
19. Ongoing selected Task still keeps Flow compact.
20. V8A-R relation styles/directions remain unchanged.
21. People mode unchanged.
22. No backend/schema/API change.
23. Known unrelated detail-screen failures do not expand.

## Run

Run at minimum:

- new Task-map hierarchy projection tests;
- V8B1 composition/profile/client tests;
- V8A-R relation-presentation tests;
- V7A/V7B hybrid geometry tests;
- Graph workspace/controller regressions;
- Task Profile UI regressions;
- Flutter analyze touched files;
- `flutter build linux --debug`;
- `git diff --check`.

## Completion

When complete:

- record implementation SHA;
- record exact hierarchy radial spacing rule;
- record global component packing rule;
- record whether proposed edges influence layout (expected: no);
- record bounds/area comparison metrics;
- record Task stability metrics;
- record known visual limitations;
- do not start backend hierarchy closure or panel polish automatically;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Human real-data review decides whether hierarchy projection is accepted before the next shell/workspace stage.
