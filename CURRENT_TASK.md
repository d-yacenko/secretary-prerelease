# Current task — Visual Task Map V8A: Productize hybrid renderer + simplify edge grammar

V7B near-field geometry is accepted as the working product-map base.

This task is productization/cleanup only.

Promote the accepted `LOD+fCoSE` hybrid renderer to the single visible Tasks-map implementation and simplify the visual language of edges.

Do NOT implement `part_of`.
Do NOT change backend relation semantics.
Do NOT deploy production.

No new dependency.

## 1. One visible Tasks renderer

In Tasks mode, remove the visible renderer experiment selector/buttons:

- `Текущий`;
- `Эксперимент`;
- `ELK`;
- `fCoSE`;
- `Фокус LOD`;
- `LOD+fCoSE`.

The product Tasks graph should directly render the accepted hybrid LOD+fCoSE presentation.

Keep:
- Tasks / People mode switch;
- search and existing graph actions;
- Preserve / Relax selector for now.

People mode remains unchanged.

Do not add a new renderer selector.

## 2. Preserve/Relax stays

Keep the current two fCoSE refinement modes:
- Preserve;
- Relax.

Default remains Preserve unless current behavior already intentionally differs.

Do not parameter-search or rename them in this task.

## 3. Experimental implementation cleanup boundary

The old experimental implementations may remain in source temporarily if removing them would broaden risk.

But:
- they must not be reachable from normal product UI;
- no visible labels/toggles for them remain;
- the product screen should no longer depend on a user-selected `TaskMapRenderer` mode to decide the Tasks canvas.

Do not delete graphview/ELK dependencies or experiment files unless removal is trivial and all focused tests stay green.

Prefer UI/product cleanup over broad code deletion.

## 4. Remove normal experimental fallback banners

Topology-guard fallback to balanced deterministic positions is now expected behavior, not a product error.

Do not show user-facing banners such as:
- `Компактные гало оставлены на сбалансированных позициях`;
- `Локальное соцветие оставлено на стартовых позициях`.

Keep diagnostics internally/testably if useful.

Show a concise warning only for a genuine refinement failure where product geometry cannot be produced normally.

Do not remove actual error handling.

## 5. Add an engine-neutral edge presentation role

Introduce a small client presentation helper equivalent to:

- `GraphMapEdgeRole.attachment`
- `GraphMapEdgeRole.structural`
- `GraphMapEdgeRole.dependency`
- `GraphMapEdgeRole.hidden`

The helper classifies visible Tasks-map edges from:
- edge type;
- source object kind;
- target object kind;
- current selected object id when needed for visibility.

Do not mutate canonical `SecretaryEdge`.

The primary map must NOT equate raw `source_id -> target_id` with “draw an arrow”.

## 6. Attachment edges: no arrow

Task ↔ compactable Flow context/evidence is an attachment in this map.

For:
- compact Flow hairlines;
- selected finite Task -> expanded focused Flow;
- equivalent Task/Flow context edges shown by the hybrid renderer;

render:
- solid low/normal-emphasis line;
- NO arrowhead.

Canonical edge direction remains unchanged in data/details.

The user can inspect exact relation type in the detail panel.

## 7. Generic Task↔Task structural/context links: no arrow

For visible Task↔Task edges that are not `depends_on`, including current:
- `related_to`;
- legacy `contains`;
- `references` if such an edge exists between Tasks;
- other non-operational contextual Task↔Task links;

render a plain line with no arrowhead.

Keep existing selected/emphasized styling where practical.

Do not reinterpret the canonical edge.

## 8. depends_on: directional cross-link only

`depends_on` retains directional semantics:

- source Task depends on target Task;
- arrow points source -> target.

But in the primary Tasks map:
- hide/dim the dependency cross-link in normal overview;
- show it clearly when the selected Task is either endpoint;
- use a visually distinct dashed or similarly secondary style;
- keep one arrowhead at the target end.

Do not use dependency edges as hierarchy/layout parentage.

Do not change Task operational semantics.

## 9. Hide non-map relation classes from Tasks canvas

In Tasks mode, do not continuously draw canvas edges for:

- Task↔Person actor-role relations:
  - `requested_by`;
  - `delegated_to`;
  - `waiting_on`;
  - `involves`;
- `labeled_with`;
- `temporal_evidence`;
- `temporal_confirmation`;
- Flow↔Flow source-local relations such as email thread/reference edges.

Their data must remain unchanged and visible in the appropriate detail/Task Profile/People contexts.

People mode behavior stays unchanged.

## 10. Proposed edge styling

If a visible edge is proposed:
- preserve the current proposed/dashed provenance cue where practical;
- edge role still decides whether an arrowhead exists.

A proposed generic link does NOT get an arrow merely because it has source/target orientation.

## 11. Reserve compact-halo angles around major Task rays

Fix the screenshot defect where a compact Flow hairline lies directly on top of a Task↔Task line.

For each Task anchor during HYBRID compact balanced placement:

- collect rays from that Task center to visible Task neighbors whose map edge role is `structural`;
- treat a symmetric angular corridor around each such ray as unavailable for compact preferred slots;
- use ±15° as the initial reserved corridor (half of the existing 30° compact reference slot);
- if a compact preferred slot falls inside a reserved corridor, search the existing deterministic nearby angular alternatives / next ring;
- do not move Tasks;
- do not add an edge router.

This is presentation-only.

Do not reserve corridors for hidden relations.

For `depends_on`, reserve its ray only while that dependency edge is currently visible due to focus.

## 12. Hairline clarity

Compact Flow hairlines:
- remain thin and non-directional;
- use final accepted compact positions;
- should not intentionally coincide with a visible Task↔Task edge for a meaningful length;
- can cross another line at a non-parallel angle if unavoidable.

Do not build a full segment-routing engine.

## 13. Preserve current finite/ongoing behavior

Finite Task:
- current rectangular presentation;
- selected finite opens local focused Flow flower.

Ongoing Task:
- current 144×144 circular `∞` presentation;
- selected ongoing keeps Flow compact.

No completion-mode changes.

## 14. Future hierarchy invariant — document only

Do NOT add `part_of` in this task.

Add one concise code/project comment where appropriate documenting the future convention:

- canonical `part_of`: child/source -> parent/target;
- normal overview is expected to use a structural line;
- any future arrow affordance may therefore point rootward without inventing layout-based direction.

No API/backend/schema code for `part_of`.

## 15. Tests / focused proof

Add/update tests proving at minimum:

1. Tasks UI no longer shows renderer labels:
   - Текущий;
   - Эксперимент;
   - ELK;
   - fCoSE;
   - Фокус LOD;
   - LOD+fCoSE.
2. Tasks mode renders hybrid presentation directly.
3. People mode unchanged.
4. Preserve/Relax remains visible in Tasks mode.
5. Balanced/topology fallback does not show a normal product warning banner.
6. Genuine refiner failure still has safe fallback/error cue.
7. Task↔Flow attachment edge has no arrowhead.
8. Generic Task↔Task edge has no arrowhead.
9. `depends_on` arrow is source -> target.
10. `depends_on` is not prominent/visible in overview but appears when one endpoint is selected.
11. Actor-role/label/temporal/Flow↔Flow edges are hidden from Tasks canvas.
12. Detail/Task Profile relation data remains unchanged.
13. Proposed visible generic edge remains proposed-styled but non-directional.
14. Compact balanced placement avoids ±15° structural Task-edge corridor in fixture.
15. Compact hairline does not coincide with the structural Task edge in the screenshot-style fixture.
16. Task center drift remains 0 px.
17. Finite/ongoing focus behavior remains unchanged.
18. Preserve/Relax geometry behavior remains at V7B baseline.
19. No backend/schema/relation-data changes.
20. Current known unrelated UI/detail test failures are not expanded.

Run:
- current Graph workspace/controller tests;
- V7A completion-mode/ongoing graph tests;
- V7B dandelion/angular tests;
- new edge-presentation/product-toolbar tests;
- Task Profile UI regression tests;
- Flutter analyze touched files;
- `flutter build linux --debug`;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA;
- record which renderer UI was removed/hidden;
- record edge-role mapping used by the Tasks map;
- record arrow policy;
- record ±15° Task-ray corridor result;
- record known remaining visual polish;
- do not begin `part_of` automatically;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Human/architect review decides whether to begin Task composition/hierarchy next.
