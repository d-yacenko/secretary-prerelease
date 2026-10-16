# CURRENT_TASK

ACTIVE

## REL1D-HG6B — global context palette and compact local gravity packing

### Context

REL1D-HG6A is technically accepted.

Implementation:
`82f47d2f0e53da1069709186df051f8d543c43c5`

Architect acceptance:
`496049e3da451b9cdcf390c4b3bb15fc9062a6d6`

Human verification on a fresh client confirms the direction is useful, but exposes two bounded visual defects:

1. People sharing one exact Task-anchor cluster are spread too loosely around the Task-derived center. The current family attractor radius / radial free-slot search creates a sparse cloud where the intended result is one compact pack with context micro-clusters inside it.

2. Related but distinct exact contexts inside one organization family are visually almost indistinguishable. The motivating example is:
   - SRE / DevOps context in Arenadata;
   - Training Center context in Arenadata.
   They correctly share the Arenadata family, but must render as clearly related **and visibly distinct** shades.

A further invariant is now explicit:

> Context color identity is global across the People map. The same normalized exact context must map to the same visual identity everywhere, independent of Person, Task cluster, semantic window, shelf position, input order, or current population.

Do not persist RGB/color assignments. Do not introduce embeddings/model calls for this corrective.

### Goal

Client-only tuning:

1. make exact-context visual identity globally deterministic and stable across the whole People experience;
2. keep related contexts in one family/base hue but make exact contexts visibly distinguishable;
3. make same-anchor People clusters substantially denser while preserving gravity-like context grouping;
4. preserve all HG5/HG6A topology, progressive authoring, mutation, and stale-response behavior.

No backend/schema/deploy work.

### A. Global deterministic context palette

1. The only source of context visual identity remains active non-empty `PersonRoleAssignment.context`.

Do not infer context from:

- Person title;
- email/domain;
- Task title;
- provider;
- message text;
- role title alone;
- cluster membership;
- Person id;
- LLM/model output.

2. Normalized exact context is global.

For any two People with the same normalized exact context, `personContextVisual(...)` must produce the same exact visual signature, and `contextCardColor(...)` must produce the same rendered color for the same `ColorScheme`, even if they are:

- in different Task-anchor clusters;
- in different semantic Task/People windows;
- one anchored and one unanchored;
- loaded in different input orders;
- rendered after different numbers of other People are present.

3. The mapping must survive process restart by being a pure deterministic function of normalized context/family keys. No session palette allocation and no "next available color" state.

4. No-context remains exactly the existing neutral/default behavior:

- no family/exact color is invented;
- compact card uses `ColorScheme.surface`.

5. Keep the conservative family concept.

The motivating pair must share one family:

- `SRE ГК Arenadata` / `SRE Arenadata`;
- `УЦ ГК Arenadata` / `УЦ группы компании Arenadata`.

These should resolve to the same Arenadata family after normalization.

Unrelated contexts such as `Южный Федеральный Университет` and `Рубитех` must not be folded into the Arenadata family.

6. Family controls the base hue / color neighborhood. Exact context controls a deterministic variation inside that family.

Do not make every exact context a completely unrelated random hue.

Preferred shape:

- stable family hash → base hue;
- stable exact-context hash → bounded signed hue offset plus bounded saturation/lightness variation;
- same exact context → identical variation;
- related exact contexts → visibly different but still obviously one family.

The exact numeric implementation is owned by Executor.

7. Increase exact-context separation enough to be perceptible.

For the motivating pair:

- `SRE Arenadata`;
- `УЦ группы компании Arenadata`;

the final rendered card colors must be visibly distinct in both light and dark themes.

Tests must assert a **minimum rendered-color separation**, not merely `colorA != colorB`. The implementation may use HSL component distance, RGB distance, relative-luminance/color-channel distance, or another small deterministic metric. Choose and document a sane threshold that fails the current HG6A near-identical result.

At the same time, the pair must still remain within the same family/base-hue neighborhood rather than becoming unrelated colors.

8. Multiple distinct active contexts remain conservative and deterministic.

Do not silently choose one context as primary truth. Preserve or improve the existing combined/multi-context signature behavior.

9. Keep context color as presentation only.

Do not:

- write color/family IDs to backend;
- add DB fields;
- add local persistent palette storage;
- add embeddings;
- call providers/models.

A future semantic-family resolver may be added later if string heuristics prove insufficient, but it is out of scope here.

### B. Compact gravity-like same-anchor packing

10. Preserve HG5 geography exactly.

Do not change:

- semantic Task windows;
- Task coordinates;
- Person Task-anchor sets;
- Task-derived Person cluster base centroid;
- canonical Task world bounds;
- shared camera;
- Person storage coordinates;
- inter-window membership.

11. Context remains only a local packing signal inside an already existing exact Task-anchor cluster.

Do not pull a Person from one Task-anchor cluster toward a similar-context Person in another Task-anchor cluster.

12. Replace/tune the current sparse local placement.

The current fixed family attractor radius (`220`) and radial slot step based primarily on card width create excessive whitespace.

Prefer a compact deterministic candidate-slot field around the unchanged Task-derived base, for example:

- rectangular/lattice/spiral candidate centers using both compact card width **and height** plus the normal intra-cluster gap;
- family/exact attractors influence which nearby slot each Person prefers;
- collision avoidance remains exact;
- local attraction is a scoring/ordering signal, not permission to expand the cloud arbitrarily.

No general force-physics engine, animation, iterative random simulation, or third-party layout package.

13. Desired visual structure:

- one same-anchor cluster reads first as **one dense pack around one Task center**;
- inside that pack, same exact context forms compact micro-clusters;
- related exact contexts in one family are nearby but separable;
- unrelated families/no-context may occupy other local portions of the same dense pack;
- cards never overlap.

14. Compactness is a hard regression criterion.

Add a representative fixture with **13 People sharing one exact Task-anchor set**, containing at least:

- 2 People in one Arenadata exact context;
- 4 People in another Arenadata exact context;
- several no-context People;
- at least one unrelated context.

For this fixture, after local packing and recentering but before any unrelated-cluster collision translation:

- no card overlap;
- centroid remains on the original Task-derived base within the existing small tolerance;
- the bounding rectangle must fit within a compact **4 × 4 card-cell envelope** using compact card dimensions plus normal intra-cluster gap, with only a tiny floating-point tolerance.

This test exists specifically to prevent a return to the visually sparse HG6A cloud.

15. Stability remains mandatory:

- identical input → identical positions;
- reversed/shuffled input → identical positions;
- no frame-to-frame jitter;
- changing one Person's context may rearrange only its same-anchor local cluster;
- unrelated anchor clusters retain positions unless the pre-existing inter-cluster collision separator must move them.

16. Existing inter-cluster collision separation remains the final step.

Local context packing must be centered on the canonical Task-derived base first. Only then may the existing cluster-vs-cluster collision avoidance translate the whole packed cluster.

17. Unanchored shelf semantics stay unchanged.

All unanchored People remain on the shelf. Preserve existing context-aware shelf sub-grouping unless a very small adjustment is required for shared helper compatibility. Do not redesign shelf geography in HG6B.

### C. Preserve HG6A authoring behavior

18. Do not modify progressive Person hydration semantics except for unavoidable refactors that are behavior-neutral.

Keep green:

- immediate overview-summary opening;
- background rooted hydration;
- loading placeholders instead of false empty truth;
- summary retained on hydration failure;
- retry;
- A→B stale response rejection;
- rename stale safety;
- Task actor generation/reconciliation;
- role-specific stale protection.

19. Role/context mutation fast path remains unchanged:

- authoritative returned assignment patches detail immediately;
- overview Person patches immediately;
- no People workspace refresh solely for role mutation.

A context mutation must naturally repaint the global deterministic color and recompute only the affected local layout through existing controller repaint behavior.

### Required tests

At minimum prove:

1. same normalized exact context → same visual signature across different Person ids.
2. same exact context → same rendered color in the same theme across different Task-anchor clusters.
3. same exact context → same rendered color when one Person is unanchored and another is anchored.
4. result is independent of input order and unrelated population.
5. no-context → exact existing default surface.
6. Arenadata SRE and Arenadata Training Center share one family.
7. their rendered colors have an explicit minimum perceptual/numeric separation in **light theme**.
8. same minimum separation in **dark theme**.
9. both remain in one family/base-hue neighborhood.
10. Rubitech and Southern Federal University are not folded into Arenadata family.
11. multiple-context signature remains deterministic and order-independent.
12. 13-Person same-anchor mixed-context fixture fits inside the required 4×4 compact envelope.
13. same fixture has no overlaps.
14. same fixture centroid remains at Task-derived base.
15. same fixture is identical under reversed/shuffled Person input.
16. same exact contexts form contiguous/compact micro-clusters inside that envelope.
17. related Arenadata exact contexts are locally nearer to each other than an unrelated family where the compact slot geometry permits.
18. changing one context does not move an unrelated Task-anchor cluster.
19. existing unanchored shelf test remains green.
20. existing card selection/conflict/bookmark visual tests remain green.
21. existing `person_authoring_test.dart`, `person_roles_section_test.dart`, `person_rename_test.dart`, and `person_task_bridge_test.dart` remain green.
22. existing shared semantic-window / People-landscape regression suites remain green.

### Expected scope

Prefer only:

- `client/lib/graph/person_context_visual.dart`;
- `client/lib/graph/people_landscape.dart`;
- focused context/landscape tests;
- screen test only if needed for rendered-color assertion.

Avoid touching controller/authoring code unless a test requires a behavior-neutral compatibility edit.

### Checks

Run focused Flutter suites for all touched behavior, including at least:

- `person_context_packing_test.dart`;
- `people_landscape_overview_test.dart`;
- `people_landscape_screen_test.dart`;
- `person_authoring_test.dart`;
- `person_roles_section_test.dart`;
- `person_rename_test.dart`;
- `person_task_bridge_test.dart`;
- `people_overview_window_test.dart`;
- `graph_semantic_window_test.dart`.

Also run:

- `dart format` on touched Dart;
- `dart analyze` on touched Dart;
- `git diff --check`.

### Explicitly out of scope

Do NOT:

- add embeddings/vector search/OpenSearch;
- persist context colors or palette assignments;
- add backend/schema/Alembic changes;
- deploy production;
- move production refs;
- alter identity-candidate/email discovery;
- optimize rooted backend evidence scans;
- change Task semantic topology or Task coordinates;
- add Person coordinates to storage;
- change Task actor ontology;
- change PersonRole storage semantics;
- add Person→Person social relations;
- modify Agent/harness/tools;
- call providers/models;
- resume historical repair;
- modify role-import image extraction.

### Completion protocol

When implementation/checks are green:

1. update `PROJECT_STATE.md` with concise HG6B implementation/test facts;
2. replace this file with `HOLD`, recording implementation SHA and exact checks;
3. commit + push canonical `main`;
4. STOP.

Do not deploy and do not start the next phase automatically.

Production remains:
`0031f531d1215970093bea7add44fcd2259ec71b`

Alembic remains:
`0054 / 0054`

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
