# Current task — PL1-G4.2 shared world frame + compact same-anchor People clusters

Authorized base: `8db2e35f3e3f481c6badd15a03accf7f36b933fd`.
Production/runtime remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.
Production Alembic remains `0052 / 0052`.

PL1-HG3 human gate failed on real production data. Two client-only defects must be corrected before another bundle/human gate:

1. Tasks and People use the same canonical Task centers but still render through mode-specific normalized canvas frames, so real Tasks<->People switching can visibly shift the whole world.
2. People sharing exactly the same Task anchor are separated too aggressively by the generic radial anti-overlap algorithm.

No backend/schema/production change is authorized in this slice.

## 1. Make the canonical unrooted world frame genuinely shared

The single-world invariant must be constructive, not compensatory.

For healthy unrooted canonical mode:

- canonical Task centers define one world coordinate system;
- Tasks and People must use one stable world-frame origin;
- the current layer's visible/presentation bounds may change canvas extent and manual Fit, but must not redefine world origin;
- do not derive the shared origin independently from `hybridPresentationBounds(...).left/top` in Tasks and `GraphLayout.computeBounds(...).left/top` in People.

Refactor the screen/frame code so that the same world coordinate maps to the same canvas-local coordinate in Tasks and People.

A preferred implementation is a small explicit shared-world-frame helper/model whose origin is derived once from the full canonical Task world and then reused for both layers. If rendered presentation extends beyond the canonical Task bounds, grow extent as needed without moving that shared origin. Do not introduce a second People world.

The solution must also handle a real UI-frame change between modes. In particular, Tasks may show the semantic-window/truncation banner while People does not. If the graph viewport's global screen origin changes, preserve the camera so the same canonical world point stays on the same **global screen pixel**, not only at the same local canvas coordinate. You may either keep the viewport origin stable or compensate using the actual viewport-global delta; tests must prove the result.

Remove or narrow `_holdWorldPoint` if its previous mode-specific-bounds compensation is no longer needed. Do not leave two competing frame/camera systems.

## 2. Realistic parity regression

The current one-Task/one-Person camera test is insufficient.

Add a widget regression that resembles the failed human gate:

- several canonical Tasks at distinct world positions;
- Tasks mode shows a semantic-window subset and a truncation/window banner;
- at least two single-anchor People are tied to distinct Tasks;
- at least two People share one Task anchor;
- People mode does not show the Task cards;
- start in Tasks, perform manual Fit, record the **global screen centers** of the relevant Task cards;
- switch to People without user pan/zoom;
- each single-anchor Person must appear at the exact corresponding Task world point within a small epsilon;
- switch back to Tasks and verify the same Task points return to the same global pixels and scale;
- repeat with different visible Task-window membership to prove current-window bounds do not change parity.

The test should fail on `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.

## 3. Compact same-anchor clustering

Replace the current behavior where identical-anchor People are independently sent to large radial slots.

Semantics:

- one Person with an anchor set -> marker center equals that anchor/centroid;
- People with the exact same distinct Task-anchor set belong to one presentation cluster;
- same Task repeated across roles is already deduplicated and remains so;
- members of one identical-anchor cluster must be packed tightly with a small visual gap and no overlap;
- the **cluster center** must remain on the shared Task/centroid point, within deterministic rounding epsilon;
- member ordering is deterministic by Person id;
- no role/salience/recency/authority weighting;
- no persisted Person coordinates.

For two People on the same single Task, their 140x44 markers should read visually as adjacent members of one cluster, not as separate Task regions. Use a small named intra-cluster gap, target **4–8 logical px**.

For larger identical-anchor groups, use a compact deterministic stack/grid around the same base rather than the current diagonal-radius rings.

Only after same-anchor clusters are formed may different anchor groups be displaced minimally to avoid actual cluster overlap. Different anchor groups should keep their coarse anchor/centroid regions.

Do not reintroduce large semantic spacing merely to maximize whitespace.

## 4. Preserve the rest of PL1-G4/G4.1

Keep unchanged:

- one-anchor and multi-anchor Task-center/centroid semantics;
- fail-closed whole-grid fallback on incomplete/missing anchor truth;
- 140x44 unrooted Person markers;
- rooted Person/inspector behavior;
- deterministic unanchored right-side strip;
- strip remains to the right of final anchored marker bounds and full canonical Task bounds;
- adding/removing unanchored People does not move anchored clusters;
- Task cards absent from People-only mode;
- selected Task semantic-window index restored after People -> Tasks;
- G3 canonical Task centers/persistence contract.

## Required tests

Cover at least:

- realistic multi-Task Tasks->People->Tasks global-pixel parity with Task truncation/window banner;
- parity across different Task semantic-window subsets;
- scale preserved across healthy mode switch;
- mode switch itself does not auto-Fit;
- one single-anchor Person center == Task center;
- two same-anchor People are non-overlapping, separated by only the named 4–8 px intra-cluster gap, and their cluster center == Task center;
- 3+ same-anchor People pack compactly and deterministically around the same anchor;
- input order permutations do not swap Person ids/positions;
- different-anchor clusters may separate only when they actually collide;
- multi-anchor centroid semantics unchanged;
- missing/incomplete anchors still trigger whole-grid fallback;
- dense same-anchor group plus unanchored People still keeps every anchored marker left of the strip;
- G3 Task canonical-position tests and existing People screen/world-camera regressions remain green.

Run focused Flutter graph/People/task-layout tests, relevant smoke/large-canvas tests, `flutter analyze` for changed Dart files, and `git diff --check`.

## Explicitly out of scope

- No backend/API changes.
- No Alembic changes.
- No production ref movement or deploy.
- No new bundle in this slice.
- No installed-client replacement.
- No combined Tasks+People view.
- No Task<->Person canvas lines.
- No social/authority ontology.
- Do not declare PL1 accepted.

## Completion contract

When complete:

- record implementation SHA, changed files, exact tests/analyze/diff results, the new shared-frame rule, same-anchor packing rule, and any limitation in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-G4.2 summary;
- commit/push to `main`;
- STOP.

Do not deploy or build another human-gate artifact without a new explicit authorization.
