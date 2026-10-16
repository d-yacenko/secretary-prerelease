# CURRENT_TASK

ACTIVE

## REL1D-HG6D — single-flight Person hydration and visible role API failures

### Context

REL1D-HG6C diagnostic is Architect-accepted.

Accepted diagnosis:
`CLIENT_CONCURRENCY_SUPPORTED`

Diagnostic ledger:
`72e9f2074f51ef797433a67c6f971030b24e0d9d`

Architect acceptance:
`6a031452d6d1fa2b13863adbae6fea99869e5382`

Production remains:
`0031f531d1215970093bea7add44fcd2259ec71b`

Alembic remains:
`0054 / 0054`

Established facts:

- rapid selection of 8 People starts 8 simultaneous unresolved rooted `GET /graph/people-workspace` requests;
- stale-response tokens reject old responses but do not stop the HTTP/DB work;
- production logs from the incident window contain repeated QueuePool / SQLAlchemy TimeoutError failures on People/role route families;
- role-cap/data state does not explain the incident;
- role-term search failures are currently hidden;
- role assign/retract failures currently collapse to `Не удалось обновить роль`.

### Goal

Client-only corrective:

1. bound background rooted Person hydration to **one active request plus at most one replaceable latest pending target**;
2. keep the HG6A immediate-summary UX;
3. ensure rapid traversal never creates an unbounded queue of rooted People GETs;
4. expose useful sanitized role API failures;
5. preserve an explicit typed-role fallback when role-term search fails;
6. preserve all HG4/HG5/HG6A/HG6B stale-response, topology, role, and layout contracts.

No backend/schema/deploy work.

### A. Latest-target single-flight background hydration

1. Background detail hydration initiated from overview selection must be single-flight.

At any moment, this surface may have:

- at most one active rooted People GET for background Person hydration;
- at most one pending Person target.

Do not enqueue every intermediate Person.

2. Rapid A → B → C selection while A hydration is active:

- A request continues if it cannot be cancelled safely;
- B does **not** start a rooted GET;
- C replaces B as the only pending target;
- C overview summary is shown immediately;
- A response must not install into C;
- when A finishes, start exactly one fresh hydration for C if C is still the selected Person and authoritative rooted truth is not already available.

3. The pending target is **latest-wins**, not FIFO.

Selecting D, E, F while one request is active must keep only F pending.

4. Capture generation state when a pending target actually starts its HTTP request, not when it is first queued.

This ensures rename/role/task mutations that happen while waiting are compared against current generation state.

5. If the pending/current Person becomes authoritative through existing controller-rooted truth before its queued hydration starts:

- adopt/reuse that truth;
- do not start a duplicate rooted GET.

6. If the selected Person changes back to the currently active hydration target, do not start a duplicate request.

When that active response completes, it may install only if all existing freshness conditions still hold for that selected Person.

7. Stale active success/failure must not surface detail content or hydration error on the newer selected Person.

8. The queue must always drain.

After an active request completes or fails:

- clear active state in a `finally`-equivalent path;
- inspect the single latest pending target;
- start it only if still needed/current;
- otherwise leave zero hydration requests active/pending.

No stuck "active" bit after exceptions.

9. Retry from `Не удалось загрузить подробности · Повторить` uses the same coordinator.

Retry must not bypass the single-flight bound.

10. A direct/rooted entry with no usable overview summary may still show the full-card spinner, but must also respect the same single-flight coordinator.

11. Do not redesign/cancel the separate Task-actor reconciliation machinery in this task.

It may remain its own existing single-flight path.

However:

- do not reuse `_personTaskGeneration` for hydration scheduling;
- do not weaken its current max-one reconciliation invariant;
- do not create a new unbounded interaction between hydration and reconciliation.

### B. Preserve progressive Person UX

12. Selecting a Person with an overview `PersonPresentation` remains immediate:

- title visible immediately;
- rename visible immediately;
- roles/context visible immediately;
- safe overview metrics visible;
- root-only empty sections show loading placeholders;
- no full-card blocking spinner merely because hydration is queued behind another Person.

13. If the current selected Person is pending behind another active hydration, its summary remains usable throughout the wait.

14. Hydration failure for the current selected Person preserves the summary and shows the existing recoverable detail error/retry.

15. Existing generation protections remain independent:

- presentation/rename generation;
- role generation;
- Task actor generation/reconciliation.

A newer local role/context mutation must still survive an older rooted hydration response.

### C. Role-term search error visibility and fallback

16. `GET /graph/person-role-terms` failures must no longer be silent.

On `ApiException`:

- show a visible inline error in the add-role dialog using the sanitized API message;
- clear stale suggestions;
- mark that search attempt settled as failed;
- do not pretend the search succeeded.

17. Preserve an explicit typed-role fallback after a failed search.

If the user has non-empty role text and the search request failed:

- allow submitting the typed role directly through the existing assign endpoint;
- use wording that does **not** falsely claim a new vocabulary term will definitely be created, e.g. `Использовать роль «…»`;
- backend remains authoritative about whether the term is reused or created.

18. While a role-term search is merely pending, keep the existing safety behavior:

- do not show stale suggestions;
- do not prematurely show the fallback action until that search resolves or fails.

19. On the next successful search:

- clear the prior search error;
- restore normal suggestions;
- preserve exact-match behavior;
- hide the fallback when an exact existing role term is found according to current semantics.

20. Generic/non-ApiException search failure may show a safe generic text such as `Не удалось загрузить роли`.

Do not expose stack traces, raw response bodies, tokens, or internal SQL.

### D. Role assign/retract error visibility

21. Assign failure:

- keep the add-role dialog open;
- preserve typed role/context;
- leave existing role list unchanged;
- on `ApiException`, show the sanitized API message, preferably with a short user-facing prefix;
- allow retry.

22. Retract failure:

- keep the role visible;
- show the sanitized API message inline in the role section;
- allow retry;
- no optimistic removal before authoritative success.

23. Successful assign/retract retains the HG6A fast path:

- apply returned authoritative `PersonRoleAssignment` immediately;
- update detail immediately;
- update overview immediately;
- no People workspace refresh solely for the role mutation.

24. Do not add automatic retry/backoff for role mutation in this task.

The user should see the failure rather than creating duplicate writes.

### E. Required concurrency tests

Add a committed deterministic widget/harness regression test.

1. Eight distinct overview People with individually gated rooted responses.
2. Rapidly select all eight before releasing the first active gate.
3. Assert before release:
   - rooted GETs started = 1;
   - peak simultaneous unresolved hydration GETs = 1;
   - selected Person is person 8;
   - person 8 summary is already usable;
   - intermediate People 2–7 have not started rooted GETs.
4. Release Person 1.
5. Assert exactly one new rooted GET starts for Person 8.
6. Assert People 2–7 are never requested.
7. Release Person 8.
8. Assert:
   - in-flight hydration = 0;
   - no pending target;
   - Person 8 heavy truth installs;
   - Person 1 stale truth never installs.

Also prove:

9. A→B→A while A is the active request does not start a duplicate A request.
10. Stale A failure while C is current does not show C a hydration error.
11. Retry after current hydration failure respects single-flight and starts exactly one request.
12. If pending target is satisfied by existing controller-rooted truth before dispatch, no duplicate GET is made.

### F. Required role error tests

13. Role-term search HTTP 500 with API detail:
   - stale suggestions disappear;
   - inline error contains the sanitized API detail;
   - after failure and non-empty typed role, explicit `Использовать роль …` action is visible.
14. Search pending:
   - fallback action is hidden.
15. Subsequent successful search:
   - error clears;
   - suggestions return;
   - exact-match semantics remain.
16. Assign HTTP failure:
   - previous roles remain;
   - dialog stays open;
   - typed role/context remain;
   - API detail is visible;
   - no local role patch occurs.
17. Retract HTTP failure:
   - role remains visible;
   - API detail is visible.
18. Successful retry still patches locally without People workspace refresh.

### G. Regression suites

Keep green at minimum:

- `person_authoring_test.dart`;
- `person_roles_section_test.dart`;
- `person_rename_test.dart`;
- `person_task_bridge_test.dart`;
- `person_context_packing_test.dart`;
- `people_landscape_overview_test.dart`;
- `people_landscape_screen_test.dart`;
- `people_overview_window_test.dart`;
- `graph_semantic_window_test.dart`.

### Expected scope

Prefer client-only changes in:

- `client/lib/graph/graph_workspace_screen.dart`;
- `client/lib/graph/person_roles_section.dart`;
- focused Flutter tests;
- possibly one tiny private helper/model for hydration target state.

Avoid touching `SecretaryApiClient` unless strictly needed for test observability. Do not change HTTP timeout/pool behavior.

### Checks

Run focused Flutter suites covering all above contracts.

Also run:

- `dart format` on touched Dart;
- `dart analyze` on touched Dart;
- `git diff --check`.

### Explicitly out of scope

Do NOT:

- tune SQLAlchemy pool size;
- change database pool timeout/max overflow;
- optimize backend rooted evidence scans yet;
- add cancellation plumbing to the HTTP client unless absolutely necessary (serialization is sufficient);
- add automatic role retries;
- change role cap;
- change role storage semantics;
- add backend/schema/Alembic changes;
- deploy production;
- move production refs;
- restart production;
- change identity-candidate/email discovery;
- add embeddings/OpenSearch/cache;
- change Task topology/coordinates;
- change context palette/packing;
- modify Agent/harness/tool contracts;
- call providers/models;
- resume historical repair;
- modify role-import extraction.

### Completion protocol

When implementation/checks are green:

1. update `PROJECT_STATE.md` with concise HG6D implementation/test facts;
2. replace this file with `HOLD`, recording implementation SHA and exact checks;
3. commit + push canonical `main`;
4. STOP.

Do not deploy and do not start backend optimization or another phase automatically.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
