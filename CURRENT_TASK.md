# CURRENT_TASK

ACTIVE

## REL1D-HG3.2 — instant Person task-role feedback with non-blocking reconciliation

### Context

Human recheck of accepted HG3.1 confirmed correct add/remove semantics, but visible Person task-role changes still take roughly 15–25 seconds.

Source diagnosis:

- the Task actor mutation endpoint itself returns the authoritative mutated edge;
- after that success, the client currently awaits `controller.refreshCurrentWorkspace()`;
- in People mode that performs a rooted `GET /graph/people-workspace?root_id=<person>`;
- the client then separately awaits `_loadRootedPerson(... preserveVisible: true)`, which performs the same rooted People-workspace request again;
- the first rooted People-workspace response already contains the root Person's full `task_involvement`.

Therefore visible CRUD feedback is incorrectly blocked on two sequential heavy People-workspace projections.

### Goal

After a successful Person↔Task actor mutation, make the Person card reflect the confirmed server result immediately, without waiting for People workspace refresh. Reconcile the heavier People graph/projection asynchronously and safely.

### Required behavior

1. The visible Person task-role mutation flow must have two phases:
   - **foreground mutation**: await only the actual add/remove/confirm/reject server mutation/decision request;
   - **background reconciliation**: refresh derived People workspace state without blocking the already-confirmed visible card update.

2. On successful foreground mutation, update the rooted Person task-involvement list from the authoritative server response:
   - `addTaskActor`: upsert exactly the returned edge using the selected Task/Direction metadata already available in the dialog;
   - `removeTaskActor`: if the returned edge is rejected, remove exactly that `edge_id`;
   - proposal confirm: update exactly that edge to the returned confirmed state;
   - proposal reject: remove exactly that rejected edge.
   Preserve all unrelated Person task-role rows.

3. Multiple Task actor edges for one Person remain supported. Multiple roles may also exist for the same Task. Matching must be by edge identity, not only by Task id.

4. The existing foreground busy cue `Обновляем участие в задачах` and disabled mutation controls must cover the foreground mutation request only. Once the server mutation response has been applied locally:
   - the visible row/card must already be correct;
   - foreground controls may become usable again;
   - a slow People-workspace refresh must not keep the CRUD action visually pending.

5. Do not perform two sequential rooted People-workspace loads for one settled mutation. Remove the current `refreshCurrentWorkspace() -> _loadRootedPerson()` double-fetch path.

6. A background reconciliation may use the existing rooted People workspace projection, but it must be versioned/coalesced:
   - a response started before a newer Person task-role mutation must never overwrite the newer local state;
   - if one reconciliation is already in flight and a newer mutation succeeds, ensure a final reconciliation is performed for the newest mutation generation;
   - do not start unbounded concurrent People-workspace refreshes.

7. When a background reconciliation completes for the latest generation, it may replace the rooted Person/task-involvement state with the authoritative workspace projection and refresh graph/landscape state.

8. If the foreground mutation request fails:
   - keep the previous task-role rows;
   - surface the existing recoverable mutation error;
   - do not pretend success.

9. If the foreground mutation succeeds but the later background reconciliation fails:
   - do NOT revert the successful local mutation;
   - do NOT show the foreground mutation as failed;
   - surface at most a non-blocking reconciliation warning equivalent to:
     `Изменение сохранено, обзор обновится позже`;
   - allow another mutation/retry.

10. Switching away from the Person, changing root/mode, or disposing the screen must prevent a late background response from mutating the wrong Person surface.

11. Where the mutated edge is represented in the current graph controller, reuse existing `upsertEdge` / `removeEdge` / relation-decision helpers as appropriate rather than waiting for a full graph reload merely to reflect that single edge.

### Explicitly out of scope

Do NOT:

- change Task actor backend semantics;
- change mutation/decision API response schemas unless client implementation proves strictly impossible without it;
- add schema/Alembic changes;
- introduce polling;
- introduce arbitrary fixed delays/debounces as the correctness mechanism;
- add new relation types;
- change Person→Person ontology;
- change PersonRole assignments;
- modify role-import image extraction;
- deploy/install anything;
- touch production data;
- resume historical HG2 repair/backfill.

Prefer a client-only implementation.

### Likely files

- `client/lib/graph/graph_workspace_screen.dart`;
- `client/lib/graph/graph_workspace_controller.dart` only if a small existing-state helper is needed;
- `client/lib/api/api_models.dart` only if a narrow immutable Person/task-involvement copy helper is useful;
- focused graph/person task bridge tests.

Do not refactor unrelated graph state.

### Required tests

At minimum add/update focused Flutter tests proving:

1. While the actual mutation HTTP response is delayed, the busy cue remains visible and no local success is shown prematurely.
2. Once a successful remove response arrives, that exact edge disappears immediately even when the subsequent People-workspace reconciliation is intentionally held/delayed.
3. Once a successful add response arrives, the new edge appears immediately while an unrelated existing edge remains visible, even when reconciliation is held/delayed.
4. Confirm/reject proposal actions apply their returned edge state immediately without waiting for reconciliation.
5. The foreground busy cue clears after the mutation response, not after delayed background reconciliation.
6. One settled mutation does not perform the previous pair of sequential rooted People-workspace GETs.
7. A background response from an older mutation generation cannot overwrite a newer successful local mutation.
8. If a newer mutation succeeds while reconciliation is in flight, a final reconciliation occurs for the newest generation without unbounded concurrent refreshes.
9. Foreground mutation failure preserves prior rows and surfaces a retryable error.
10. Background reconciliation failure preserves the successful local mutation and surfaces only a non-blocking sync warning.
11. Switching Person/root before a delayed reconciliation response prevents that response from changing the new Person surface.
12. Existing duplicate-title disambiguation from HG3.1 remains green.

Run the smallest focused Flutter suite covering these contracts plus the existing Person task bridge/disambiguation tests. Run formatting/analyzer checks appropriate for touched Dart files and `git diff --check`.

### Completion protocol

When implementation and required checks are green:

1. update `PROJECT_STATE.md` with a concise factual HG3.2 implementation/test entry;
2. replace this file with `HOLD`, recording implementation SHA and checks;
3. commit + push to canonical `main`;
4. STOP.

Do not begin the raster role-import extraction follow-up or any other phase.

Production/backend remains:
`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic remains:
`0054 / 0054`

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
