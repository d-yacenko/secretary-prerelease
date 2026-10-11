# CURRENT_TASK

ACTIVE

## REL1D-HG5B.1 — bound shared People semantic projection without changing topology semantics

### Context

HG5B implementation `64f72a19cbf549022f99efd0b5fe8c482e0fe3e5` is directionally correct and keeps the intended one-map/different-projections product model.

Accepted HG5B semantics that MUST remain unchanged:

- Task semantic windows are the sole canonical overview windows;
- People `window_index=N` is the People projection of Task semantic area N;
- qualifying anchors remain confirmed active non-terminal Task → Person edges in canonical `TASK_ACTOR_ROLES`;
- anchored Person appears in every semantic window touched by its qualifying anchors;
- complete unanchored Person appears in every People semantic window on the global shelf;
- no home-window policy;
- same Person id across multiple relevant windows;
- search/rooted People are independent of overview membership;
- client uses one shared unrooted semantic window index;
- People UI says `Люди · область N из M`;
- global Person geometry remains derived from full complete anchor set and canonical Task centers.

Architect review found backend boundedness violations:

1. `PersonGraphWorkspaceService._overview()` obtains the requested Task window, then calls `GraphWorkspaceService.get_workspace()` again for every other Task window solely to rebuild a global Task universe.

2. `_require_projectable_anchor_geography()` calls `_qualifying_anchor_pairs()`, materializing every active qualifying Person↔Task anchor pair into Python.

3. `_people_for_semantic_window()` materializes the complete People result before `MAX_COMPLETE_WINDOW_NODES` is checked.

These violate the explicit HG5B boundedness / fail-before-materialization contract.

### Goal

Keep HG5B behavior exactly the same while making unrooted People semantic-window evaluation bounded and single-snapshot.

Prefer a backend-only corrective.

No schema/Alembic change.

### A. Canonical Task semantic snapshot

1. Add/reuse one small read-only helper in `GraphWorkspaceService` that computes canonical semantic overview packing **once** and can provide, from that same calculation:

- requested semantic window `GraphWorkspaceResult` or equivalent authoritative metadata/nodes;
- canonical semantic Task membership needed to determine whether a qualifying anchor belongs to the Task semantic overview universe and/or which window contains it.

The exact helper shape is implementation-owned, but:

- do not duplicate constellation/window-packing rules in Person code;
- do not call `get_workspace(window_index=...)` once per semantic window;
- do not change Task semantic packing/order/results;
- one People overview request must not recompute the entire Task semantic packing N times for N windows.

2. Task ids used for semantic membership must include only Task objects from canonical semantic Task windows, not priority non-Task flow nodes.

3. Existing `GET /graph/workspace` behavior must remain unchanged.

### B. Bounded People membership

4. Preserve current SQL membership semantics:

A Person is visible in requested semantic window iff:

- it has at least one qualifying anchor Task in the selected semantic Task-id set; OR
- it has zero qualifying anchors globally and is therefore complete unanchored.

Do not change generic/proposed/rejected/terminal relation behavior.

5. Do not materialize an unbounded complete People window before enforcing the emergency ceiling.

Before loading the full visible Person objects:

- use a SQL `COUNT`, `LIMIT MAX_COMPLETE_WINDOW_NODES + 1`, or equivalent bounded DB operation;
- if matching People exceed `MAX_COMPLETE_WINDOW_NODES`, raise the same explicit completeness `ValidationError`;
- only materialize the full result when the count is within the ceiling.

6. No Python list of all active Person↔Task anchor pairs is allowed.

Remove/replace the current `_qualifying_anchor_pairs()` full materialization path.

7. Incomplete/unmapped anchor safety must remain fail-closed without full-pair materialization.

Allowed approaches include bounded SQL aggregate/existence checks such as:

- `GROUP BY person_id HAVING COUNT(DISTINCT qualifying_task_id) > PEOPLE_LANDSCAPE_TASK_ANCHOR_CAP LIMIT 1`;
- `EXISTS` for qualifying anchor Tasks outside canonical semantic Task membership;
- selected-Person bounded/capped anchor reads.

The implementation may fail the semantic People overview globally when an active Person has qualifying geography that cannot be represented, as HG5B currently does, provided the check is SQL-bounded and does not emit identity data.

Do not silently reclassify incomplete/unmapped People as unanchored.

8. Do not perform communication/provider/model scans to determine topology.

9. Salience may order the bounded visible People set after membership is established. It must not determine membership.

### C. Preserve HG5B client behavior

10. Do not redesign the client shared-window state.

The following already-implemented behavior must stay green:

- one `_unrootedSemanticWindow`;
- Tasks N → People N;
- People N → Tasks N;
- rooted Person visit restores remembered N;
- OOR fallback synchronizes to authoritative area 0;
- People label/tooltips use semantic-area wording;
- selection clears if absent from next area;
- rename and Task actor foreground/reconciliation behavior remains intact.

Only touch client code if a focused regression test proves a necessary issue. Otherwise leave it unchanged.

### D. Required tests

Backend tests must at minimum prove:

1. Existing HG5B membership fixture still passes:
   - left-only Person;
   - right-only Person;
   - multi-window Person;
   - global unanchored People;
   - generic/proposed/terminal non-qualifying links;
   - rejected/deleted People exclusion.

2. Task semantic packing is computed once per People overview request, not once per semantic window.
   - Use an explicit spy/counter around the new reusable helper or the underlying packing call.
   - A fixture with 3+ semantic windows must still report exactly one canonical semantic packing calculation for one People overview request.

3. The old full-pair Python path is absent.
   - No helper may return/materialize all active Person↔Task anchor pairs merely to validate geography.

4. Completeness ceiling is enforced before full Person materialization.
   - Construct/patch a fixture with ceiling K and K+1 matching People.
   - prove the request returns 422 without a full unbounded Person materialization path.
   - a bounded `LIMIT K+1` materialization is acceptable.

5. A semantic window with <= ceiling still returns every matching Person; `seed_limit=1` does not split it.

6. Multi-window Person keeps the same full `landscape_task_ids` in each relevant window.

7. SQL-bounded incomplete geography detection still returns 422.

8. SQL-bounded unmapped geography detection still returns 422.

9. A Person with only non-qualifying generic/proposed/terminal Task links is still treated as unanchored exactly as HG5B specified.

10. Existing rooted/search Person workspace tests remain unchanged and green.

11. Existing Person rename and Task actor tests remain green.

Client regression tests:

12. Run the existing focused HG5B/HG4 client suites unchanged unless backend response plumbing requires a narrow fixture adjustment:
   - `people_overview_window_test.dart`
   - `graph_semantic_window_test.dart`
   - `people_landscape_overview_test.dart`
   - `person_rename_test.dart`
   - `person_task_bridge_test.dart`

### Checks

Run:

- focused backend pytest for Person graph workspace;
- focused Flutter suites above;
- Ruff on touched Python/tests;
- Dart format/analyze only if Dart touched;
- `git diff --check`.

### Explicitly out of scope

Do NOT:

- change Task semantic packing;
- change Task layout coordinates;
- change People membership policy;
- add/remove global unanchored shelf behavior;
- add a home-window policy;
- change client shared semantic-window UX;
- change salience scoring;
- change Task actor semantics/direction/types;
- change Person identity candidate/email scan depth;
- change PersonRole semantics;
- change rename;
- change generic PATCH/embedding;
- deploy production;
- move production refs;
- add schema/Alembic changes;
- call providers/models;
- resume historical HG2 repair;
- modify role-import image extraction.

### Completion protocol

When implementation/checks are green:

1. update `PROJECT_STATE.md` with concise HG5B.1 implementation/test facts;
2. replace this file with `HOLD`, recording implementation SHA and exact checks;
3. commit + push canonical `main`;
4. STOP.

Do not deploy production or start identity-candidate/email work automatically.

Production remains:
`50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

Alembic remains:
`0054 / 0054`

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
