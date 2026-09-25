# Current task — Task Refinement T2: Task Profile human projection in Graph UI

Task Refinement T1/T1R is architect-accepted. Implement the first human projection of the shared canonical Task Profile.

Do not implement automatic task discovery, proactive prioritization, project/roadmap semantics, new Task entity types, organization inference, provider calls, or production deployment.

## Goal

In existing Graph `Задачи` mode, selecting a Task should present the same semantic Task Profile already available to Assistant/MCP:

- lifecycle/timing;
- Actor roles;
- dependencies;
- evidence/context;
- proposed vs confirmed relation state.

The UI should let the user inspect and correct this semantic state without introducing a parallel client-side Task model.

## 1. Client Task Profile model/API

Add client DTOs matching `GET /tasks/{task_id}/profile`.

Expose through `SecretaryApiClient`:
- getTaskProfile(taskId);
- addTaskActor(taskId, personId, role);
- removeTaskActor(taskId, edgeId);
- addTaskDependency(taskId, dependsOnTaskId);
- removeTaskDependency(taskId, edgeId);
- attachTaskEvidence(taskId, objectId) only if needed by UI in T2;
- decideRelation(edgeId, decision) already exists and should be reused for agent proposals.

Do not reconstruct Task roles by scanning graph edges in Dart.

## 2. Graph Task detail panel

When selected object is an active Task in `Задачи` mode:
- load Task Profile asynchronously;
- preserve existing object details/actions;
- add a compact semantic section, not a new full-screen workflow.

Suggested sections:
- **Люди**
  - Запросил;
  - Поручено;
  - Ждём;
  - Участвует.
- **Зависимости**
  - Зависит от;
  - От этой задачи зависят.
- **Основание**
  - evidence/context Objects.

Show timing/lifecycle using the existing task fields/labels.

Do not duplicate large message bodies/evidence text into the panel; show compact object title/type/provider/date and allow normal object navigation where available.

## 3. Proposed vs confirmed truth

Task Profile relation items already expose:
- `edge_state`;
- `edge_origin`;
- `edge_confidence`.

UI requirements:
- confirmed relations appear as normal grounded facts;
- proposed relations must be visually distinct and explicitly labelled as a suggestion/proposal;
- do not silently present proposed as confirmed;
- for `origin=agent, state=proposed`, expose actions:
  - **Подтвердить** -> existing `POST /relations/{edge_id}/decision` with `confirm`;
  - **Отклонить** -> same endpoint with `reject`;
- after decision, reload Task Profile;
- confirmed/rejected decision rules remain backend-authoritative.

Do not add a second proposal-confirmation mechanism.

## 4. Explicit user relation editing — bounded T2 scope

Provide small explicit UI affordances for the most useful Task semantics:

### Add Person role

Allow adding one known canonical Person to one role:
- requested_by;
- delegated_to;
- waiting_on;
- involves.

Use existing People search/workspace APIs to choose a canonical Person. Do not accept free-text Person names as new identity truth.

After selection:
- call the Task actor endpoint;
- reload profile;
- duplicate confirmed relation remains idempotent.

### Remove current Person role

For a current user/agent removable role edge:
- require explicit user action on the exact relation item;
- call the Task-specific actor removal endpoint or existing exact relation removal path;
- preserve history (backend rejection), no client-side deletion.

For proposed relation, prefer explicit reject decision rather than generic remove.

### Add/remove dependency

Allow choosing an existing canonical Task:
- search existing Tasks;
- add `depends_on`;
- remove an exact current dependency edge;
- prevent self-dependency in UI, but backend remains authoritative.

Do not add drag/drop graph editing.

## 5. Evidence is primarily inspectable in T2

Evidence/context should be visible and navigable.

Do not build a broad manual evidence browser in T2 unless trivial reuse already exists.

At minimum:
- list bounded profile evidence;
- select/open evidence Object through normal Graph/source navigation;
- show proposed state distinctly if evidence relation is proposed;
- allow confirm/reject proposed evidence relation.

Manual “attach arbitrary evidence” UI may remain backend/API-only for now.

## 6. Person/Task navigation symmetry

From Task Profile:
- clicking Person should switch/re-root to People mode on that canonical Person where current Graph architecture supports it cleanly;
- clicking dependency Task should stay/switch to Tasks mode and re-root/select that Task;
- clicking evidence should use normal object/source navigation, not create a new navigation subsystem.

If direct cross-mode navigation would require a large refactor, implement safe selection/re-root only where current controller supports it and leave the rest as explicit clickable object detail.

## 7. Focus and visual density

The purpose is to answer quickly:
- who asked;
- who is doing it;
- whom am I waiting for;
- what blocks this;
- why does this task exist.

Do not expose raw graph complexity.

Requirements:
- collapsed/compact role groups where empty;
- avoid rendering every generic neighbor;
- no giant edge lists;
- existing Task edit/status actions remain available;
- no visible scoring/ranking taxonomy.

## 8. Proposed relation labels

Add/confirm Russian labels:
- requested_by -> `Запросил`;
- delegated_to -> `Поручено`;
- waiting_on -> `Ждём`;
- involves -> `Участвует`;
- depends_on -> `Зависит от`;
- reverse depends_on -> `Зависит эта задача` or a clearer natural equivalent such as `От неё зависят`;
- references/evidence -> `Основание`.

For proposal state use concise wording like `Предложено секретарём`.

Avoid overly technical `edge/state/origin` terms in user-facing copy.

## 9. Loading/error behavior

Task Profile load must:
- not block the entire Graph screen;
- show local progress in Task detail section;
- handle 404/deleted Task safely;
- preserve existing Graph selection if profile load fails;
- provide retry or graceful error text;
- ignore stale async result if user selects another object before response arrives.

## 10. No hidden mutation

Opening/selecting a Task must be read-only.

No relation is created, confirmed, removed, or lifecycle-changed merely by viewing profile.

## Focused proof

Add tests proving at minimum:

1. Client decodes Task Profile actor/dependency/evidence items including edge state/origin/confidence.
2. Selecting a Task loads `GET /tasks/{id}/profile`.
3. Switching selection before response completion does not render stale profile.
4. Confirmed Actor relation appears under correct role.
5. Proposed Actor relation is visibly marked proposed.
6. Proposed relation confirm calls existing relation-decision endpoint and reloads profile.
7. Proposed relation reject does the same and disappears after reload.
8. Add known Person to `waiting_on` uses canonical Person id and Task actor endpoint.
9. Duplicate add remains harmless/idempotent.
10. Remove current confirmed role uses exact edge id and reloads profile.
11. Add dependency chooses existing Task and calls dependency endpoint.
12. Self-dependency is prevented in UI and backend remains tested.
13. Remove dependency uses exact edge id.
14. Evidence appears under `Основание` and can be opened/navigated using existing object navigation.
15. Empty sections do not create noisy placeholders.
16. Existing Task edit/status actions still work.
17. Existing `Задачи | Люди` switch remains backward compatible.
18. People mode behavior is unchanged.
19. Existing backend Task Profile/relations tests remain green.
20. Existing Graph Flutter tests remain green except documented pre-existing failures.
21. No migration, auto-detection, proactive logic, project entity, provider call, or deploy.

Run:
- new Flutter Task Profile model/API tests;
- Graph controller/screen tests;
- task management action tests;
- existing People workspace tests;
- backend `tests/test_task_relations.py`;
- relevant direct Task API tests;
- Flutter analyze touched files;
- Ruff/compile only if Python changes are necessary;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not begin automatic obligation discovery, proactive attention, project/roadmap semantics, or deploy.
