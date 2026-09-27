# Current task — Graph G3A-R2: keep Task daisies with their hierarchy during packing

G3A is accepted.
G3A-R1 implementation is accepted, but its human gate exposed a second, narrower layout defect.

Production backend/runtime and `origin/production` remain:
`489741540e30a775e2ea086f3976d7305512afe2`

Alembic remains:
`0050`

This task authorizes one bounded CLIENT layout corrective on `main` only.

NO backend deploy is authorized.
Do not implement the ontology/prompt corrective in this task.
Do not start `Скрыть связи`, G3B, S3, or H2D.

## Human evidence

On the exact C1 bundle:

- deleting the structural relation caused the publication “daisy” to gather correctly;
- re-adding the same structural relation scattered it again with long rays.

Therefore G3A-R1 authoritative refresh/fresh controller relayout is active, but the final presentation projection still produces bad geometry after confirmed hierarchy creation.

## Confirmed root cause

The screen applies:

`positions.addAll(projectTaskMapHierarchy(nodes: nodes, edges: edges).positions)`

AFTER controller layout.

Current `projectTaskMapHierarchy`:

1. recognizes confirmed `part_of` Tasks as hierarchy ids;
2. builds radial hierarchy components from those ids;
3. removes hierarchy ids from `freeIds`;
4. computes free connected components only among remaining free ids.

A visible non-`part_of` Task<->Task edge crossing from a hierarchy Task to a free Task is therefore ignored for component packing while the edge is still rendered.

This means adding confirmed `part_of` can pull a Direction into a hierarchy tree while leaving its existing related/referenced/dependent Task petals in separately shelf-packed components. The long rays are deterministic output of the hierarchy projector, not stale coordinates.

## Product invariant

**Structural parentage and visual packing are different concerns.**

- Confirmed `part_of` alone defines parent/child hierarchy, root, depth, and radial ancestry.
- Map-visible Task<->Task relations define visual packing affinity.
- A non-`part_of` cross-link must NEVER become hierarchy parentage.
- But a directly connected Task cluster must not be arbitrarily packed far away merely because one endpoint joined a `part_of` tree.

The concrete expected behavior:

When an existing Direction with a visible Task daisy is attached under another Direction using confirmed `part_of`, the Direction and its existing visible Task daisy move/repack together as one visual connected component. The petals must not remain behind with long rays.

## Canonical packing connectivity

For Tasks presentation, build a visual packing graph over visible Task nodes using:

- confirmed `part_of`;
- map-visible `related_to`;
- map-visible `references`;
- map-visible `depends_on`.

Preserve existing state semantics:
- proposed `part_of` does NOT alter hierarchy or packing geography until confirmed;
- rejected edges do not participate;
- hidden relation types do not participate;
- Flow/non-Task nodes do not determine Task packing geography.

Use the existing canonical relation presentation helpers rather than duplicating a relation vocabulary when practical.

## Part A — refactor TaskMapHierarchy projection around visual connected components

Refactor `projectTaskMapHierarchy` so that GLOBAL packing components are connected components of the visual Task packing graph above.

Within each visual packing component:

- confirmed `part_of` still defines one or more structural trees;
- structural tree placements remain radial/ancestral;
- Tasks not in a `part_of` tree remain non-hierarchy/free Tasks;
- visible non-`part_of` edges provide affinity between hierarchy trees and/or free Tasks;
- all members of the visual connected component are laid out locally before the whole component is shelf-packed globally.

Do NOT shelf-pack a free Task component separately when it has a visible Task<->Task path into a hierarchy component.

Disconnected visual components should still be globally packed independently.

## Part B — local placement guidance

The exact local algorithm may be refactored, but preserve these principles:

- keep the existing all-Task `baselinePositions` or an equivalent deterministic affinity skeleton;
- use that skeleton to retain locality for non-`part_of` Task relations;
- place each confirmed `part_of` tree around its actual root without turning cross-links into parentage;
- if two separate `part_of` trees are connected by a visible non-`part_of` Task relation, they may share one VISUAL packing component while remaining two distinct structural trees;
- avoid Task presentation rectangle overlap;
- include ongoing Direction circle size in clearance;
- remain deterministic for unchanged input.

It is acceptable to reposition the whole current Task visual component after a structural mutation. Stable geography across topology mutation is not required.

Do not implement a force-layout redesign or G3B.

## Part C — metrics / data structures

Current `TaskMapComponent.hierarchy` assumes a component is either hierarchy or free.

If the refactor creates mixed visual components, adjust internal projection metadata cleanly.

Do not lie in metrics:
- `hierarchyTreeCount` should continue to mean actual confirmed `part_of` trees, not “number of mixed components that contain at least one hierarchy”;
- free-component metrics may be renamed/refined internally if needed;
- no public REST/API contract depends on these client-only metrics.

Keep tests explicit about the new meaning.

## Part D — preserve accepted behavior

Preserve:

- G3A semantic windows;
- G3A-R1 authoritative refresh after Task<->Task topology mutation;
- Task<->Flow incremental behavior;
- canonical `part_of` child/source -> parent/target;
- ongoing Direction circle;
- Flow compact LOD/satellites;
- Preserve/Relax product meaning;
- selection/focus;
- relation arrows/dashes;
- direct relation inventory;
- proposed `part_of` does not move geography before confirmation;
- Flow coordinates do not inflate Task geography;
- independent disconnected Task clusters remain independently packed.

No backend changes.

## Required regression tests

Extend `task_map_hierarchy_test.dart` and focused Graph coverage with at least:

1. **exact hierarchy+daisy regression**
   - Direction `publications`;
   - several finite publication Tasks connected to it with visible non-`part_of` Task relations;
   - `publications part_of academy`;
   - after confirmation, academy + publications + publication Tasks belong to one VISUAL packing component;
   - publication petals stay locally close to `publications`;
   - no overlap.

2. **delete/add symmetry**
   - projection without the structural edge is locally compact;
   - adding confirmed `part_of` may rearrange the component but must not create a large cross-map separation;
   - removing it again remains compact.

3. **cross-link is not parentage**
   - non-`part_of` Task link affects packing affinity;
   - `placements[parentId]` is still determined only by confirmed `part_of`.

4. **two hierarchy trees with a cross-link**
   - they are one visual packing component;
   - still two structural roots/trees;
   - cross-link does not rewrite parentage.

5. **disconnected hierarchy trees**
   - remain distinct globally packed visual components.

6. **proposed part_of**
   - still does not alter geography until confirmed.

7. **Flow control**
   - distant Flow and Task<->Flow evidence do not affect Task packing membership or Task geography.

8. **determinism**
   - reversed node/edge input order produces identical presentation positions.

9. **ongoing circle clearance**
   - mixed hierarchy+daisy layout respects 144x144 Direction presentation.

10. **screen/controller integration**
    - after G3A-R1 fresh refresh, the final screen hierarchy projection cannot re-separate the daisy into distant shelf components.

Use comparative/bounded assertions rather than tuning to one accidental pixel arrangement.

## Checks

Run at minimum:

- `client/test/graph/task_map_hierarchy_test.dart`;
- `client/test/graph/graph_workspace_controller_test.dart`;
- G3A semantic-window tests;
- G1R;
- map relation;
- proposed relation;
- hybrid/focus LOD;
- Graph workspace/screen focused coverage.

Run Flutter analyze on touched client files.
Run `git diff --check`.
Run `flutter build linux --debug`.

The three documented detail-route text-finder failures are not authorization for unrelated fixes.

## Human bundle

Because this is client-only, build a Linux debug bundle from the exact implementation checkout and report its absolute path.

Do NOT install over the user's client.
Do NOT change saved API URL, preferences, secure storage, or token.
Startup-only smoke is allowed; no product interaction.

## Explicitly forbidden

Do NOT:

- change relation persistence or semantics;
- infer/convert `related_to` into `part_of`;
- mutate production data;
- deploy backend;
- move `origin/production`;
- add migrations;
- implement ontology prompt change;
- implement `Скрыть связи`;
- implement G3B pan/lens loading;
- start S3 or H2D;
- fix unrelated test failures.

## Completion

On completion:

1. update `PROJECT_STATE.md` with:
   - exact hierarchy projection root cause;
   - new structural-vs-visual connectivity rule;
   - algorithm summary;
   - test/analyze/build results;
   - implementation SHA;
   - exact Linux bundle path;
2. return `CURRENT_TASK.md` to HOLD;
3. push implementation/HOLD commits to `main`;
4. do not deploy;
5. STOP.

Final report must state:

- confirmed cause;
- definition of structural tree vs visual packing component;
- how hierarchy-to-free and hierarchy-to-hierarchy cross-links are packed;
- proof cross-links do not become parentage;
- delete/add symmetry result;
- relevant tests/analyze/build;
- backend product code changed? (expected NO);
- implementation SHA;
- HOLD/main SHA;
- absolute human bundle path.

Then STOP. Do not start the ontology/prompt corrective yourself.
