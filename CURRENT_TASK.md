# Current task — Visual Task Map V5: Hybrid Focus LOD + fCoSE presentation geometry

Human real-data review changed the geometry direction.

V3B fCoSE looked visually strong on real data despite negative synthetic movement metrics. V4 Focus LOD concept looked promising, but current 24 px circular provider dots are too weak semantically and lack visible attachment to their Task.

Implement one new experimental hybrid renderer that combines:

- stable Task geography;
- Focus LOD large-vs-compact semantics;
- fCoSE as geometry/refinement for presentation Flow marks of mixed sizes;
- semantic compact Flow glyphs with thin Task-to-glyph hairlines.

Do not replace the current startup renderer.
Do not remove V1/V2/V3B/V4 experiments.

No new dependency is allowed; reuse existing `fcose: 0.1.0`.

No backend/API/schema/ontology/deploy changes.

## 1. New renderer

Add a Task renderer labelled equivalent to:

`LOD+fCoSE`

Keep:
- `Текущий` startup/default;
- V1 `Эксперимент`;
- V2 `ELK`;
- V3B `fCoSE`;
- V4 `Фокус LOD`;
- People mode unchanged.

The hybrid renderer reuses already-loaded workspace data only.

## 2. Revised geometry invariant

The important stable geography is the Task skeleton.

In hybrid mode:

- every visible Task card MUST stay exactly at its controller/current `GraphLayout` top-left;
- Task drift across focus changes MUST be 0 px;
- fCoSE may reposition Flow/context presentation nodes to improve packing;
- Flow movement is allowed and must be measured;
- do not persist refined Flow positions;
- switching back to Current/V4 must reveal unchanged canonical/controller positions.

Do not use fCoSE to move Tasks.

## 3. LOD semantics

Reuse V4 compactable kinds and presentation-anchor rules.

When a Task is selected:
- selected Task stays a full fixed Task card;
- its already-loaded directly connected compactable Flow objects render as full current-style cards;
- those selected full Flow cards are MOVABLE presentation nodes for fCoSE;
- Task-to-Task neighbors stay fixed full Task cards.

All other eligible compact Flow:
- render as compact semantic glyphs;
- are MOVABLE presentation nodes for fCoSE;
- keep one deterministic V4 presentation anchor Task;
- one Flow object is rendered exactly once.

No selected Task:
- all eligible Flow is compact;
- Tasks stay full/fixed;
- fCoSE may refine compact Flow placement.

Non-compactable non-Task objects keep their current full-card representation and are FIXED geometric obstacles.

Do not fetch more data.

## 4. Mixed-size fCoSE presentation scene

Build an engine-neutral `GraphGeometryScene` (or equivalent adapter input) from PRESENTATION nodes.

Use actual presentation sizes:

- Task cards: current `kGraphNodeWidth × kGraphNodeHeight`, fixed;
- selected expanded Flow cards: current full-card size, movable;
- compact Flow glyphs: choose exactly one size in the 30–34 px range, movable;
- non-compactable full objects: current full-card size, fixed.

Recommended compact geometry size: 32×32 px.

Initial positions:

- Tasks/full fixed objects: current `GraphLayout` positions;
- selected expanded Flow: their current `GraphLayout` positions;
- compact Flow: V4 deterministic halo/ring positions BEFORE fCoSE refinement.

This makes V4 the deterministic starting geometry and fCoSE the collision/packing helper.

Use `randomize: false`, fixed-node constraints, and the existing deterministic seed.

## 5. Geometry edges

For fCoSE geometry only:

- compact Flow -> its V4 presentation-anchor Task;
- selected expanded Flow -> selected Task when directly connected to it;
- do not feed global Task-to-Task edges as movable-layout forces;
- do not create ontology/canonical relations.

These are presentation geometry constraints only.

Add explicit comments that anchor edges are not ownership/canonical relations.

## 6. Preserve vs Relax comparison

Reuse the existing fCoSE modes:

### Preserve
- existing V3B settings;
- `idealEdgeLength: 50`.

### Relax
- same settings except `idealEdgeLength: 90`.

Expose a compact Preserve/Relax selector only while `LOD+fCoSE` is selected.

Do not parameter-search.

## 7. Semantic compact Flow glyph

Replace the V4 circular provider-logo dot in the new hybrid renderer with a semantic object glyph.

The normal visible body MUST communicate object kind primarily by shape/icon:

- email -> envelope;
- chat/message -> chat bubble;
- file/document -> file/document shape;
- calendar/event -> calendar/event;
- web_page -> web/link/world;
- dataset/folder/note -> existing kind icon equivalents.

Use existing `iconForKind` / presentation primitives.

Visual target:
- compact mark around 32 px overall;
- main kind glyph roughly 22–26 px;
- NO enclosing circular outline as the primary silhouette;
- no visible title/date/body text.

Provider/source:
- overlay a small provider/source mark, approximately 10–12 px, in a corner when provider identity exists;
- reuse `ProviderSourceIcon`;
- provider does not replace the main kind glyph.

Bookmark:
- overlay a small bookmark-color cue (dot or existing small bookmark glyph), roughly 6–8 px;
- keep it visually distinct from provider mark;
- read-only in compact mode.

Keep Tooltip/Semantics with title/provider for accessibility.

## 8. Thin halo hairlines

For each compact Flow mark, draw one thin presentation hairline from the edge of its anchor Task card to the edge/center boundary of the compact glyph.

Requirements:
- hairline is visually low emphasis;
- recommended stroke ~0.8–1.0 logical px;
- use theme outline/onSurfaceVariant with low opacity;
- no arrowhead;
- it represents visual attachment, not edge direction;
- do not mutate/hide canonical relation data;
- selected/full Flow continues using existing canonical edge rendering.

This should create a visual “dandelion/flower” halo around non-selected Tasks.

When current focus dimming applies, the hairline and compact mark dim together.

## 9. Rendering / edge rules

Hybrid renderer:

- Task-to-Task edges keep current canonical rendering;
- selected Task -> expanded full Flow edges keep current canonical rendering;
- compact Flow canonical long edges remain suppressed;
- compact Flow gets only the thin presentation hairline to its presentation anchor;
- non-anchor relationships of a compact multi-Task Flow are not rendered in this spike.

One compact Flow visual only.

## 10. fCoSE failure fallback

If hybrid fCoSE refinement fails:

- keep Task positions unchanged;
- fall back to V4 deterministic halo positions for compact Flow;
- selected expanded Flow uses current `GraphLayout` positions;
- show concise experimental warning;
- canonical workspace/controller state remains untouched.

Do not fall back to another library.

## 11. Focus transition behavior

When Task A -> Task B selection changes:

- all Task positions stay exactly fixed;
- A's Flow changes from full-card to compact presentation where eligible;
- B's Flow changes from compact to full-card;
- fCoSE may refine Flow positions after the representation-size change;
- measure how much still-compact peripheral Flow moves;
- no backend reload solely for presentation transition.

Do not require zero Flow drift.

## 12. Required fixtures

Reuse V4 fixtures and add mixed-size cases.

### A. Overview
5+ Tasks with multiple compact halos.

Measure cross-halo packing after fCoSE.

### B. Selected flower
Selected Task with 8–12 full Flow cards plus at least two peripheral compact halos.

### C. Close halos
Two nearby Task cards, each with >=8 compact Flow marks.

This is the V4 known weak case and should directly test whether fCoSE reduces cross-halo collision.

### D. Mixed sizes
Selected Task full Flow cards adjacent to a non-selected Task compact halo.

### E. High count
One non-selected Task with >35 Flow objects.

Keep V4 cap semantics: <=20 individual marks + `+N`.
The overflow marker participates in geometry as one compact presentation mark.

### F. Focus change
A and B each have Flow; switch A -> B and measure Task vs Flow drift.

## 13. Required metrics

For Preserve and Relax record:

- success / typed failure;
- Task max drift (must be 0 px);
- number of Flow presentation nodes moved >1 px from starting presentation positions;
- max Flow displacement;
- full-card vs compact counts;
- compact-vs-Task overlaps;
- compact-vs-compact overlaps globally (not only same halo);
- full-Flow-card vs Task overlaps;
- full-Flow-card vs compact overlaps;
- deterministic repeatability;
- focus-change:
  - Task drift;
  - count of peripheral compact marks still compact before/after that move >1 px;
  - max peripheral compact displacement;
- high-count cap / overflow correctness;
- duplicate Flow visual count (must be 0).

Also record one human-readable density summary on the real-data-style selected fixture.

No production telemetry.

## 14. Product acceptance target

A promising hybrid result should show:

- Tasks keep recognizable stable geography;
- compact Flow clearly reads as email/chat/file/calendar/etc, not generic dots;
- provider and bookmark cues remain visible;
- thin hairlines make each halo's ownership/attachment visually obvious;
- fCoSE reduces cross-halo/full-vs-compact collisions compared with raw V4;
- selected full flower is clean enough to read;
- movement of Flow is acceptable and remains presentation-only.

Do not reject solely because Flow nodes move substantially.

A failure is:
- Task drift;
- worse overlaps than raw V4 without compensating readability;
- compact semantic marks still reading as generic noise;
- fCoSE moving presentation nodes so far from anchors that halos stop reading as clusters.

## 15. Scope exclusions

Do not implement:
- finite/ongoing Task mode yet;
- round infinity Direction nodes;
- far-horizon semantic zoom;
- Areas/islands;
- hierarchy / part_of / contains;
- Graphviz retry;
- new layout dependency;
- edge routing library;
- backend/API/schema changes;
- Android packaging work;
- DuckDB fix;
- production deploy.

## Focused proof

Add tests proving at minimum:

1. Current remains startup/default.
2. V1/V2/V3B/V4 remain available unchanged.
3. People mode unchanged.
4. Hybrid fixes every Task at current `GraphLayout` position.
5. Compact Flow starts from deterministic V4 halo positions.
6. Selected Flow switches to full-card geometry.
7. fCoSE receives mixed node sizes.
8. fCoSE Task constraints produce <=1 px drift; expected target 0.
9. Compact marks use kind glyph as primary visual and provider as secondary overlay.
10. Bookmark cue remains visible.
11. Compact marks have no normal visible title/date.
12. Hairline exists from anchor Task to each compact mark and has no arrowhead.
13. Compact canonical long edges stay suppressed.
14. Selected full Flow canonical edges remain.
15. Multi-Task compact Flow still renders once.
16. Close-halo global overlap metrics are recorded.
17. Focus-change Flow movement metrics are recorded.
18. High-count cap remains <=20 + correct overflow.
19. fCoSE failure falls back to raw V4 presentation with unchanged Task coordinates.
20. No canonical objects/edges/controller positions mutate.
21. Existing current/V1/V2/V3B/V4 relevant tests remain at known baseline.
22. No backend/schema/ontology/deploy change.

Run:
- `flutter pub get`;
- current Graph workspace/controller/layout/screen tests;
- V1 tests;
- V2 ELK tests;
- V3B fCoSE tests;
- V4 Focus LOD tests;
- new V5 hybrid tests;
- Task Profile UI tests;
- Flutter analyze touched files;
- `flutter build linux --debug`;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA;
- record compact glyph size and hairline styling;
- record Preserve/Relax metrics for required fixtures;
- compare raw V4 vs hybrid close-halo overlap;
- record qualitative geometry limitations;
- do not begin ongoing/infinity Task work automatically;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Human real-data visual review decides whether hybrid becomes the product-map base.
