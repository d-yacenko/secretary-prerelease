# Current task — ACTIVE

## AH2-AP1 — frozen semantic approval presentation for internal action plans

Architect review before this authorization:

- AH2-FIN2 implementation: `c649981c6342b24eb3eee71c1b727e16b25b1744`
- AH2-FIN2 HOLD: `56cfaff981aace5b1da43afc6e2eaa2b0992acf0`
- AH2-FIN2: **ARCHITECT SOURCE-ACCEPTED**
- production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`

AH2-FIN2 acceptance basis:

- temporal finalization is isolated in `backend/app/assistant/temporal_finalization.py`;
- frozen/user-approved timestamps are used for wording only after timezone-aware same-instant verification against execution output;
- instant mismatches fail safe and do not claim the frozen value was applied;
- `update_task changed=false` emits no temporal-change fact;
- raw execution results remain authoritative for state/instant;
- AH2-FIN1 language continuity remains intact;
- storage, scheduled-job instants, schema, production, model calls, and real network were unchanged.

## Problem observed in manual AH2 acceptance

Internal approval cards expose implementation details rather than the human semantic action.

Examples observed:

- A1: `Set task status: <UUID> -> open`
- M2 / R2 / F1: `Update task: <UUID>`
- R1: `Link objects`
- R3: `remove relation`

By contrast, Gmail and Mattermost approval cards already show useful human semantics: destination/route, subject/body, reply mode, etc.

Current client source confirms the asymmetry:

- `PendingAction.displayLabel` in `client/lib/api/api_models.dart` derives labels directly from `tool_name + arguments`;
- internal mutation labels therefore fall back to English tool names and raw ids;
- `_ActionPlanCard` renders that label directly;
- action-plan API currently exposes only `tool_name` and public frozen `arguments`.

An approval decision must be based on **what the action means to the user**, not on UUIDs or internal tool names.

## Goal

Add a bounded, frozen, server-authored **semantic approval presentation snapshot** for internal action-plan actions and render it in the client.

The snapshot is presentation only.

Execution must continue to use exactly the existing frozen:

- `tool_name`;
- canonical `arguments`.

The presentation snapshot must never become an execution input or alter domain semantics.

## Core contract

### A. Presentation is frozen with the plan

At action-plan creation time, build a deterministic presentation snapshot from the canonical user-owned state needed to explain the action.

Persist that snapshot with the action in the existing JSON action-plan payload.

No schema migration is expected or authorized.

A later rename/status change of an involved object must not silently rewrite what the approval card said the user was approving.

For new plans, the semantic snapshot should be stable across:

- initial Assistant response;
- conversation reload;
- GET/read of the pending plan;
- approve/reject response.

### B. Execution remains presentation-blind

Approval execution must continue to read only the existing executable action contract.

A presentation snapshot:

- must not change the target id;
- must not change relation type/direction;
- must not change temporal values;
- must not change provider route;
- must not be used by `execute_approved_actions_with_tools`;
- must not be accepted from the client as a mutation request.

Add a regression proving that changing presentation data cannot change execution behavior.

### C. Human semantic targets, not raw ids

For the internal actions below, approval UI must prefer semantic presentation and must not show raw UUIDs as primary copy when the semantic snapshot is available.

Required coverage:

1. `create_task`
2. `update_task`
3. `set_task_status`
4. `delete_task` if it shares the same presentation path
5. `link_objects`
6. `remove_relation`
7. `create_scheduled_activity`

Do not redesign external send/email cards in this slice; preserve their current good behavior.

### D. Required semantics by action

#### create_task

Show at least:

- human action: create Task / create Direction when `completion_mode=ongoing`;
- title;
- important supplied due/planned fields if present.

Do not expose confidence or internal provenance noise as primary confirmation copy.

#### update_task

Show the target Task title and the semantic fields being proposed.

At minimum support the fields exercised by manual acceptance:

- `due_at`;
- `planned_start_at` + `planned_end_at`;
- `completion_mode`;
- `waiting_on_person_ids`;
- `evidence_object_ids`.

Where the frozen update supplies object/person ids, resolve and freeze bounded titles for the card.

Do not display a UUID in place of a title when the target was valid at staging time.

It is acceptable for this slice to show a compact "will set/add" semantic summary rather than a full arbitrary before/after diff for every possible update field.

#### set_task_status

Freeze:

- target Task title;
- current status at staging time;
- proposed status.

A no-op-looking proposal such as `open -> open` must remain visible as exactly that; do not pretend it is a meaningful state transition.

#### link_objects

Freeze:

- source title/kind;
- target title/kind;
- canonical relation type;
- canonical direction.

For `part_of`, presentation must preserve the canonical semantic direction:

**child/source -> parent/target**.

The user should see an equivalent of:

`Добавить в направление: Бизнес -> Экспериментальная рубрика октября`

rather than `Link objects`.

Do not alter generic relation ontology.

#### remove_relation

Resolve the exact frozen edge id at staging/presentation time and freeze:

- source title/kind;
- target title/kind;
- relation type/direction.

The user should see the relation being removed, for example:

`Удалить основание: Экспериментальная рубрика октября -> Приглашение_ЮФУ.pdf`

Do not broaden exact-edge removal into pair/type guessing.

#### create_scheduled_activity

Show:

- reminder/activity title;
- approved `run_at` representation;
- priority only if it materially helps the user.

Keep Scheduled Activity distinct from Task and Calendar Event.

### E. Snapshot data is bounded and privacy-safe

Presentation snapshot must contain only what is necessary for confirmation.

Do not include:

- message/email bodies for unrelated internal actions;
- arbitrary object metadata;
- hidden provider identifiers;
- credentials/secrets;
- embeddings;
- full graph neighborhoods;
- unbounded lists.

Titles/labels must be length-bounded.

Continue to hide existing private action argument keys such as:

- `operation_id`;
- `rfc822_message_id`;
- `calendar_href`.

### F. Legacy plans fail soft

Old stored plans created before this change will have no semantic presentation snapshot.

They must still:

- load;
- approve/reject/resume;
- execute with identical semantics.

Client may fall back to the existing legacy label for such historical plans.

Do not fabricate a "frozen" snapshot for an old plan from current mutable state and present it as if it were frozen at staging time.

## Preferred data shape

Exact schema naming is implementation choice, but prefer structured semantic data over a prelocalized prose blob.

For example, an optional per-action object equivalent to:

`presentation: { operation, entities, relation_type, fields, ... }`

where entity snapshots contain bounded:

- role;
- id if needed for internal navigation/debug but not primary UI text;
- title;
- kind.

The Flutter client should own Russian UI labels/formatting where practical.

Do not make the model author approval-card copy.

## Preferred implementation boundary

Likely touch points:

- a focused backend approval-presentation builder;
- `AssistantService._persist_staged_action_plan` or the nearest action-plan creation boundary;
- `PendingActionPlanView` / public-action projection;
- Assistant API output models/serializers;
- persistent conversation hydration of pending plans;
- client `PendingAction` model;
- `_ActionPlanCard` / focused preview widgets;
- deterministic backend and Flutter tests.

The same persisted semantic snapshot should be reused after conversation reload. Do not make the client issue N+1 object fetches to reconstruct card semantics.

## Explicit non-goals

Do not in AH2-AP1:

- fix the A1 pre-approval prose contradiction (`Изменено...` before execution); that is a separate staging-truthfulness slice;
- change post-approval finalization;
- change Task/Person/Flow ontology;
- change relation direction or execution semantics;
- change Person resolution;
- change T3 unsupported-relation behavior;
- add Scheduled Activity to Today/Week/mobile;
- redesign all Assistant chat UI;
- run model evaluation;
- deploy backend or install a client;
- add schema/Alembic migration.

## Required deterministic tests

At minimum prove:

1. **snapshot persistence**
   - stage a plan for a named Task;
   - semantic presentation is stored with the plan;
   - reload/conversation hydration returns the same presentation.

2. **snapshot survives rename**
   - stage against Task title A;
   - rename canonical object to title B after staging;
   - approval presentation remains frozen as A;
   - execution still targets the exact same object id.

3. **A1 status card**
   - Task title is visible;
   - `open -> open` is represented semantically;
   - raw UUID is not primary card text.

4. **R1 part_of card**
   - source/child and target/parent titles are present;
   - relation is `part_of`;
   - child -> parent direction is unambiguous.

5. **R3 remove card**
   - exact edge snapshot contains source, target, relation type;
   - card does not collapse to generic `remove relation`.

6. **R2 waiting_on update**
   - Task title and Person title are presented;
   - no generic relation substitute is introduced.

7. **F1 evidence update**
   - Task title and evidence object title are presented;
   - evidence remains `references`/evidence semantics, not a new Task.

8. **M2 temporal update**
   - Task title plus frozen planned interval/due values are present in approval presentation;
   - FIN2 post-approval temporal facts remain separate and unchanged.

9. **Scheduled Activity card**
   - title and frozen `run_at` are present;
   - card semantics identify a reminder/scheduled activity rather than Task/calendar event.

10. **presentation cannot affect execution**
    - alter/tamper presentation in a stored test plan while leaving executable arguments unchanged;
    - approved execution follows only tool name + arguments.

11. **legacy plan**
    - plan without presentation still serializes, loads, approves/rejects as before;
    - client does not crash and uses a bounded legacy fallback.

12. **privacy/bounds**
    - long titles are bounded;
    - unrelated bodies/metadata and hidden action keys are absent from presentation.

13. **external communication regression**
    - existing Gmail and Mattermost approval previews remain unchanged and green.

## Required checks

Run at least:

- focused backend action-plan tests;
- persistent Assistant conversation tests;
- relevant AH2 eval/action-plan tests for R1/R2/R3/F1/M2/A1;
- focused client API-model tests for the new optional presentation field;
- Assistant card widget tests covering semantic internal previews;
- preserved Gmail/Mattermost approval-card tests;
- focused `flutter analyze` for changed client files;
- `git diff --check`.

Record exact pass counts.

Model calls: 0.
Real external network calls: 0.

## Acceptance criteria

AH2-AP1 is complete only when:

- internal pending actions have a frozen semantic presentation snapshot for the required action set;
- the snapshot is persisted and survives conversation reload;
- human-readable cards no longer depend on live client-side UUID lookup;
- current semantic titles/roles/relations are frozen at staging time for new plans;
- execution ignores presentation completely;
- legacy plans remain executable;
- external communication cards do not regress;
- no schema, ontology, or execution-contract change occurs;
- tests/analyze are green;
- production is untouched.

## Completion protocol

After implementation:

1. append a compact factual AH2-AP1 result to `PROJECT_STATE.md`;
2. record AH2-FIN2 Architect source acceptance in the same ledger update;
3. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - exact changed files;
   - presentation schema/contract;
   - supported action types;
   - frozen-vs-legacy behavior;
   - proof presentation cannot affect execution;
   - exact backend/client test counts;
   - confirmation of no schema/model/network/deploy;
4. commit + push to `main`;
5. STOP.

Do not start staging-prose truthfulness, T3, Person aliases, or Scheduled Activity product integration from HOLD.
