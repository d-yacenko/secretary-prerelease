# Current task — Task/Direction S2R: truthful mode conversion + create/edit form convergence

Production D2 is accepted and production remains on exact release:
`fd45df20ff53ad973f22e461ff84f3cb5c251b8a`

Human visual validation found one real corrective and one closely related UX refinement.

This task authorizes implementation/tests on `main` only.

NO production deploy is authorized.
Do not start S3 or H2D.

## Human evidence

Against the real production backend the human:

- successfully created an ongoing Direction through manual Capture;
- selected the existing finite Task “Академ”;
- opened `Редактировать`;
- selected `Направление`;
- saved;
- saw the success feedback;
- but the Graph still presented the object as a rectangular finite Task, and the visible object properties still described it as `Задача`.

Treat this as a failed finite -> ongoing human path until code/tests establish the full state transition and Graph presentation.

Do not use the user's production data to reproduce the defect.

## Architectural invariant

Direction is NOT a new object kind.

Canonical representation remains:
- `kind=task`;
- `completion_mode=finite` => human Task / `Задача`;
- `completion_mode=ongoing` => human Direction / `Направление`.

Do not change kind, introduce a Direction kind, infer mode from title/text/due dates, or rewrite existing relations.

Existing part_of compatibility/lifecycle guards remain authoritative.

## Part A — diagnose and fix finite <-> ongoing human edit truth

Trace the real client path end-to-end:

`TaskManagementActions editor -> TaskPatchRequest -> PATCH /tasks/{id} -> TaskMutationResponse -> onTaskUpdated -> GraphWorkspaceController -> Graph presentation/detail`.

The current isolated widget test that only asserts an outbound `completion_mode` payload is insufficient.

Add focused regression coverage that starts with a finite Task, performs the actual editor interaction `Задача -> Направление -> Сохранить`, and proves all of:

1. PATCH contains `completion_mode=ongoing`;
2. returned mutation object has `completion_mode=ongoing`;
3. controller/workspace state for that id becomes ongoing;
4. the Graph uses the ongoing Direction presentation (circular `HybridOngoingTaskNode`, not the finite rectangle);
5. human-facing object summary/properties say `Направление`, not `Задача`;
6. a workspace/readback refresh does not revert the object to finite.

Add the reverse path `ongoing -> finite` as well:
- payload is finite;
- Graph returns to finite Task presentation;
- summary says `Задача`.

If the existing implementation already passes one layer, do not stop there: identify the layer that explains the human symptom and fix that layer.

Do not paper over a persistence defect with presentation-only local state.

### Human-facing labels

The generic object `kind` may remain `task`, but any Task/Direction summary used in this Graph/detail flow must map:

- ongoing Task -> `Направление`;
- finite Task -> `Задача`.

Do not globally rename unrelated technical/API kind fields.

### Success feedback

Do not show a misleading generic success if the mutation did not change the requested field.

Use the actual mutation response/readback so the UI only presents success for the requested mode when the resulting object reflects that mode.

## Part B — converge manual Capture with the editor form

The current Capture screen is visually primitive compared with the newer edit dialog.

Refactor manual Task/Direction creation so the core form is approximately the same field model and density as edit.

Required creation fields/controls, in this order:

1. segmented `Задача / Направление`;
2. `Название`;
3. `Описание`;
4. due date / `Без срока` with set/clear controls;
5. `Запланированное время` with set/clear controls;
6. existing context/dependency attachments and existing voice/drop behavior remain available.

Do not require an exact pixel clone of the edit AlertDialog, but remove the current giant sparse text-area composition and make creation/readability clearly consistent with editing.

The primary action should reflect the selected mode:
- finite -> `Создать задачу`;
- ongoing -> `Создать направление`.

Default remains finite.

After successful creation/reset, the next draft resets to:
- finite;
- no due date;
- no planned interval;
- existing current reset semantics for title/body/context/dependencies.

A failed submit preserves all user-entered fields including mode/dates/planned interval.

## Capture API parity for due/planned fields

Extend the existing Capture contract narrowly; no migration.

`POST /capture/task` may add optional:
- `due_at`;
- `planned_start_at`;
- `planned_end_at`.

Rules:
- omission preserves old-client behavior;
- due_at may be omitted/null according to the existing creation semantics you establish consistently;
- planned start/end must be both set or both absent/null as one interval;
- use the existing timezone-aware datetime conventions;
- pass values through to the existing Object creation fields;
- preserve `status=open`, `origin=user`, `state=confirmed`;
- preserve explicit finite/ongoing semantics;
- preserve context `references`, `depends_on`, embedding enqueue, and cross-user fail-closed behavior;
- Capture still does NOT create `part_of`.

Prefer shared validation/helpers already used by ObjectCreate/planned execution rather than duplicating rules.

## Reuse / drift control

Prefer extracting/reusing small Task field widgets/helpers between create and edit where that reduces future drift, especially:
- mode selector;
- due-date row;
- planned-interval row;
- human-facing Task/Direction labels.

Do not perform a broad UI architecture rewrite.

## Tests

Backend focused coverage must include at least:
- old Capture payload without new fields remains valid;
- finite and ongoing creation;
- due date creation;
- planned interval creation;
- invalid half-planned interval rejected;
- ongoing + due/planned remains ongoing;
- context/dependency behavior unchanged.

Client focused coverage must include at least:
- finite -> ongoing real edit callback/presentation path;
- ongoing -> finite reverse path;
- ongoing human summary label;
- Capture defaults finite;
- selecting ongoing changes action label;
- Capture request carries mode/title/body/due/planned values;
- failed submit preserves the draft;
- successful submit/reset clears temporal fields and returns finite;
- existing context/dependency attachment preservation;
- existing Capture voice/drop behavior is not regressed by the refactor.

Run the existing relevant Task management, Capture, Graph/hybrid, API-client, and backend Task/Capture suites.

Run Flutter analyze on touched files and `git diff --check`.

A Linux debug build is required.

## Scope guard

Do NOT:
- deploy backend/client to production;
- move `origin/production`;
- change Alembic or DB schema;
- create/read/modify production Tasks for diagnosis;
- use the user's bearer token;
- perform manual GUI clicking on behalf of the human;
- change Task/Direction ontology;
- infer completion_mode;
- change part_of semantics;
- start S3;
- start H2D;
- fold in the separate saved-server-URL / `SECRETARY_API_BASE_URL` precedence issue;
- fix unrelated failures.

If implementation uncovers a backend persistence defect outside this bounded Task PATCH/Capture path, STOP and report it rather than broadening scope.

## Completion

On completion:

1. update `PROJECT_STATE.md` with root cause, implementation SHA, exact tests/results, and whether a backend application deploy will be required;
2. return `CURRENT_TASK.md` to HOLD;
3. push the normal implementation/HOLD commits to `main`;
4. do not deploy;
5. STOP.

Final report must state:
- root cause of the human finite -> ongoing failure;
- finite -> ongoing regression proof;
- ongoing -> finite regression proof;
- resulting human labels/presentation;
- Capture UI changes;
- Capture API changes;
- backend tests;
- client tests/analyze/build;
- implementation SHA;
- HOLD/main SHA;
- whether the next step needs a schema-neutral backend/client rollout.

Then STOP. Do not choose the next task yourself.
