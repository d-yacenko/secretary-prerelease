# Current task — Visual Task Map V4: Focus LOD + compact Flow satellites

The architect visualization checkpoint is recorded. The current custom Graph is the leading product-map foundation.

Implement only a reversible presentation spike that keeps the current stable Task geography but changes how Flow/context is rendered outside the active focus.

No new layout library is required in V4.

Do not replace `GraphLayout`.
Do not change ontology/backend/Task semantics.
Do not start Areas/islands/hierarchy.
Do not retry Graphviz or tune fCoSE.

## Product hypothesis

The current graph is useful because Tasks and their local “flowers” form a stable spatial map, but it becomes a gray/dense field because every Flow object is rendered as a full ~186x100 card.

V4 tests a focus-lens / level-of-detail model:

- Tasks remain full cards and stable geographic anchors.
- The selected Task keeps its direct Flow/context as full cards.
- Flow around non-selected Tasks becomes compact icon-like satellites/halos with no title/date text.
- Changing selected Task moves the lens: the old flower collapses, the new flower expands, while global Task coordinates do not move.
- In overview with no selected Task, Tasks are full cards and eligible Flow is compact.

This is presentation only. Canonical objects and edges stay unchanged.

## 1. Preserve existing renderers

Keep unchanged and available:
- `Текущий` current renderer as startup/default;
- V1 GraphView experiment;
- V2 ELK experiment;
- V3B fCoSE experiment;
- People mode current renderer.

Add one explicit experimental Task renderer, label equivalent to `Фокус LOD`.

Do not silently change the default current renderer in this spike.

## 2. Stable Task geography is an invariant

All Task card top-left coordinates in Focus LOD MUST be exactly the current `GraphLayout` / controller visible positions.

Selecting another Task must not cause Task coordinates to be recomputed or moved by the LOD projection.

Do not persist any new coordinates.

Do not run ELK/fCoSE/another engine inside this renderer.

## 3. Compactable Flow/context kinds

For this spike, compact only already-known evidence/context kinds:

- `email`;
- `calendar_event`, `event`;
- `file`, `document`, `dataset`, `folder`;
- `note`;
- `web_page`;
- `chat`, `message`, `chat_message`.

Do NOT compact:
- `task`;
- `person`;
- `project`;
- `label`;
- `scheduled_activity`;
- `temporal_hint`;
- unknown kinds.

Unknown/non-Flow kinds keep the current full-card representation.

Do not create or persist a new Flow subtype model.

## 4. Selected Task: full flower

When the selected object is a Task:

- the selected Task stays at its current global position;
- every already-loaded directly connected compactable Flow object is rendered exactly once as a FULL current-style card;
- those full Flow cards use their existing current graph positions;
- current full-card edge rendering for the selected Task and its full Flow neighbors remains available;
- current detail panel / source navigation / bookmarks / selection behavior remains canonical.

A Flow object that is full because it is directly connected to the selected Task must NOT also appear as a compact satellite elsewhere.

Task-to-Task neighbors remain normal Task cards.

Do not fetch additional neighbors.

## 5. Non-selected Task: compact halo

For compactable Flow not expanded by the selected Task:

- render a small satellite around one non-selected connected Task;
- Task card remains full-size;
- satellite has no visible title/body/date;
- satellite should show provider/source identity when available;
- otherwise use existing kind icon;
- preserve a visible read-only bookmark cue when the underlying object has a bookmark;
- tooltip/semantics may include the underlying object title/provider for accessibility, but no full text is painted in the normal satellite body.

Suggested initial satellite visual size: approximately 20–28 px. Choose one deterministic size and record it.

Reuse existing provider/kind/bookmark presentation primitives rather than inventing parallel icon semantics.

## 6. Presentation anchor for Flow connected to multiple Tasks

Do not duplicate one canonical Flow object around multiple Tasks.

If an eligible compact Flow object is connected to multiple visible Tasks and is not expanded by the selected Task, choose exactly one PRESENTATION anchor Task:

1. among its directly connected visible Tasks, choose the Task whose existing `GraphLayout` center is geometrically closest to the Flow object's existing `GraphLayout` center;
2. tie-break by Task id.

This anchor is presentation-only:
- do not persist it;
- do not create/change relations;
- do not imply ownership;
- do not change canonical edges.

Add a code comment making this explicit.

## 7. Deterministic satellite placement

Compute satellite positions locally from the anchor Task position; do not reuse the Flow card's old full-card rectangle as the satellite position.

Use deterministic concentric rings around the Task card.

Requirements:
- same workspace + same Task positions + same satellite set => same satellite positions;
- satellites must not overlap the anchor Task card;
- avoid overlapping any visible Task card rectangle;
- avoid satellite-vs-satellite overlap within the same halo;
- use multiple rings as needed;
- keep the algorithm small and presentation-specific;
- do not build a general graph layout engine.

You may reuse/extract the mathematical ideas already present in `GraphLayout` (ring radius/angular slots), but do not couple canonical global Task layout to satellite size.

If all allowed satellite slots are exhausted, use overflow aggregation rather than moving Tasks.

## 8. Cap and overflow

Do not render unlimited individual satellites.

Initial hard cap:
- maximum 20 individual satellites per Task halo.

If a Task has more eligible compact Flow:
- render 20 individual satellites;
- render one compact overflow marker `+N` for the remainder.

The cap is a presentation safety bound, not a data limit.

The underlying objects remain in workspace data and become available as full cards when the Task is selected.

For choosing the 20 individual satellites:
1. bookmarked objects first;
2. then use an already-available object time/recency value if the client has one with clear semantics;
3. otherwise deterministic object id.
Do not introduce an opaque importance score.
Do not add LLM ranking.

If using recency would require inventing new timestamp semantics, skip it and use deterministic id after bookmarks.

## 9. Compact edge behavior

For V4:
- keep all Task-to-Task edges using current rendering;
- keep normal current edges for the selected Task's expanded full Flow cards;
- do NOT draw global/current long edges to compact satellites;
- the halo proximity is the compact representation of that Task↔Flow relation.

Do not add an edge router.

Do not delete/change canonical edges; this is renderer-only suppression.

## 10. Lens interaction

Task click/select behavior remains canonical.

When a different Task is selected:
- previous selected Task remains at same coordinate;
- its eligible Flow collapses to compact satellites;
- new selected Task remains at its same coordinate;
- its direct eligible Flow expands to full cards at their existing current positions;
- no backend reload is required solely for this presentation transition;
- no Task global position changes.

Satellite click in V4 should select its PRESENTATION anchor Task, moving the lens to that Task. The underlying Flow object becomes directly accessible after expansion as a normal full card.

Do not invent a second detail-panel state machine for satellites.

## 11. Focus/dimming

Reuse the current focus/dimming semantics rather than replacing them.

Selected Task and its expanded direct neighbors remain visually emphasized.

Peripheral Tasks and their compact halos may inherit the current dimming behavior.

Do not add attention scoring.

## 12. Projection architecture

Keep LOD logic outside canonical models.

Introduce a small presentation projection equivalent to:
- full-card object ids;
- Task anchors;
- compact satellite records with source object id + anchor Task id + position + visual metadata;
- overflow records;
- edge visibility decision.

Do not put presentation anchor/satellite state into API models, DB, controller canonical workspace data, or Task ontology.

The same workspace objects/edges must remain unchanged when switching among renderers.

## 13. Fixtures / cases

Add deterministic focused fixtures for:

### A. Overview
- 4–6 Tasks;
- 5–12 Flow objects around several Tasks;
- no selected Task.

Expected: all Tasks full, eligible Flow compact.

### B. Selected flower
- selected Task with 8–12 direct Flow neighbors;
- at least two other Tasks with their own Flow.

Expected: selected flower full; other Flow compact; Task coordinates unchanged.

### C. Multi-Task Flow
- one Flow connected to two visible Tasks.

Expected: rendered once, deterministic nearest-Task presentation anchor unless selected Task expands it.

### D. High-count halo
- one non-selected Task with at least 35 eligible Flow objects.

Expected: <=20 individual satellites + one `+N` marker.

### E. Close Tasks
- two Task cards close enough that naive satellites would hit the other Task.

Expected: ring-slot placement avoids visible Task rectangles or overflows safely without moving Tasks.

## 14. Required measurements

Record for the fixtures:

- number of full Task cards;
- number of full Flow cards;
- number of individual satellites;
- overflow count;
- Task-position drift before/after selection change (must be 0 px);
- satellite-vs-Task overlap count;
- satellite-vs-satellite overlap count per halo;
- deterministic repeatability;
- count of Flow objects visually represented more than once (must be 0);
- high-count result under the cap.

Also record a simple density comparison for the selected-flower fixture:
- current renderer number of full non-Task cards;
- Focus LOD number of full non-Task cards + compact satellites.

No production telemetry.

## 15. Scope exclusions

Do not implement in V4:
- new library/layout engine;
- Graphviz retry;
- fCoSE tuning;
- ELK changes;
- Areas/islands/label regions;
- Task hierarchy / contains / part_of;
- new semantic zoom thresholds beyond what is strictly needed for this renderer;
- true fisheye;
- 3D;
- opaque importance ranking;
- backend/API/schema changes;
- new data fetch;
- production deploy;
- DuckDB fix.

Do not solve the “selected Task has 70 Flow cards” problem generally yet. V4 only records that as a future local-flower concern.

## Focused proof

Add tests proving at minimum:

1. Current renderer remains startup/default.
2. V1/V2/V3B remain available unchanged.
3. People mode unchanged.
4. Focus LOD Task positions equal current `GraphLayout` positions.
5. No selection => eligible Flow compact, Tasks full.
6. Selected Task => its loaded direct Flow is full exactly once.
7. Other eligible Flow remains compact.
8. Multi-Task Flow renders exactly once with deterministic nearest presentation anchor.
9. Satellite visually contains provider/kind cue and bookmark cue when applicable.
10. Satellite has no normal visible title/date text.
11. Satellite placement deterministic.
12. Satellite placement avoids Task-card rectangles in fixture.
13. Per-halo satellite overlap count is zero in fixture.
14. High-count halo renders <=20 individual satellites plus correct `+N`.
15. Selection change produces 0 px Task-position drift.
16. Satellite click selects its anchor Task.
17. Compact Flow canonical objects/edges are not mutated.
18. Switching back to Current uses unchanged workspace/controller data.
19. Existing current/V1/V2/V3B relevant tests remain at known baseline.
20. No backend/schema/ontology/deploy changes.

Run:
- existing current Graph workspace/controller/layout/screen tests;
- V1 Task Map tests;
- V2 ELK tests;
- V3B fCoSE tests;
- new Focus LOD projection/UI tests;
- Task Profile UI tests;
- Flutter analyze touched files;
- `flutter build linux --debug`;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks in `PROJECT_STATE.md`;
- record satellite size/ring algorithm/cap;
- record fixture measurements and density comparison;
- explicitly state any cases where compact halos are visually/geometrically weak;
- do not select a final library or start another geometry spike;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Human review on real data decides whether Focus LOD becomes the next product-map direction.
