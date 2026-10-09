# CURRENT_TASK

ACTIVE

## REL1D-HG4C — complete bounded People overview windowing

### Context

HG4A production audit and HG4B client corrective are Architect-accepted.

Production evidence:

- active People: 17;
- default People overview returned: 12;
- overview was truncated;
- 2 of 4 recently created People were outside the visible overview;
- this included the sole recent manual-like Person and one recent identity-backed Person;
- all 17 active People currently had positive salience.

Therefore the remaining defect is not specific to manual creation or zero salience. The People overview is bounded but has no user-reachable next window.

The Graph controller and generic graph workspace already have a window contract:

- `window_index`;
- `window_count`;
- `has_previous_window`;
- `has_next_window`;
- `loadNextOverviewWindow()`;
- `loadPreviousOverviewWindow()`.

People workspace currently does not expose/use that contract, and the screen shows the window controls only in Tasks mode.

### Goal

Make every active Person reachable from the unrooted People graph through deterministic bounded overview windows, reusing the existing graph window controller/UI contract.

Do not solve this by merely increasing the People seed limit.

### Product contract

1. Unrooted People overview is paged/windowed with page size = requested `seed_limit` (default 12, existing max 24).

2. The complete current ordering is:

   - first: the existing bounded salience-ranked Person prefix returned by `PersonSalienceService.rank()`, limited by its existing safeguards and ordered exactly as current People overview orders ranked People:
     `score desc, title casefold, person id`;
   - then: every remaining active/non-hidden/non-rejected Person not already in that ranked prefix, ordered by:
     `title casefold, person id`.

3. This task must NOT make salience scanning unbounded or increase `MAX_RANKED_PEOPLE`. The bounded ranked prefix remains bounded; completeness comes from paging the remaining active People.

4. No Person may appear in more than one overview window for the same read state.

5. Across all valid overview windows, the union must contain every active/non-hidden/non-rejected Person exactly once.

6. Window metadata for unrooted overview must be accurate:

   - `window_index` zero-based;
   - `window_count` at least 1;
   - `has_previous_window`;
   - `has_next_window`;
   - `truncated == true` whenever the current window is only part of a multi-window People overview;
   - empty People state returns window 0 of 1 with no previous/next and `truncated=false`.

7. An out-of-range unrooted People `window_index` must fail closed with HTTP 422 and an error message containing exactly the shared phrase:
   `window index is out of range`
   so the existing controller fallback contract can be reused.

8. Rooted Person workspace remains unwindowed. A nonzero `window_index` combined with `root_id` must be rejected with 422 rather than silently ignored.

9. People search remains a global bounded search independent of overview windows. A nonzero `window_index` combined with non-empty `q` must be rejected with 422 rather than silently changing search semantics.

10. The existing first People window must preserve current first-page ranking behavior.

### Backend/API requirements

11. Extend `PeopleWorkspaceResult` and `PeopleWorkspaceOut` with the existing graph-style fields:

   - `window_index`;
   - `window_count`;
   - `has_previous_window`;
   - `has_next_window`.

   Keep defaults appropriate for rooted/search results (0 / 1 / false / false).

12. `GET /graph/people-workspace` accepts `window_index: int >= 0` and forwards it to `PersonGraphWorkspaceService.get_workspace()`.

13. Catch the service `ValidationError` at the route and map it to HTTP 422, matching the generic graph route behavior.

14. Implement paging without loading the entire active Person table merely to slice it in Python.

   Preferred bounded shape:

   - obtain the existing bounded ranked prefix;
   - count total active People with SQL;
   - calculate the requested page range;
   - take the relevant slice of the bounded ranked prefix;
   - fill remaining page slots from SQL over active People excluding the ranked-prefix ids, ordered by lower(title), id, with explicit offset/limit.

15. Do not duplicate active-Person visibility predicates. Reuse the existing `_active_filters()` contract.

16. Promotion candidates/suppressions may continue to be attached to each unrooted overview window exactly as today. Do not redesign promotion pagination in this task.

17. Rooted People behavior, Person detail truth, landscape anchors/context, roles, identities, communication counts, and search behavior remain semantically unchanged.

### Client requirements

18. `SecretaryApiClient.getPeopleWorkspace` accepts an optional `windowIndex` and serializes `window_index` only when supplied.

19. `GraphWorkspaceController._fetchWorkspace` passes `window_index` for unrooted People overview loads.

   It must not pass an overview window index for rooted Person reads or search requests.

20. Preserve independent unrooted window positions per mode:

   - existing Tasks overview window;
   - People overview window.

   Switching Tasks → People → Tasks or People → Tasks → People should restore the last valid overview window for each mode instead of forcing People permanently to page 0.

21. Existing `loadOverviewWindow`, previous/next methods, refresh-current-window behavior, and out-of-range fallback should be reused rather than adding People-specific navigation methods.

22. Window controls become available for unrooted People mode whenever `windowCount > 1`.

23. Use People-specific human wording rather than calling People pages Task "areas". For example:

   - status: `Люди · страница 1 из 2`;
   - previous tooltip: `Предыдущие люди`;
   - next tooltip: `Следующие люди`.

   Existing Tasks wording remains unchanged.

24. When a People window changes:

   - replace the overview nodes with that window;
   - clear selection if the selected Person is not in the new window;
   - do not carry stale Person detail from the previous window;
   - keep mode = People and rootId = null.

25. Search must still find a Person outside the current overview window and may then re-root to that Person using the existing search flow.

26. Manual `Добавить человека` behavior stays unchanged: successful creation may re-root immediately to the created Person. This task only ensures that later return to overview can reach that Person through windows.

27. HG4B immediate Task-actor feedback and HG3.2.x stale-response protections must remain unchanged.

### Explicitly out of scope

Do NOT:

- increase `DEFAULT_SEED_LIMIT` as the solution;
- increase `MAX_RANKED_PEOPLE`;
- redesign salience scoring;
- make People overview unbounded;
- paginate rooted Person neighbors;
- paginate People search;
- change Person creation/promotion semantics;
- attach identities to manual People;
- change Person merge behavior;
- change Task actor semantics;
- add schema/Alembic migrations;
- deploy production;
- install/rebuild the user's client;
- call providers/models;
- modify role-import raster extraction;
- resume historical HG2 repair/backfill.

### Expected files

Likely relevant:

- `backend/app/services/person_graph_workspace_service.py`;
- `backend/app/api/routes/graph_workspace.py`;
- `backend/app/api/schemas.py`;
- `backend/tests/test_person_graph_workspace.py`;
- `client/lib/api/secretary_api_client.dart`;
- `client/lib/graph/graph_workspace_controller.dart`;
- `client/lib/graph/graph_workspace_screen.dart`;
- focused graph/People window tests.

Keep the implementation localized. Do not refactor unrelated graph pagination/layout.

### Required backend tests

At minimum prove:

1. 25 active People with `seed_limit=12` yield exactly 3 windows (12/12/1), correct previous/next flags, and no duplicates across windows.

2. The union of all three windows equals all 25 active People.

3. Rejected/deleted/hidden People are excluded from both total window count and page content.

4. The first window preserves current salience-first ordering.

5. A Person outside the ranked prefix appears in exactly one later page according to title/id ordering.

6. The implementation remains bounded: ranked prefix stays limited by existing `PersonSalienceService.rank()`; SQL remainder reads use page-sized limit/offset rather than materializing all remaining People.

7. Empty state returns window 0/1, no previous/next, not truncated.

8. Exact last valid window works; first out-of-range index returns 422 containing `window index is out of range`.

9. Nonzero `window_index` with `root_id` returns 422.

10. Nonzero `window_index` with search `q` returns 422.

11. Existing rooted/search/identity/promotion tests remain green.

### Required client tests

At minimum prove:

12. People overview request page 0 sends/accepts window metadata and displays no controls when only one page exists.

13. Multi-window People overview shows People-specific previous/next controls and `Люди · страница N из M`.

14. Tapping next sends `window_index=1`, replaces page-0 People with page-1 People, remains unrooted, and updates controls.

15. Tapping previous returns to page 0.

16. Selection/detail from page 0 is cleared when moving to a page that does not contain that Person.

17. A manual-like test Person placed only on page 2 becomes visible by navigating to page 2.

18. Tasks and People remember independent overview window indexes across mode switches.

19. Refresh while on People page 2 reloads page 2, not page 0.

20. If the current People page becomes out of range, existing shared fallback returns safely to page 0.

21. Global People search still finds a Person not present in the current overview page and existing search selection/re-root behavior works.

22. HG4B unrooted actor feedback focused tests and existing Task semantic-window tests remain green.

Run the smallest focused backend + Flutter suites covering these contracts.

Run:

- Ruff/appropriate Python checks for touched backend/tests;
- Dart formatting/analyzer checks for touched client files;
- `git diff --check`.

### Completion protocol

When implementation and checks are green:

1. update `PROJECT_STATE.md` with a concise factual HG4C implementation/test entry;
2. replace this file with `HOLD`, recording implementation SHA and exact checks;
3. commit + push to canonical `main`;
4. STOP.

Do not deploy production or start another phase.

Production remains:
`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic remains:
`0054 / 0054`

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
