# Current task — TL2.1.1 exclude proposed secondary edges from canonical geography

Authorized base: `6669424f4effa661fd11ad401e87cd3605fc941d`.
TL2.1 implementation under review: `4f4d3d93755680fd4b70fa18f59f61035191f7a5`.
Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`.

TL2.1 sibling ordering is broadly correct, but Architect review found one narrow semantic defect before human verification.

## Defect

The new sibling-order optimizer itself filters to confirmed secondary Task relations. However `projectTaskMapHierarchy` still adds every non-rejected, non-`part_of` visible Task edge to `layoutEdges`.

Those `layoutEdges` are then used by:

- `GraphLayout.computePositions(...)` for baseline sibling order;
- `packingAdjacency` / component grouping;
- free-Task layout.

Therefore a **proposed** `depends_on`, `references`, or `related_to` edge can still change canonical Task geography indirectly even though it is not scored by the TL2.1 reorder objective.

This violates the accepted invariant: proposed/rejected relations may be rendered according to presentation rules, but only confirmed Task relations may influence canonical Task centers.

## Required correction

For canonical Task geography:

- confirmed `part_of` continues to define the structural forest;
- only **confirmed** non-`part_of` visible Task↔Task relations may enter canonical layout/baseline/component-packing/orientation inputs;
- proposed non-`part_of` relations must not affect canonical positions or component membership;
- rejected relations must continue to have no effect;
- proposed relations may still be drawn by the normal Graph presentation layer; this task changes geography inputs only.

Prefer one clear canonical-layout filter rather than scattering state checks across several downstream helpers.

Do not change relation visibility semantics in the UI.

## Algorithm version

Because canonical coordinates can differ from the current TL2.1 implementation, bump:

- `task-map-v2.1` -> `task-map-v2.1.1`.

A usable v2.1 snapshot must be treated as old and replaced once by a complete v2.1.1 snapshot through the existing complete-topology + optimistic PUT path.

No schema/Alembic change.

## Required regressions

Add tests proving:

1. A proposed `depends_on` between Task leaves yields exactly the same canonical positions/components as no such edge.
2. The same edge when confirmed can still reorder/shorten the relevant siblings as TL2.1 intended.
3. Proposed `references` and `related_to` likewise do not alter canonical geography.
4. Rejected secondary edges remain inert.
5. A proposed secondary edge between otherwise separate Task components does not merge those components for canonical packing; confirmed may merge according to current semantics.
6. A usable `task-map-v2.1` snapshot is replaced once by complete `task-map-v2.1.1`; usable v2.1.1 is reused.
7. Existing TL2/TL2.1 geometry fixtures stay green:
   - recursive local flowers;
   - six-leaf confirmed sibling shortening;
   - multiple confirmed secondary links;
   - mixed leaf + subtree;
   - five-leaf even spread;
   - deep hierarchy;
   - no Task rect overlap.

Keep GFX-A/B/C, Tasks<->People shared world/camera, People anchors/clusters/shelf/cue, Graph smoke/large-canvas green.

## Human-check build

After correction and tests pass, produce a fresh self-contained Linux debug bundle from a clean detached checkout of the exact TL2.1.1 implementation SHA.

Record exact source SHA, UTC build time, executable path, launcher SHA-256, kernel SHA-256 if present, and adjacent `BUILD_INFO.txt`.

Human checklist remains focused on:
- «Трудоустройство в МФТИ» ↔ «Преподавание Java в МФТИ» becoming clearly shorter where sibling reorder permits;
- Teaching/Publications/Courses remaining coherent local flowers;
- no overlaps;
- quick GFX-A/B/C spot-check.

Page tearing remains explicitly out of scope until Semantic Windows v2.

Do not install automatically.

## Explicitly out of scope

- Semantic Windows v2 / page partitioning.
- Continuation connectors.
- Page/window limits.
- New relation types or ontology changes.
- Backend/API/schema/Alembic changes.
- Production deploy/ref movement.
- Global optimizer/manual positioning.
- Other Graph polish.

## Completion contract

When complete:

1. record root cause, implementation SHA, version bump, regression results, bundle provenance/hashes, and limitations in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus TL2.1.1 summary and human-check bundle path;
3. commit/push to `main`;
4. STOP.

Do not begin Semantic Windows v2 until Architect review + user human verification.
