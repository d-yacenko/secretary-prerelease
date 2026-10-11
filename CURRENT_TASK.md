# CURRENT_TASK

ACTIVE

## REL1D-HG4E — reliable Person rename and canonical actor-relation presentation

### Context

Human acceptance on a rebuilt client against production `a9221699b4b725888213ff38e6673495a512042c` confirmed:

1. People paging/reachability works; the previously hidden manually-created Person is visible on the second People page.
2. Person rename still fails as a user-visible no-op.
3. The same canonical Task actor edge is rendered twice in Person detail:
   - correctly in specialized `Участие в задачах`;
   - again in generic `Связи`.

Source review:

- current rename uses generic `PATCH /objects/{id}`;
- that route depends on `_graph_service_with_embedding`;
- title changes trigger `refresh_object_embedding(...)`;
- the client rename flow does not catch `ApiException`;
- global search title matching uses live `objects.title` through FTS/trigram, so a Person-specific title mutation does not require embedding to make the new title lexically searchable/displayed;
- generic `_DirectRelationInventory` currently renders every direct edge and therefore duplicates the four canonical Task actor roles already represented by the specialized Person/Task surfaces.

### Goal

Make Person rename a reliable first-class Person mutation with no provider/model/embedding dependency, and make canonical Task actor roles appear only on their specialized UI surfaces rather than being duplicated in generic direct relations.

### A. Person-specific rename contract

1. Add a narrow Person-specific rename API under the People API namespace.

Preferred shape:

`PATCH /graph/people/{person_id}`

with a strict body containing only:

`{"title": "..."}`

and response `ObjectOut`.

2. The rename endpoint must:

- operate only on the current user's active/non-hidden/non-rejected Person;
- trim leading/trailing whitespace;
- reject blank title;
- preserve the existing Person title maximum of 200 characters;
- update only `Object.title`;
- flush/commit through the normal request transaction;
- return the updated Person object;
- not merge, alter identities, roles, routes, edges, provenance, state, or salience.

3. The rename path must have **no dependency on**:

- `get_user_embedding_service`;
- provider credentials;
- model/provider/network calls;
- embedding refresh.

A missing/misconfigured embedding provider must not block Person rename.

4. Do not change the behavior of generic `PATCH /objects/{id}` in this task. This task is not a general embedding/indexing redesign.

5. Place the mutation in the narrow existing Person service layer. Reuse the canonical active-Person ownership/visibility rules; do not invent a second Person validity rule.

6. No schema/Alembic change.

### B. Client rename UX

7. Add a dedicated API-client method for the Person-specific rename endpoint. Person rename must stop using generic `patchObject`.

8. Rename dialog must be recoverable and deterministic:

- trim input before submit;
- blank title cannot submit;
- while request is in flight, disable conflicting submit/cancel/double-submit actions as appropriate;
- do not close the dialog before the server confirms success;
- on API/network failure, keep the dialog/input available and show a visible error;
- do not silently swallow the failure.

9. On successful server response:

- close the dialog;
- immediately update the visible Person title from the returned authoritative object;
- update the graph node title;
- update the current Person presentation/title state so reselecting the same Person does not restore the old title;
- do not block visible success on a heavy People workspace refresh.

10. A later authoritative People refresh/rooted read may reconcile the rest of Person presentation, but no older response may revert a newer successful rename.

Reuse the existing stale-response/request-generation discipline where needed; do not create an unrelated state system.

11. Rename must work for:

- Person selected from unrooted People overview;
- rooted/centered Person.

It must not re-root an unrooted overview merely to rename.

12. After success, People workspace/search responses naturally carry the new persisted title. Do not add client-side aliases or text substitutions.

### C. Canonical actor relation presentation

13. The four Task actor edge types remain exactly:

- `requested_by`
- `delegated_to`
- `waiting_on`
- `involves`

Their storage direction remains Task → Person.

14. These actor edges are already represented by specialized surfaces:

- Person: `Участие в задачах`;
- Task/Direction: Task profile actor section.

Therefore generic `_DirectRelationInventory` must not render Task actor edges.

15. Apply the exclusion consistently whether the edge came from:

- current controller/map edges;
- off-canvas/direct-neighbor response.

Do not merely hide one source.

16. Do not duplicate the actor-type set in multiple widgets. Introduce/reuse one small client helper such as `isTaskActorRelationType(type)` or equivalent in the existing domain-label/relation helper layer.

17. All non-actor generic direct relations remain visible and unchanged, including `related_to`, `references`, `depends_on`, and `part_of` where valid.

18. Do not delete/reject/change any edge in storage. This is presentation-only deduplication.

### Explicitly out of scope

Do NOT:

- change Person identity candidate scan depth;
- attach or infer email/identity from global text search;
- alter the 90-day/400-row Person communication scan;
- change People/Task shared topology or window partitioning;
- redesign salience;
- change HG4C paging;
- change Task actor semantics/direction/types;
- change PersonRole semantics;
- add Person→Person relation types;
- modify generic object PATCH/embedding behavior beyond no longer using it for Person rename;
- deploy production;
- build/install the user's client;
- call providers/models;
- modify raster role-import extraction;
- resume historical HG2 repair/backfill.

The identity-candidate depth issue and shared topology/window issue are separately recorded follow-ups and require fresh Architect authorization.

### Expected implementation scope

Likely relevant:

Backend:
- `backend/app/api/routes/graph_workspace.py`
- `backend/app/api/schemas.py`
- `backend/app/services/person_identity_service.py` or the narrow existing Person service selected consistently
- focused People API tests

Client:
- `client/lib/api/secretary_api_client.dart`
- `client/lib/api/api_models.dart` only for a narrow immutable Person title helper if needed
- `client/lib/graph/graph_workspace_controller.dart` only for a small authoritative Person-title state helper if needed
- `client/lib/graph/graph_workspace_screen.dart`
- existing domain-label/relation helper file for one actor-type predicate
- focused Person rename/relation presentation tests

Do not refactor unrelated graph state.

### Required backend tests

At minimum prove:

1. Person rename trims and persists a valid new title.
2. Blank/whitespace-only title returns 422 and preserves old title.
3. Title >200 characters returns 422 and preserves old title.
4. Non-Person target is rejected/fails closed.
5. Rejected/deleted/foreign Person cannot be renamed through this endpoint.
6. The endpoint succeeds even when the user embedding-service dependency is configured to fail if touched; prove the rename path does not resolve/call it.
7. After rename, direct GET / object representation returns the new title.
8. Rooted People workspace returns the new title.
9. Global lexical search for the new title returns the Person with the new title without requiring embedding refresh.
10. Existing generic `PATCH /objects/{id}` behavior is unchanged.

### Required client tests

At minimum prove:

11. Rename dialog starts with current title and blank input cannot submit.
12. While rename HTTP is delayed, dialog remains open, one request is sent, and double submit is prevented.
13. Successful unrooted Person rename:
    - uses the Person-specific endpoint, not generic object PATCH;
    - closes only after success;
    - immediately shows the returned new title;
    - keeps controller `rootId == null`;
    - preserves current People page/window.
14. Successful rooted Person rename immediately updates the rooted title without a forced full workspace reload.
15. Rename failure keeps the dialog/input available and exposes a visible recoverable error; old title remains.
16. A stale older rooted/detail/reconciliation response cannot restore the pre-rename title after a newer successful rename.
17. For a Person with a confirmed Task actor edge, the specialized `Участие в задачах` tile remains visible while the generic `Связи` inventory does not render that same actor edge.
18. All four actor types are excluded from generic direct relation inventory.
19. An actor edge returned only by off-canvas/direct-neighbor loading is also excluded.
20. A non-actor generic relation for the same Person remains visible.
21. Existing HG4B actor mutation tests and HG4C People window tests remain green.

Run the smallest focused backend + Flutter suites covering these contracts.

Run:

- Ruff/appropriate Python checks for touched backend/tests;
- Dart formatting/analyzer checks for touched client files;
- `git diff --check`.

### Completion protocol

When implementation and checks are green:

1. update `PROJECT_STATE.md` with a concise factual HG4E implementation/test entry;
2. replace this file with `HOLD`, recording implementation SHA and exact checks;
3. commit + push to canonical `main`;
4. STOP.

Do not deploy production or start identity-candidate/topology work automatically.

Production remains:
`a9221699b4b725888213ff38e6673495a512042c`

Alembic remains:
`0054 / 0054`

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
