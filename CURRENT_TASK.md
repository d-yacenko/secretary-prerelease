# Current task — Visual Task Map V6: Local selected flower + hybrid presentation bounds

V5 hybrid is accepted as a promising direction after human real-data review.

Refine the existing experimental `LOD+fCoSE` renderer only.

Do not replace the current startup renderer.
Do not add another layout dependency.
Do not start finite/ongoing Task presentation yet.
Do not start far-horizon semantic zoom yet.

No backend/API/schema/ontology/deploy changes.

## Product problem

Real-data review found the overall hybrid concept promising:
- stable Task geography works;
- compact Flow glyphs with kind/provider/bookmark cues work;
- thin halo hairlines work;
- fCoSE is useful as a presentation geometry helper.

The remaining near-field defect is selected Flow geometry.

Today selected expanded Flow can reuse distant old `GraphLayout` coordinates and then move hundreds of pixels under fCoSE. This creates:
- long selected edge rays;
- a selected flower that stops feeling local;
- hybrid fit-to-view that can collapse into tiny islands because hidden canonical Flow positions still enlarge the canvas bounds.

V6 should make the selected Task open a LOCAL flower around itself and make hybrid bounds use actual presentation geometry.

## 1. Keep existing renderers

Keep unchanged and available:
- `Текущий` as startup/default;
- V1 GraphView;
- V2 ELK;
- V3B fCoSE;
- V4 Focus LOD;
- V5 `LOD+fCoSE`;
- People mode unchanged.

Do not add another top-level renderer.

V6 is a refinement of the existing `LOD+fCoSE` renderer.

## 2. Task geography remains fixed

In hybrid mode:
- every visible Task uses its current controller / `GraphLayout` position;
- Task drift across selection changes must remain 0 px;
- no refined presentation position is persisted;
- switching back to Current/V4 must show unchanged controller positions.

Tasks are always fixed nodes for fCoSE.

## 3. Hybrid presentation bounds

Do NOT compute hybrid canvas size / fit-to-view from every canonical `positions` entry when Flow is compact or relocated.

Introduce a presentation-bounds helper built from ACTUALLY DRAWN hybrid rectangles:
- Task cards;
- fixed non-compact full objects;
- focused Flow presentation cards;
- compact Flow glyphs;
- overflow glyphs.

Hidden canonical full Flow rectangles must not enlarge hybrid presentation bounds.

Use hybrid presentation bounds for:
- canvas width/height;
- graph-to-canvas offset;
- hybrid fit-to-view.

Do not change Current renderer bounds/fit behavior.

Add a fixture where one hidden canonical Flow node is very far away and prove hybrid visible bounds stay local.

## 4. Selected Flow gets deterministic local start positions

When selected object is a Task, directly connected compactable Flow must NOT start from its old global full-card coordinates.

Create deterministic local start positions around the selected Task.

Requirements:
- selected Task stays fixed;
- focused Flow starts in one or more local rings/cloud bands;
- no focused Flow start rectangle overlaps selected Task;
- avoid every visible Task rectangle;
- avoid focused-Flow vs focused-Flow overlap;
- deterministic for same inputs;
- no canonical position mutation.

Ordering:
1. bookmarked first;
2. existing clear recency value if already available;
3. object id tie-break.

Keep the algorithm presentation-specific and small.
Do not build a new global layout engine.

## 5. Focused Flow uses a medium graph card

Do not render selected Flow in the old full `186×100` graph card.

Introduce a dedicated selected-flower Flow presentation card.

Choose one exact size in this range:
- width 150–160 px;
- height 72–80 px.

Record the chosen dimensions.

It should show:
- kind cue;
- provider/source cue;
- title, max 2 lines;
- compact date/time if the existing client already has a clear display helper;
- bookmark cue;
- no body/long metadata.

Click selects the underlying canonical Flow object and uses the existing detail panel.

This is presentation only.

## 6. fCoSE refines the local flower

After deterministic local start positions, run fCoSE.

Use:
- selected Task fixed;
- all visible Tasks fixed as obstacles;
- fixed non-compact full objects as obstacles;
- focused Flow medium cards movable;
- compact peripheral Flow movable;
- `randomize: false`;
- deterministic seed;
- existing Preserve / Relax modes.

Focused Flow geometry spring goes to selected Task.

Do not initialize focused Flow from canonical old positions.

## 7. Two-pass refinement is allowed

If one mixed fCoSE scene makes the selected flower disperse, split refinement into two presentation-only passes:

1. focused flower:
   - selected Task;
   - focused Flow;
   - visible Tasks/fixed full objects as obstacles;

2. peripheral compact halos:
   - Tasks fixed;
   - refined focused Flow treated as fixed obstacles;
   - compact Flow movable.

Do not add another engine.

Keep this behind the presentation/geometry boundary.

## 8. Locality guard

Measure selected Task center -> focused Flow card center after refinement.

Record:
- median focused radius;
- max focused radius.

If fCoSE produces a clearly non-local selected flower, fall back to the deterministic local start positions for focused Flow and show a concise experimental warning.

The fallback threshold must be derived from the local flower ring geometry/card size, not from an arbitrary viewport constant.

Do not individually clamp nodes after fCoSE.

## 9. Peripheral compact Flow stays V5-style

Keep:
- semantic kind silhouette;
- provider overlay;
- bookmark cue;
- thin Task-to-glyph hairline;
- one visual per Flow;
- cap 20 + `+N`.

You may increase compact geometry from 32 px only if needed for readability, but stay within 32–40 px and record the exact value.

Do not return to generic circular provider dots.

## 10. Edges

Task-to-Task edges keep current canonical rendering.

Selected Task -> focused Flow keeps canonical relation styling/direction, but endpoints must use the focused medium-card rectangle dimensions.

Compact peripheral Flow:
- canonical long edge remains suppressed;
- thin non-directional presentation hairline remains.

No new router.

## 11. Focus transition

On Task A -> Task B:
- Task positions remain unchanged;
- A's focused Flow collapses to compact halo;
- B's Flow opens locally around B;
- presentation bounds update from actual visible hybrid geometry;
- no backend reload solely for presentation;
- no canonical/controller position mutation.

Measure both Task drift and peripheral Flow movement.

## 12. Required fixtures

Add/reuse deterministic fixtures for:

### A. Distant canonical Flow
Selected Task has direct Flow with canonical coordinates hundreds/thousands of px away.

Expected:
- focused Flow opens near selected Task;
- hidden old coordinates do not inflate hybrid bounds.

### B. 10–12 focused Flow
Expected:
- multiple local slots/rings;
- no focused-card overlap;
- selected edges remain local.

### C. Nearby Task obstacle
Selected flower opens beside another Task.

Expected:
- focused start/refinement avoids the nearby Task rectangle.

### D. Mixed flower + compact halo
Focused medium cards and another Task's compact halo coexist without avoidable overlap.

### E. Focus A -> B
Expected:
- Task drift 0;
- A collapses;
- B opens locally;
- bounds remain presentation-based.

### F. Overview
No selected Task:
- compact halos only;
- bounds come from visible Tasks/glyphs, not hidden canonical Flow cards.

## 13. Required metrics

For Preserve and Relax record:

- Task max drift;
- focused Flow count;
- compact Flow count;
- focused Flow moved >1 px from deterministic local start;
- max focused displacement;
- median focused radius;
- max focused radius;
- focused-vs-Task overlaps;
- focused-vs-focused overlaps;
- focused-vs-compact overlaps;
- compact-vs-Task overlaps;
- compact-vs-compact global overlaps;
- deterministic repeatability;
- duplicate Flow visual count;
- focus-change peripheral Flow moved >1 px / max displacement;
- hybrid presentation bounds width/height;
- same fixture canonical-all-node bounds width/height for comparison.

No production telemetry.

## 14. Acceptance target

Promising V6 result:

- Tasks remain a recognizable stable skeleton;
- selected Flow forms a compact local flower around selected Task;
- no long rays caused only by stale Flow coordinates;
- hybrid fit no longer collapses due to hidden distant Flow positions;
- compact peripheral halos remain readable;
- fCoSE improves packing without destroying flower locality.

Do not reject merely because Flow moves.

Negative result if:
- Task drift appears;
- selected flower still disperses far from anchor;
- presentation bounds still depend on hidden Flow;
- overlap/readability is worse than V5.

## 15. Scope exclusions

Do not implement:
- finite/ongoing Task property;
- infinity/direction visualization;
- Task hierarchy / `part_of`;
- far-horizon semantic zoom;
- Areas/islands;
- Graphviz retry;
- new layout library;
- edge-routing library;
- custom SVG/icon asset system;
- backend/API/schema changes;
- DuckDB fix;
- production deploy.

## Focused proof

Add tests proving at minimum:

1. Current stays startup/default.
2. Existing V1/V2/V3B/V4 remain unchanged.
3. People mode unchanged.
4. Task positions are exact current `GraphLayout` positions.
5. Focused Flow start does not use distant old canonical coordinates.
6. Focused deterministic starts avoid selected Task and other Task fixtures.
7. Focused medium-card dimensions are used in geometry.
8. Hybrid presentation bounds ignore hidden distant canonical Flow rectangles.
9. Hybrid fit uses presentation bounds.
10. Preserve/Relax keep Task drift <=1 px, target 0.
11. Focused locality metrics are recorded.
12. Locality fallback preserves Tasks and uses deterministic local starts.
13. Selected canonical edge endpoints use focused-card dimensions.
14. Peripheral compact marks/hairlines remain.
15. No duplicate Flow visuals.
16. Focus A->B leaves Task drift 0.
17. Switching back to Current uses unchanged controller state.
18. Existing relevant graph/V1/V2/V3B/V4/V5/Task Profile tests remain at known baseline.
19. No backend/schema/ontology/deploy change.

Run:
- `flutter pub get`;
- current Graph workspace/controller/layout/screen tests;
- V1 tests;
- V2 ELK tests;
- V3B fCoSE tests;
- V4 Focus LOD tests;
- V5 hybrid tests;
- new V6 local-flower/bounds tests;
- Task Profile UI tests;
- Flutter analyze touched files;
- `flutter build linux --debug`;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA;
- record focused card size;
- record any compact glyph size change;
- record Preserve/Relax metrics;
- record canonical-all-node bounds vs presentation bounds on the distant-flow fixture;
- record known visual limitations;
- do not start ongoing/infinity work automatically;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Human real-data review decides whether this near-field hybrid becomes the product-map base.
