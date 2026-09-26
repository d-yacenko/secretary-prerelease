# Current task — Visual Task Map V8A-R: Productize hybrid renderer + preserve semantic relation direction

V7B near-field geometry is accepted as the working product-map base.

The previous V8A edge simplification policy is superseded.

This task productizes the accepted hybrid renderer AND makes map relation presentation faithful to canonical relation semantics.

Core invariant:

> If Secretary can reason over a relation type and source/target direction, the human must be able to inspect the same type and direction.

Do NOT reverse arrows to point toward a visual center.
Do NOT infer direction from layout.
Do NOT implement `part_of` yet.
Do NOT change backend relation semantics.
Do NOT deploy production.

No new dependency.

## 1. One visible Tasks renderer

In Tasks mode remove the visible experiment selector/buttons:

- `Текущий`;
- `Эксперимент`;
- `ELK`;
- `fCoSE`;
- `Фокус LOD`;
- `LOD+fCoSE`.

The Tasks graph should directly render the accepted hybrid LOD+fCoSE presentation.

Keep:
- Tasks / People switch;
- search and existing graph actions;
- Preserve / Relax selector for now.

People mode remains unchanged.

Old experiment implementations may remain in source if deleting them broadens risk, but they must not be reachable from normal product UI.

## 2. Preserve / Relax stays

Keep:
- Preserve;
- Relax.

Default remains current behavior.

Do not tune parameters in this task.

## 3. Remove normal topology-fallback banners

Balanced deterministic fallback is expected behavior.

Do not show ordinary product banners such as:
- compact halo kept at balanced positions;
- local flower kept at start positions.

Keep diagnostics internally/testably.

Only genuine refinement failure may show a concise warning.

## 4. Add semantic edge presentation metadata

Introduce a client presentation helper equivalent to a `GraphMapEdgePresentation` that derives from canonical edge type and endpoint kinds:

- whether edge is visible in Tasks map;
- whether relation is directed;
- line style;
- arrowhead policy;
- relative emphasis;
- human-facing relation label.

Do not mutate `SecretaryEdge`.

Raw `source_id -> target_id` is canonical direction, but arrow visibility depends on the semantic type.

## 5. Initial Tasks-map relation grammar

Implement this initial vocabulary.

### `related_to`
Semantically symmetric for map purposes.

Render:
- solid normal line;
- no arrowhead.

Detail panel:
- show both endpoints with an undirected separator.

### `references`
Directed:
- source -> target.

Typical Task evidence is:
- Task -> Flow.

Render:
- light solid line;
- arrowhead at target;
- in compact LOD use a small low-emphasis arrowhead on the Task->Flow hairline;
- in selected expanded flower use normal visible arrowhead.

Do not reverse based on visual center.

### `depends_on`
Directed:
- dependent/source -> prerequisite/target.

Render:
- dashed line;
- arrowhead at target;
- visually secondary compared with structural/current-focus edges;
- may be dimmed outside focus, but if the line is shown its direction must remain visible.

Do not use it as hierarchy/layout parentage.

### legacy `contains`
Directed according to actual canonical:
- source -> target.

Render:
- solid structural line;
- arrowhead at target.

Do NOT reinterpret or reverse it as future `part_of`.

### future `part_of`
DOCUMENT ONLY in this task:
- child/source -> parent/target.

No backend/API/schema implementation yet.

## 6. Other relation types

Task actor roles:
- `requested_by`;
- `delegated_to`;
- `waiting_on`;
- `involves`.

Label/temporal:
- `labeled_with`;
- `temporal_evidence`;
- `temporal_confirmation`.

Flow↔Flow source-local relations may remain hidden from the primary Tasks canvas to avoid clutter.

But:
- do not mutate/remove them;
- detail/Task Profile/People views must keep them;
- when shown in any relation detail row, source/target direction must be explicit.

Do not invent a separate map style for every internal relation in this task.

## 7. Relation detail panel becomes semantic audit view

The selected-object side panel currently shows relation type and the other object but not enough canonical orientation.

Update each relation row so the human can see:

- relation type label;
- canonical source;
- canonical target;
- direction;
- provenance/origin when available;
- state/proposed/confirmed cue when available.

For directed relations show text equivalent to:

`Source title —[relation type]→ Target title`

For symmetric `related_to` show equivalent to:

`Source title — Target title`

The selected object may be source OR target; do not rewrite the underlying orientation.

Make it obvious which endpoint is the currently selected object, using wording/style equivalent to `Этот объект` if helpful.

Keep existing confirm/reject/remove actions.

## 8. Directional truth must match map and detail

For every visible directed map edge:

- arrow direction must match the exact canonical source -> target shown in the side panel;
- no layout/root/focus code may reverse it;
- changing focus must not flip an arrow.

Add test helpers around this invariant.

## 9. Proposed relation styling

Keep current proposed provenance cue.

A proposed directed relation:
- keeps its semantic arrow direction;
- also keeps proposed styling.

A proposed `related_to` stays non-directional.

Do not let dash style alone ambiguously encode both proposal state and dependency type without another distinguishing cue.

Use color/opacity/line pattern combination already available, minimally.

## 10. Compact Task→Flow hairlines

Compact Flow remains LOD presentation of a real canonical relation.

For a compact Flow whose presentation anchor edge is a directed `references` Task->Flow relation:

- draw thin hairline;
- add a small arrowhead at the Flow end;
- keep arrow visually subtle;
- provider/kind/bookmark glyph remains primary.

If the compact visual is anchored through a symmetric `related_to` relation:
- no arrowhead.

Do not fabricate direction for presentation-anchor geometry if no canonical directed anchor edge exists.

## 11. Multi-Task compact Flow

One Flow still renders once at its deterministic presentation anchor.

Its compact hairline must correspond to the actual chosen canonical edge between the anchor Task and Flow.

If that canonical edge is directed:
- preserve its actual direction.

Do not infer ownership from the presentation anchor.

Other non-anchor relations remain visible in the detail panel even if not simultaneously drawn as compact long edges.

## 12. Reserve compact-halo angles around major visible Task rays

Keep/finalize the geometry polish from prior V8A intent.

For each Task anchor:
- collect visible Task↔Task map-edge rays;
- reserve ±15° around each such ray for compact preferred slots;
- if a compact preferred slot falls there, use deterministic alternate angle / next ring;
- do not move Tasks;
- no edge router.

This prevents compact Flow hairlines from visually merging with Task↔Task edges.

Reserve only rays that are actually visible in the Tasks canvas.

## 13. Hairline / line collision clarity

Compact hairlines:
- should not intentionally coincide with a visible Task↔Task edge for a meaningful length;
- can cross at a clear angle if unavoidable.

Do not implement general routing.

## 14. Preserve finite / ongoing behavior

Finite Task:
- rectangular;
- selected finite opens local Flow flower.

Ongoing Task:
- 144×144 circular infinity presentation;
- selected ongoing keeps Flow compact.

No completion-mode change.

Task center drift stays 0 px.

## 15. Tests / focused proof

Add/update tests proving at minimum:

1. Tasks UI no longer shows:
   - Текущий;
   - Эксперимент;
   - ELK;
   - fCoSE;
   - Фокус LOD;
   - LOD+fCoSE.
2. Tasks mode directly renders accepted hybrid.
3. People mode unchanged.
4. Preserve/Relax remains visible.
5. Normal topology fallback banners are gone.
6. Genuine refinement failure remains safe.
7. `related_to` renders without arrow.
8. `references` renders source -> target arrow.
9. Selected Task->Flow references arrow points Task -> Flow in both compact and expanded presentation.
10. `depends_on` renders dashed source -> target arrow.
11. legacy `contains` preserves canonical source -> target arrow.
12. Focus/root changes do not reverse any semantic arrow.
13. Detail relation row shows canonical source, relation type, target, origin/state.
14. Detail orientation matches canvas orientation.
15. Selected object may be target and still sees the true source -> target relation.
16. Proposed directed relation preserves both proposal cue and arrow direction.
17. Hidden actor/label/temporal/source-local relations remain present in canonical/detail data.
18. Multi-Task compact Flow hairline uses the actual chosen anchor edge semantics.
19. Compact balanced placement avoids ±15° visible Task-edge corridor.
20. Screenshot-style hairline does not lie on top of the major Task edge.
21. Task center drift remains 0 px.
22. Finite/ongoing focus behavior remains unchanged.
23. V7B geometry baseline remains intact.
24. No backend/schema/relation-data changes.
25. Known unrelated UI/detail failures do not expand.

Run:
- graph workspace/controller tests;
- relation/detail-panel tests;
- V7A completion-mode/ongoing tests;
- V7B dandelion/angular tests;
- new semantic-edge/product-toolbar tests;
- Task Profile UI regression tests;
- Flutter analyze touched files;
- `flutter build linux --debug`;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA;
- record removed/hidden renderer UI;
- record final relation-to-line/arrow mapping;
- record side-panel canonical relation format;
- record ±15° corridor result;
- record known remaining visual polish;
- do not begin `part_of` automatically;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Architect/human review decides whether to begin Task composition/hierarchy next.
