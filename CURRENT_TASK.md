# CURRENT_TASK

ACTIVE

## REL1D-HG5B — shared semantic windows for Task and People projections

### Context

HG5A read-only production audit is Architect-accepted.

Production facts:

- canonical Task semantic windows: 2;
- active Tasks across them: 34 unique;
- active People: 17;
- complete unanchored People: 6;
- complete single-window anchored People: 11;
- multi-window People: 0;
- incomplete anchors: 0;
- unmapped anchors: 0;
- only 3/11 single-window anchored People currently sit on the independently paged People page matching their Task window; 8/11 do not.

This confirms the current HG4C independent People pagination violates the accepted product model:

**Tasks and People are different projections of one canonical Task-world map.**

### Accepted architecture

1. Task semantic windows are the sole canonical overview windows.

2. In unrooted overview:
   - Task `window_index=N` means canonical semantic Task area N;
   - People `window_index=N` means the People projection of that exact same semantic Task area N.

3. People overview must no longer create independent salience/title pages.

4. A Person with at least one qualifying Task anchor appears in every semantic Task window containing at least one of that Person's anchors.

This is projection membership of the same Person object/id, not duplicate persistence.

Do **not** invent a home-window.

5. A complete Person with zero qualifying Task anchors is a global unanchored layer:
   - it appears in every People semantic-window overview;
   - it remains on the existing unanchored shelf;
   - it is not assigned an arbitrary Task window.

6. Person position remains in the one global coordinate system:
   - use the existing full complete `landscape_task_ids`;
   - use canonical persisted Task centers;
   - do not recompute a per-window centroid;
   - the same Person must have the same world position in every window where it is rendered.

7. Search and rooted Person views remain independent of overview-window membership and continue to work outside the current semantic window.

### Goal

Replace independent HG4C People page membership with canonical Task semantic-window projection while preserving complete Person reachability, bounded behavior, current Person interaction features, and one shared unrooted overview window index across Task/People modes.

No schema/Alembic change.

### A. Backend People semantic-window overview

1. Keep `GET /graph/people-workspace` API shape compatible.

For unrooted/no-search overview only, reinterpret `window_index` as the canonical Task semantic window index.

2. Reuse `GraphWorkspaceService` current semantic overview contract. Do not duplicate Task constellation/window-packing rules inside Person code.

For requested People overview window N:

- obtain the canonical Task semantic workspace/window N from `GraphWorkspaceService`;
- use only Task nodes in that canonical window as the selected semantic Task membership;
- People response `window_index`, `window_count`, `has_previous_window`, `has_next_window` must equal the canonical Task semantic workspace metadata.

3. Qualifying Person Task anchors remain exactly current landscape anchors:

- edge direction Task → Person;
- edge type in canonical `TASK_ACTOR_ROLES`;
- edge state confirmed;
- Task belongs to current user;
- Task active/nonhidden/nonrejected;
- Task non-terminal under existing read semantics.

Do not use generic `related_to`, `references`, `depends_on`, `part_of` Person relations as People landscape anchors.

4. Anchored People membership:

A current active Person is visible in semantic window N iff at least one qualifying Task actor anchor belongs to Task semantic window N.

5. Multi-window future behavior:

If one Person has qualifying anchors in multiple semantic Task windows, the same Person id is returned in each relevant window.

Do not copy/create the Person.

Do not select one home window.

6. Global unanchored People:

A current active Person with zero qualifying Task actor anchors is visible in **every** People semantic-window overview.

These People continue to be positioned by the existing unanchored shelf policy.

7. Do not require every active Person to appear exactly once across People windows anymore.

Replace that old HG4C partition invariant with coverage semantics:

- every active Person must appear in at least one People overview window;
- an anchored Person appears exactly in the set of semantic Task windows touched by its qualifying anchors;
- an unanchored Person appears in every semantic Task window.

8. If there are no overview-eligible Tasks, canonical Task overview still has its existing single empty semantic window. People window 0 must then contain all active People as global unanchored People.

9. Ordering inside one People semantic window may continue to use deterministic salience/title/id ordering, but salience must not determine window membership.

10. `seed_limit` must no longer slice an unrooted People overview semantic window.

Keep it for search/backward API compatibility if needed, but one semantic window must never be split into arbitrary Person pages because of `seed_limit`.

11. Completeness is more important than silent truncation.

Before materializing a semantic People window, enforce a deterministic hard emergency ceiling using the existing graph completeness ceiling (`MAX_COMPLETE_WINDOW_NODES`, currently 500) or one explicit equivalent constant with the same fail-closed intent.

If the complete People projection for one semantic window exceeds that ceiling:

- return a clear `ValidationError`;
- do not silently truncate/split the semantic window.

12. Keep database work bounded:

- derive relevant anchored People with SQL over the bounded selected Task ids;
- derive unanchored People with SQL `NOT EXISTS`/equivalent over qualifying actor anchors;
- do not load all communications/messages;
- do not call provider/model services;
- do not add an unbounded Python scan of the full graph.

13. Existing `landscape_task_ids`, landscape context, Person roles, communication counts, promotion candidates, rooted truth, identity candidates, etc. remain as currently defined for the People returned.

Do not change identity/email candidate depth in this task.

### B. Incomplete/unmapped safety

14. Do not invent geography for incomplete/unmapped Person anchors.

The current production audit has zero such People.

For this task:

- preserve existing `landscape_task_ids_complete` truth;
- if a Person selected for a semantic window cannot be safely projected because its complete anchor geography is unavailable, fail closed for that semantic overview rather than silently place it in an arbitrary semantic Task window;
- do not relabel such a Person as unanchored.

Focused tests must cover this fail-closed behavior.

### C. Client shared semantic window

15. Replace independent unrooted Task/People overview window memory with one shared semantic-window memory.

Current separate concepts:

- `_unrootedTasksWindow`
- `_unrootedPeopleWindow`

must no longer allow Task area 2 and People page 1 to coexist as independent states.

Use one shared unrooted semantic window index.

16. Mode switching contract:

When unrooted in semantic window N:

- switch Tasks → People: request People `window_index=N`;
- switch People → Tasks: request Tasks `window_index=N`;
- remain in the same world area;
- do not reset to window 0 unless N is genuinely out of range after an authoritative topology change.

17. Rooted/search flows must not overwrite the remembered shared unrooted semantic window.

Returning from rooted/search to overview should restore the latest valid shared semantic window, subject to existing OOR fallback.

18. OOR behavior remains fail-safe:

If an authoritative topology change makes remembered semantic window N invalid:

- retry/fallback to semantic window 0 using existing bounded OOR behavior;
- update the shared remembered index to the authoritative result.

19. People UI wording must reflect semantic areas, not independent pages.

Replace wording such as:

`Люди · страница N из M`

with:

`Люди · область N из M`

Use area-oriented previous/next tooltips.

Tasks keep existing `Область N из M` wording.

20. Do not change rooted Person interaction, rename, Task actor mutations, role sections, promotion flow, generic relation handling, or search behavior.

### D. Global geometry invariants

21. Do not modify persisted Task coordinates or task-layout algorithm.

22. Do not create Person coordinates in storage.

23. People projection must continue to use `projectPeopleLandscapeOverview` / existing canonical Task-center world semantics.

24. A multi-window Person fixture must produce the same world position in every window because the full anchor set is used.

25. Unanchored People shelf positions must remain stable across semantic-window mode/page changes for the same canonical Task world.

### Explicitly out of scope

Do NOT:

- change Task constellation/window packing;
- change Task layout coordinates;
- add a home-window policy;
- create Person storage coordinates;
- change Task actor relation types/direction;
- change salience scoring;
- change Person identity candidate/email scan depth;
- attach/infer emails;
- change PersonRole semantics;
- add Person→Person ontology;
- change rename behavior;
- change generic PATCH/embedding behavior;
- deploy production;
- move production refs;
- add schema/Alembic changes;
- call providers/models;
- resume historical HG2 repair;
- modify role-import raster extraction.

### Expected backend scope

Likely:

- `backend/app/services/person_graph_workspace_service.py`;
- possibly one small reusable/read-only semantic-window helper in `graph_workspace_service.py` only if needed to avoid rule duplication;
- focused People workspace tests;
- API tests only if externally observable validation behavior changes.

Do not refactor Task topology algorithms.

### Expected client scope

Likely:

- `client/lib/graph/graph_workspace_controller.dart`;
- `client/lib/graph/graph_workspace_screen.dart`;
- `client/lib/graph/people_landscape.dart` only if needed for explicit safety/stability tests;
- focused `people_overview_window_test.dart`;
- `graph_semantic_window_test.dart`;
- existing People landscape tests.

### Required backend tests

At minimum prove:

1. People overview window_count/index/prev/next exactly match canonical Task semantic windows.
2. Single-window anchored Person appears only in the matching semantic window.
3. Two anchored People in different Task semantic windows separate correctly.
4. Multi-window Person appears in every matching semantic window with the same Person id.
5. Complete unanchored Person appears in every People semantic window.
6. Generic Person→Task relation does not create semantic-window membership.
7. Proposed/rejected actor edge does not create membership.
8. Terminal/rejected/hidden Task does not create an active landscape anchor.
9. Rejected/hidden Person is excluded.
10. With no overview-eligible Tasks, one People window exists and contains all active unanchored People.
11. Small `seed_limit` does not split/truncate a semantic People window.
12. Salience changes ordering only, not membership.
13. Semantic People projection above the hard completeness ceiling fails explicitly instead of truncating.
14. Incomplete/unmapped landscape geography fails closed and is not silently treated as unanchored.
15. Rooted People workspace behavior remains unchanged.
16. People search behavior remains unchanged and does not send/require semantic window index.
17. Existing Person rename/Task actor tests remain green.

### Required client tests

At minimum prove:

18. Task area N → switch to People → People requests/shows area N.
19. People area N → switch to Tasks → Tasks requests/shows area N.
20. Repeated mode switches preserve one shared semantic index, not independent remembered indices.
21. Rooted/search Person visit does not destroy the remembered shared overview area.
22. OOR on either mode falls back to area 0 and synchronizes shared memory.
23. People label is `Люди · область N из M`, not `страница`.
24. Unanchored Person may be present in multiple semantic-window responses and remains at the same global shelf position.
25. Multi-window Person may be present in multiple semantic-window responses and its global position is unchanged because the complete full anchor set is unchanged.
26. Selection clears when selected Person is absent from the next semantic area, as existing overview replacement semantics require.
27. HG4B immediate actor feedback, HG4E rename, and HG4C/HG5 navigation behavior remain green where still applicable.

Update/replace old tests that explicitly asserted independent Task and People overview window memory; that behavior is intentionally retired.

### Checks

Run the smallest focused backend and Flutter suites covering the above.

Also run:

- Ruff on touched Python/tests;
- Dart format for touched Dart;
- Dart analyze for touched Dart;
- `git diff --check`.

### Completion protocol

When implementation/checks are green:

1. update `PROJECT_STATE.md` with concise HG5B implementation/test facts;
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
