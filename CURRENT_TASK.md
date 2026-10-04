# CURRENT_TASK

## Status

ACTIVE

## REL1D-C2 — client row selection + frozen ActionPlan approval UX

REL1D-C1 / C1.1 are **ARCHITECT SOURCE-ACCEPTED**.

Accepted source baseline:

- C1 atomic backend batch: `3d3bead03271bad5dfc5713eaf78a4d1062cb11e`
- C1.1 serialization corrective: `5cb4fd7400c8e095b6949e25eac0d1afc7b9fa51`
- Executor HOLD: `bf4b44edf869c4d32222e903b274bebec476a31f`
- schema: `0054`
- production/backend/client: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- production Alembic: `0054 / 0054`

Record this C1/C1.1 Architect acceptance in `PROJECT_STATE.md` together with the C2 result.

This task is primarily **client-only**. Backend semantics from C1 are frozen unless a tiny response-model compatibility fix is strictly required.

Do not deploy, migrate, install/replace the client, call a real model/provider, or mutate production data.

## Goal

Complete the explicit human-controlled REL1D flow:

1. extract roles;
2. ground people/roles;
3. explicitly select rows;
4. explicitly choose an ambiguous existing Person or a promotion candidate where needed;
5. prepare exactly one frozen ActionPlan;
6. inspect the backend-frozen approval presentation;
7. explicitly approve or reject;
8. show the deterministic execution result truthfully.

No automatic selection, prepare, approval, or persistence.

## Reuse existing backend contracts

Use:

- `POST /people/role-import/action-plan`
- `POST /assistant/action-plans/{id}/approve`
- `POST /assistant/action-plans/{id}/reject`

Do **not** create another confirmation endpoint.

Do **not** call:

- `/assistant/action-plans/{id}/resume`
- Assistant message/finalization
- OpenAI/provider APIs

for role-import approval/result rendering.

REL1D-C2 result UI is deterministic from ActionPlan response.

## Client API

Add a typed method equivalent to:

`prepareRoleImportActionPlan(...)`

Request must send exactly the current:

- source_object_id
- source_revision
- grounding_revision
- items_truncated
- original extraction items
- explicit selections

Selection payload:

- row_index
- exactly one:
  - person_id
  - promotion_candidate_key

Never send:

- role_term_id
- role suggestion choice
- raw identity
- normalized role key
- create-role boolean
- assignment id

Return/parse the normal frozen PendingActionPlan/ActionPlan shape including backend `presentation`.

Approve/reject must reuse the existing API client methods.

## Selection state

Maintain role-import selection state separately from chat message ActionPlans.

Per grounded row:

- selected: bool
- selected existing Person id OR selected promotion candidate key when required

All rows start **unselected** after every fresh grounding.

### resolved row

- may be selected with one checkbox/control;
- target is the exact server-resolved Person id;
- no alternate Person picker.

### ambiguous row

- may be selected only after the user explicitly chooses one candidate;
- no default candidate;
- no salience-based preselection.

### promotion_candidates row

- may be selected only after the user explicitly chooses one candidate;
- no default promotion candidate;
- label must make clear this will create/promote a Person if approved.

### unresolved row

- cannot be selected;
- remains visibly unresolved.

RoleTerm selection is never editable in C2:

- `reuse_existing` stays existing;
- `propose_new` stays the exact new role;
- lexical suggestions remain advisory text only;
- no suggestion radio/dropdown.

## Prepare button

After successful grounding show:

**Подготовить изменения**

Enable only when:

- source is not stale;
- grounding exists;
- at least one row is selected;
- every selected ambiguous/promotion row has an explicit valid target;
- no role-import prepare/approve/reject request is in flight;
- no role-import plan is currently pending.

Do not prepare automatically after selection.

If no valid selected rows, button is disabled.

## Freshness / clearing

Changing any of the following invalidates local selection and role-import plan/result state:

- Assistant object context;
- re-extraction;
- re-grounding.

A late prepare response for an older:

- source id;
- source revision;
- grounding revision;
- role-import epoch

must not overwrite current UI state.

Existing extraction/grounding late-response fences remain intact.

### Prepare stale errors

If prepare returns:

`role_import_source_changed`

- mark source stale;
- clear selection/grounded plan state;
- show:
  - `Источник изменился — извлеките роли заново`
- require explicit re-extraction.

If prepare returns:

`role_import_grounding_changed`

- clear selection and pending role-import plan;
- keep extraction if source is still current;
- show:
  - `Сопоставление изменилось — сопоставьте роли заново`
- require explicit re-grounding before another prepare.

Do not auto re-ground.

## Frozen approval card

After successful prepare:

- freeze/disable row selection controls;
- show one approval card from the **backend action presentation**, not recomputed from mutable current selection;
- status:
  - `Требует подтверждения`

Show:

- source title;
- selected/total row count;
- source/items truncation warnings;
- each frozen selected row:
  - target display;
  - target mode:
    - existing Person;
    - новый Person;
  - role;
  - optional context;
  - vocabulary mode:
    - существующая роль;
    - новая роль.

Do not display:

- promotion candidate key;
- raw identity canonical values;
- normalized role key;
- provenance key;
- upload path.

Buttons:

- **Подтвердить**
- **Отклонить**

No auto-approval.

Role-import batch is not voice-approvable in this slice.

## Approval

On **Подтвердить**:

- call existing `approveActionPlan(plan.id)` exactly once per click/in-flight operation;
- do not call Assistant resume/finalization;
- do not call model/provider;
- disable duplicate clicks while in flight.

Handle returned terminal status deterministically.

### executed

Parse:

`result.actions[0].output`

for `apply_role_import_batch`.

Display aggregate facts:

- people_created
- assignments_changed
- assignments_no_op
- duplicate_rows

Display row statuses:

- `applied` -> `Применено`
- `already_active` -> `Уже было`
- `duplicate_selected_row` -> `Дубликат выбранной строки`

Truthfulness:

- if `changed=true`:
  - replace `Ничего не сохранено` with **`Изменения сохранены`**;
- if `changed=false`:
  - show **`Изменений нет`**;
  - do not claim anything was added.

After execution:

- selection controls stay frozen;
- approve/reject buttons disappear;
- no Assistant resume call.

### failed

Show:

- `Ошибка применения`
- sanitized backend failure text if available.

C1 atomicity guarantees no partial Person/Role facts; UI must not claim partial success.

If failure is:

- `role_import_source_changed` -> mark source stale, require re-extraction;
- `role_import_grounding_changed` -> require re-grounding.

For other failure, show deterministic failure and an explicit path to discard/reset the failed plan and re-ground before retrying.

### expired

Show:

- `Подтверждение истекло`

No persistence claim.

User may discard the expired plan and prepare again from current grounding; backend prepare will revalidate freshness.

## Rejection

On **Отклонить**:

- call existing `rejectActionPlan(plan.id)`;
- do not call resume/finalization/model;
- show:
  - `Отклонено`;
- preserve `Ничего не сохранено`;
- unlock an explicit **Изменить выбор** / reset path so the user may edit and prepare a new plan.

If reject returns expired, show expired state.

## Plan reset / edit

Add an explicit local reset control for terminal non-executed plans:

**Изменить выбор**

For:

- rejected;
- expired;
- failed when source/grounding is still usable.

It clears only local plan/result/error state and returns to row selection.

It does not change server terminal plan state.

For source/grounding drift, require the appropriate re-extract/re-ground step instead.

Executed plans cannot be reset into editable state without a fresh re-extraction/re-grounding cycle.

## Interaction with ordinary Assistant

Do not append role-import preview/plan/result as fake Assistant chat messages.

Do not use `MessageActionPlan` message-index approval methods for this workflow if that would trigger Assistant resume.

Role-import approval may have dedicated controller methods using the same API transport.

Ordinary Assistant chat remains otherwise unchanged.

Do not make role-import plan voice approval part of this slice.

If a normal chat ActionPlan is already pending or its approve/reject operation is busy:

- disable role-import prepare/approve/reject actions;
- do not create a second competing approval operation from this panel.

Do not modify existing voice approval semantics.

## PendingAction presentation parsing

Prefer reusing existing:

- `PendingAction`
- `PendingActionPlan`
- `ActionPlanResponse`

Add a semantic display helper for `apply_role_import_batch` only if useful.

The role-import card must render the frozen backend `presentation`, never trust client selections as approval truth.

## Controller state

Use a bounded explicit state machine, e.g.:

- selection/editing
- preparing
- pending
- approving
- rejecting
- executed
- rejected
- expired
- failed

Equivalent representation is acceptable.

Keep role-import errors separate from ordinary Assistant message/action-plan errors.

On auth failure, preserve existing auth-controller behavior.

On network failure:

- keep current plan/selection state;
- show retryable error;
- do not assume approve/reject succeeded.

A repeated approve after an uncertain network failure is safe because backend ActionPlan approval is idempotent.

## UI warnings

Preserve source completeness truth:

- source_truncated warning;
- items_truncated warning.

Before terminal execution, continue to show:

**Ничего не сохранено**

After executed changed=true, do not show that statement.

After executed changed=false, show **Изменений нет**.

After rejected/expired/failed, no success statement.

## Required deterministic client tests

Extend `client/test/assistant/role_import_preview_test.dart` or split a focused C2 module.

Prove at minimum:

1. all freshly grounded rows start unselected;
2. resolved row checkbox prepares exact resolved person_id;
3. ambiguous row has no default Person;
4. ambiguous selected without candidate cannot prepare;
5. explicit ambiguous candidate sends that person_id only;
6. promotion row has no default candidate;
7. explicit promotion sends candidate_key only;
8. unresolved row cannot be selected;
9. role suggestions are not selectable and never sent;
10. prepare is not automatic;
11. prepare button disabled with zero/invalid selection;
12. prepare body includes current source revision, grounding revision, items_truncated and exact extraction rows;
13. prepare response creates one pending frozen card;
14. card renders backend presentation, including truncation/counts;
15. card does not expose candidate_key/raw identity/provenance internals;
16. row controls freeze while plan pending;
17. approve sends exactly one request and no `resume`/Assistant/model request;
18. executed changed=true shows `Изменения сохранены`;
19. executed changed=false shows `Изменений нет`;
20. aggregate execution counts are truthful;
21. applied/already-active/duplicate statuses render correctly;
22. reject sends one request, shows `Отклонено`, keeps no-save truth;
23. expired renders correctly and can return to edit selection;
24. failed renders atomically as failure, never partial success;
25. prepare source-changed requires re-extraction;
26. prepare grounding-changed requires re-grounding;
27. approve source/grounding-changed failure maps to same stale UX;
28. context change clears selection/plan/result;
29. re-extraction clears selection/plan/result;
30. re-grounding clears prior selection/plan/result;
31. late prepare response cannot overwrite newer grounding;
32. duplicate approve/reject click while in flight sends one request;
33. normal chat ActionPlan busy state disables role-import approval operations;
34. ordinary Assistant message flow remains unchanged;
35. role-import plan is never inserted into chat history;
36. role-import approval never calls `/assistant/action-plans/{id}/resume`.

Run focused API-client tests for prepare/approve/reject JSON and error mapping.

## Backend regression

No backend production changes are expected.

Run at minimum:

- `backend/tests/test_rel1d_role_import_batch.py`

to prove C1 contract still green.

If backend code is changed for a genuinely necessary response compatibility issue, also run the directly affected backend suites and record why.

## Flutter checks

Run:

- focused role-import C2 tests;
- existing role-import preview tests;
- focused Assistant controller/action-plan tests touched by shared helpers;
- focused API-client tests;
- `flutter analyze` on changed Dart files;
- `git diff --check`.

All relevant focused checks: 0 failed.

Do not install the client.

## Expected changed files

Client bounded subset:

- `client/lib/api/role_import_models.dart`
- `client/lib/api/secretary_api_client.dart`
- `client/lib/api/api_models.dart` only if semantic presentation helper is added
- `client/lib/assistant/assistant_controller.dart`
- `client/lib/assistant/role_import_preview.dart`
- focused client tests

Backend expected: none.

Do not change:

- C1 batch persistence semantics;
- ActionPlan backend TTL/status semantics;
- Person resolver/promotion rules;
- RoleTerm normalization;
- Alembic/schema;
- Proactive/REL1B;
- provider/model configuration.

## Explicit non-goals

Do not add:

- automatic row selection;
- fuzzy Person choice;
- role suggestion selection;
- bulk edit of extracted role text;
- Organization import;
- voice approval for role import;
- Assistant model finalization/resume;
- deployment/rollout.

## Production boundary

Source-only development.

Do not:

- move `production`;
- deploy backend;
- migrate;
- install/replace client;
- call real model/provider;
- run a real role import against production;
- mutate production data.

Production/backend/client remain exact:

`6f802d6959aca40758376a83d5bdfcbbd77fc537`

Alembic remains:

`0054 / 0054`

## Expected next step after acceptance

If C2 is source-accepted, REL1D is source-complete.

Do **not** automatically deploy.

Next operational step should be a separately human-authorized controlled REL1D rollout / human acceptance gate because it involves:

- production backend deploy;
- client replacement;
- one real screenshot/document extraction model call;
- explicit human review of grounding and batch confirmation.

That rollout requires explicit user authorization.

## Completion

1. update `PROJECT_STATE.md` with:
   - C1/C1.1 Architect source acceptance;
   - C2 selection/approval/result UX;
   - confirmation that no resume/model path is used;
   - exact test counts;

2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - exact green test counts;
   - schema `0054`;
   - production/client unchanged;
   - no deploy/migration/client install/real model/provider/production-data action;
   - REL1D source-complete only if all C2 contracts are satisfied;

3. commit + push `main`;

4. STOP.

Do not deploy from HOLD.
