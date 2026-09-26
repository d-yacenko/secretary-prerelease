# Current task — Visual Task Map V7B: Dandelion geometry + angular topology guard

V7A finite/ongoing completion mode is accepted.

Refine only the existing experimental `LOD+fCoSE` near-field geometry.

The product model is now stable enough for this pass:
- finite Task = rectangular work node;
- ongoing Task = circular 144×144 Direction/activity anchor;
- compact Flow = dandelion satellites;
- selected finite Task = local medium-card flower;
- selected ongoing Task keeps Flow compact.

The remaining visual defect is angular packing:
- compact Flow often collapses below/to one side of its Task instead of surrounding it;
- focused medium cards can share nearly the same radial axis, making edges visually coincide.

No new dependency.
No backend/schema/migration change.
Do not start `part_of`.
Do not deploy production.

## 1. Keep product/runtime boundaries

Keep unchanged:
- `Текущий` startup/default renderer;
- V1/V2/V3B/V4 experiments;
- existing `LOD+fCoSE` renderer identity;
- finite/ongoing semantics from V7A;
- Task canonical positions;
- fCoSE 0.1.0 only.

V7B refines geometry helpers used by `LOD+fCoSE`.

Do not add another renderer.

## 2. Task anchors remain fixed

Every finite and ongoing Task keeps the same canonical GraphLayout center.

- finite geometry: 186×100 rectangle;
- ongoing geometry: 144×144 circle centered on the same canonical center.

Task center drift after every refinement/fallback must remain 0 px.

No presentation position is persisted.

## 3. Balanced compact dandelion starts

The current compact start allocator greedily takes the first free angular slot. Replace the HYBRID compact-start behavior with a deterministic balanced ring allocator.

For one Task halo:

- use the actual anchor presentation rect, not an assumed 186×100 rectangle;
- finite anchors therefore use the finite Task rect;
- ongoing anchors use the 144×144 circle's bounding rect and same center;
- use the actual hybrid compact glyph size (currently 32×32), not the older V4 24 px collision size;
- for a small number of marks, distribute them across the full 360° instead of filling consecutive slots;
- use concentric rings only when needed;
- stagger successive ring phase by half of the previous ring's nominal angular slot so marks on different rings do not reuse the same radial axes;
- keep bookmark/recency/id ordering only for assigning semantic priority to the deterministic slots; it must not cause all early marks to occupy one quadrant.

Example intent:
- 1 mark: one deterministic direction;
- 2: opposite sides;
- 3: roughly 120° apart;
- 4: roughly 90° apart;
- 6: roughly 60° apart;
- larger sets: balanced inner ring(s), then staggered outer ring(s).

Do not require these exact cardinal orientations; require deterministic full-circle balance.

## 4. Compact start collision rules

Balanced compact starts must avoid:
- their own Task anchor;
- every other visible Task presentation rect;
- focused medium Flow cards when present;
- same-halo compact marks;
- already reserved compact marks from previously allocated visible halos.

Allocate halos in deterministic anchor-id order so cross-halo reservation is repeatable.

When a preferred angular slot is blocked:
- search nearby angular alternatives deterministically;
- prefer preserving the current ring before moving to the next ring;
- if needed move outward;
- do not move Tasks.

Keep cap semantics:
- <=20 individual compact marks;
- one `+N` mark for overflow;
- overflow participates in the same balanced geometry.

## 5. Shared projection compatibility

V4 Focus LOD may keep its existing 24 px visual if desired.

Do not silently use 24 px collision geometry for the 32 px hybrid glyph.

Choose one clean implementation:
- parameterize the presentation projection/slot allocator with mark size and anchor rects; or
- keep a hybrid-only balanced allocator.

Prefer reuse without forcing V4's legacy visual style to change.

Canonical workspace data must remain untouched.

## 6. Focused finite-Task flower starts

Replace the current greedy focused-card slot scan with a count-aware balanced local ring plan.

For focused medium cards (156×76):

- use the selected finite Task center as anchor;
- if count fits one ring, spread all cards across the full circle;
- if multiple rings are needed, stagger adjacent ring phases by half a nominal inner-ring slot;
- no two planned cards on adjacent rings should intentionally use the exact same radial axis;
- avoid every visible finite/ongoing Task obstacle;
- avoid focused-card overlaps;
- deterministic ordering stays bookmark -> recency -> id.

Do not use canonical old Flow coordinates.

## 7. Focused preferred-slot obstacle handling

If an intended balanced focused slot is blocked by another Task:

- search deterministic nearby angles around the preferred angle;
- preserve angular separation as much as possible;
- then try the next ring;
- never move the blocking Task.

Do not turn this into a general layout engine.

## 8. fCoSE remains a helper, not topology owner

Keep Preserve / Relax.

Run fCoSE after the balanced deterministic starts, but add a presentation topology guard.

The guard decides whether to ACCEPT the refined geometry or fall back to the balanced start geometry.

Do not individually clamp nodes after fCoSE.

## 9. Focused-flower topology guard

For the selected finite Task flower, compare refined centers to balanced start centers.

The refined flower is acceptable only if all existing V6 locality/overlap rules pass AND:

- every focused card remains within 22.5° angular deviation from its own balanced start direction;
- the minimum angular separation between any two focused-card center rays is at least 11.25°;
- no exact/near-exact radial-axis collapse occurs.

These thresholds derive from the existing 8-slot 45° focused reference:
- max drift = half slot;
- minimum separation = quarter slot.

If the focused refinement violates the guard:
- reject the entire focused fCoSE pass;
- display all focused cards at balanced deterministic starts;
- show a concise experimental warning.

Do not reject because radial distance changes within the existing locality limit.

## 10. Compact-halo topology guard

For compact halos, compare each mark's refined ray from its presentation anchor to its balanced start ray.

Use the existing 12-slot 30° compact reference.

Accept the compact fCoSE pass only if:
- no required node is missing;
- overlap metrics do not worsen versus balanced raw starts;
- each compact mark moves by no more than 30° around its own anchor from its balanced start direction.

For halos with >=4 visible marks additionally require:
- the refined halo remains distributed across at least 3 quadrants.

For halos with >=6 visible marks require:
- at least 4 quadrants.

If any visible halo fails the topology guard:
- reject the entire compact refinement pass;
- use the globally reserved balanced compact starts for all compact marks/overflows;
- show a concise warning.

This all-or-pass fallback is intentional: it avoids mixing one reverted halo with other refined halos and reintroducing cross-halo collisions.

## 11. Hairlines and selected canonical edges

Keep current styling.

But after geometry changes prove:

- compact hairlines use the final accepted compact positions;
- hairlines begin on finite rectangle / ongoing circle boundary correctly;
- selected focused canonical edges use the final accepted focused positions;
- no pair of selected focused edges is near-collinear below the 11.25° guard when >1 focused card exists.

No router.

## 12. Ongoing focus

Keep V7A behavior:
- selecting ongoing does not expand direct compactable Flow;
- its compact dandelion should now be visibly balanced around the circle when space permits;
- finite Task neighbors stay normal.

Do not add hierarchy.

## 13. Finite focus

Keep V6/V7A behavior:
- finite Task opens local medium-card Flow;
- peripheral Tasks keep compact dandelions;
- the selected flower now uses balanced phased rings before fCoSE.

## 14. Required deterministic fixtures

Add/reuse:

### A. Small halos
For one isolated finite Task test compact counts:
- 2;
- 3;
- 4;
- 6.

Expected: full-circle distribution, not consecutive-sector packing.

### B. Ongoing dandelion
One 144×144 ongoing anchor with 8 compact Flow marks.

Expected:
- compact around all sides;
- no expansion when selected;
- hairlines meet circle boundary.

### C. Multi-ring compact
20 marks + overflow.

Expected:
- multiple rings;
- ring phases stagger;
- no intentional repeated radial axes.

### D. Two close halos
Two nearby Tasks each with >=8 compact marks.

Expected:
- deterministic global reservation;
- raw balanced starts have zero avoidable cross-halo overlap;
- fCoSE accepted only if topology guard passes.

### E. Focused 4-card flower
Expected:
- cards distributed around selected finite Task.

### F. Focused 12-card flower
Expected:
- multiple phased rings;
- no same-axis inner/outer intentional pair;
- after accepted refinement minimum angular separation >=11.25°.

### G. Focus + nearby ongoing obstacle
Selected finite Task flower beside a round ongoing Task.

Expected:
- no overlap with 144×144 circle;
- Task centers unchanged.

## 15. Required metrics

For balanced raw starts and Preserve/Relax final accepted geometry record:

Compact halos:
- visible mark count;
- occupied quadrant count per halo;
- minimum angular separation per halo;
- largest empty angular gap per halo;
- max angular drift from balanced start after fCoSE;
- compact-vs-Task overlaps;
- compact-vs-compact overlaps globally;
- number of compact passes accepted vs topology-fallback.

Focused flower:
- focused count;
- ring count;
- minimum angular separation;
- count of ray pairs separated by <11.25°;
- max angular drift from balanced starts;
- max radial distance;
- focused-vs-Task overlaps;
- focused-vs-focused overlaps;
- fCoSE pass accepted/fallback.

Global:
- Task center drift;
- duplicate Flow visuals;
- deterministic repeatability;
- focus A -> B Task drift;
- presentation bounds.

No production telemetry.

## 16. Acceptance target

A good V7B result should visibly read as:

- compact Flow forms a dandelion around its Task/Direction rather than a row below it;
- small halos use the whole circumference;
- ongoing circles feel like cluster centers;
- selected medium cards surround the finite Task rather than stacking on a shared ray;
- fCoSE still helps with collision packing but cannot destroy the radial topology;
- Task geography remains stable.

Do not optimize aesthetics beyond this geometry pass.

## 17. Scope exclusions

Do not implement:
- `part_of` / `contains`;
- Task hierarchy;
- another Direction kind;
- automatic ongoing classification;
- far-horizon semantic zoom;
- Areas/islands;
- new layout library;
- Graphviz;
- edge router;
- backend/API/schema/migration changes;
- fixes for the five known unrelated red UI/detail tests;
- production migration/deploy;
- DuckDB fix.

## Focused proof

At minimum prove:

1. Current remains startup/default.
2. V7A finite/ongoing behavior remains unchanged.
3. Task center drift remains 0 px.
4. Hybrid compact geometry uses actual 32 px marks.
5. Ongoing compact anchor uses the 144×144 presentation rect.
6. Small-halo 2/3/4/6 cases distribute over the full circumference.
7. Compact multi-ring phases are staggered.
8. Cross-halo raw reservation is deterministic.
9. Focused one-ring allocation is count-aware/full-circle.
10. Focused multi-ring phases are staggered.
11. Balanced focused starts avoid finite and ongoing Task obstacles.
12. Focused fCoSE topology guard enforces 22.5° own-ray drift and 11.25° pair separation.
13. Compact fCoSE topology guard enforces <=30° own-ray drift and quadrant coverage.
14. Fallback reverts an entire focused/compact pass, not individual nodes.
15. Hairlines/edges use final accepted positions.
16. Ongoing selection still keeps Flow compact.
17. Finite selection still opens local Flow.
18. No duplicate Flow visuals.
19. Deterministic repeatability.
20. Existing relevant V4/V5/V6/V7A tests stay at baseline; unrelated known failures are not in scope.
21. No backend/schema/hierarchy/deploy change.

Run:
- Focus LOD projection tests;
- V5/V6 hybrid tests;
- V7A ongoing visual tests;
- new V7B dandelion/angular tests;
- current Graph regression tests;
- Task Profile UI regression tests;
- Flutter analyze touched files;
- `flutter build linux --debug`;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA;
- record compact/focused ring allocation algorithm;
- record topology-guard thresholds and acceptance/fallback counts;
- record fixture angular metrics;
- record whether Preserve or Relax more often preserves topology;
- record known visual limitations;
- do not start `part_of` automatically;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Human real-data review decides whether V7B geometry is accepted before Task hierarchy work.
