# Current task — ACTIVE

## REL1A — explicit Person role facts foundation

User product direction, 2026-10-03:

The immediate People-track goal is **not** an organization hierarchy and not Person-to-Person social edges.

The useful fact is simpler:

> a known Person may have one or more explicit human roles such as “директор”, “студент”, “заведующий кафедрой”, “научный руководитель”, optionally with a short context such as “Arenadata” or “кафедра X”.

These role facts will later become one bounded evidence dimension when Secretary decides what deserves the user's attention. Example target for a later slice: a plain “Дима, мы тебя ждём” from a known director may deserve more attention than similarly urgent wording from an unrelated external sender, while message content, active Tasks, waiting relationships, due dates, and other evidence still matter.

REL1A itself **does not change importance/proactive ranking**. It establishes trustworthy role facts and a first-party editing/read surface first.

## Current accepted baseline

- Main before authorization: `0d2715a26d24ee1eae385397ba46c5953859f805`
- Production backend: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Installed Linux client source: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Production Alembic: `0052 / 0052`
- Production health: PASS
- AH2 remediation/client human gate: ARCHITECT ACCEPTED

Current Person truth already includes:

- canonical Person objects;
- exact provider identities and identity evidence;
- promotion candidates;
- salience;
- Task actor roles `requested_by`, `delegated_to`, `waiting_on`, `involves`;
- identity-grounded recent communications and routes.

There is currently **no canonical durable role fact on another Person**.

`docs/person_relationship_context_audit.md` remains useful background, but this task deliberately narrows the prior “relationship” idea: REL1A stores descriptive Person roles, not social hierarchy edges.

## Architectural decision for REL1A

Add a dedicated, reversible role-fact record.

Do **not** store roles in `Object.metadata`.
Do **not** encode them as generic graph edges.
Do **not** add `manager_of`, `colleague`, `member_of`, `role_at`, or another relation type.
Do **not** overload Task actor roles.

A role fact is:

> “For this user, this Person is explicitly known as ROLE, optionally in CONTEXT.”

Examples:

- `директор`
- `студент`
- `заведующий кафедрой`
- `научный руководитель`
- `директор` + context `Arenadata`

The role vocabulary is **free text**, not a closed enum. Secretary must not derive rank/order/authority from the string in REL1A.

Multiple active role facts per Person are allowed.

## Persistence contract

Create additive Alembic revision `0053` from `0052`.

Preferred table name:

`person_role_facts`

Minimum durable fields:

- `id` UUID PK;
- `user_id` FK users;
- `person_object_id` FK objects;
- `role_text` — user-visible role;
- `role_key` — deterministic normalized identity key for idempotence;
- `context_text` nullable — optional user-visible context;
- `context_key` non-null normalized key, empty string when context is absent;
- `origin` — REL1A writes only `user`, but keep this field suitable for a later approval-gated agent path;
- `state` — `active` / `retracted`;
- `provenance_kind`;
- `provenance_key`;
- `source_object_id` nullable FK objects, reserved for later grounded imports such as a user-supplied org-chart/document source;
- `created_at`;
- `updated_at`;
- `retracted_at` nullable.

If a different but equivalent schema is materially cleaner, Executor may use it, but all semantics below must hold.

### Normalization

For idempotence only:

- trim outer whitespace;
- collapse internal Unicode whitespace runs;
- case-fold deterministically;
- role must remain non-empty;
- optional context becomes empty normalized key when omitted/blank.

Suggested display bounds:

- role <= 120 chars;
- context <= 200 chars.

Do not stem, translate, fuzzy-match, synonym-expand, or infer hierarchy.

### Uniqueness

At most one active fact for:

`(user_id, person_object_id, role_key, context_key)`

Examples:

- adding `Директор` then ` директор ` with no context is idempotent;
- `Директор / Arenadata` and `Директор / Университет` are distinct;
- `Директор` without context and `Директор / Arenadata` are distinct.

Retraction preserves history. Re-adding a previously retracted role may create/reactivate an active fact according to the cleanest service design, but there must still be only one active normalized fact.

## Domain/service boundary

Add a focused Person-role service.

Required behavior:

- target must be an active current-user `kind=person` Object;
- cross-user ids fail closed;
- tombstoned/rejected/non-Person targets fail closed;
- add is idempotent on normalized role+context;
- list returns active facts only by default;
- retract is idempotent and never physically deletes history;
- no Person identity/merge/promotion rows are modified;
- no graph Edge is created;
- no Task relation is created;
- no salience score is changed in REL1A.

Keep a bounded role count per Person. Preferred max active role facts: 16. Reject a 17th distinct active role rather than silently truncate a write.

## First-party API

Expose a narrow People API.

Preferred shape:

- `POST /graph/people/{person_id}/roles`
  - body: `{"role": "...", "context": "..." | null}`
  - explicit first-party user mutation; no ActionPlan required.
- `DELETE /graph/people/{person_id}/roles/{role_id}`
  - semantic retract, not physical delete.

Equivalent endpoint naming is acceptable if consistent with existing People routes.

Response must expose enough typed data for the client to update without guessing:

- fact id;
- person id;
- role;
- context;
- state;
- origin.

No generic “custom relation” endpoint.

## People workspace projection

Extend `PersonPresentation` / People workspace with a bounded typed `roles` collection.

Each role item should contain at least:

- id;
- role;
- context nullable;
- origin;
- state.

Requirements:

- only active same-user role facts are projected;
- deterministic ordering;
- no N+1 query per Person: batch-load facts for the People workspace result;
- rooted Person view shows all active facts up to the explicit cap;
- overview may carry the typed data too, but REL1A does not require a broad graph-layout redesign.

The role is descriptive truth only. It is not a salience score or priority number.

## Linux/Flutter People UI

Add a small `Роли` section to rooted Person detail.

Minimum UI:

- show active roles as compact rows/chips;
- if context exists, render it clearly, for example:
  - `Директор · Arenadata`
  - equivalent compact localized presentation is acceptable;
- `Добавить роль` control;
- add dialog/form with:
  - required `Роль`;
  - optional `Контекст`;
- explicit remove/retract affordance per role;
- successful add/retract refreshes the Person detail from authoritative API state.

Do not add an organization tree.
Do not draw new Person-to-Person edges.
Do not redesign the People landscape in this slice.

## Critical semantic separation

A role fact such as `менеджер` or `директор` is **not** a Task relation.

Preserve AH2-SEM1:

- `Сделай эту задачу чьим-то менеджером` remains unsupported relation semantics;
- Person role `менеджер` must not authorize `delegated_to`, `involves`, or `related_to`;
- role facts do not grant permission or approval authority;
- role facts do not imply organization membership;
- role facts do not imply Person importance deterministically.

The future relevance model may treat confirmed roles as evidence, but never as a hard routing rule.

## Provenance/future import compatibility

REL1A must be ready for later user-supplied screenshots/documents without implementing them now.

A later slice may:

1. ingest/read a user-supplied org chart or university staff page screenshot;
2. extract names + displayed roles;
3. match only to grounded Person candidates / known identities;
4. propose role facts and unresolved Person promotions;
5. stage durable writes behind explicit user confirmation.

Therefore:

- role records need provenance fields now;
- `source_object_id` must be possible;
- REL1A UI-manual facts should use a clear provenance such as `user_manual`;
- do not implement OCR/image parsing, screenshot matching, bulk import, or agent writes in REL1A.

## Explicit non-goals

Do not in REL1A:

- change proactive review or Inbox importance;
- add role weight, numeric importance, ranking tiers, or hard-coded priority;
- change Person salience;
- add Organization objects;
- add organization membership;
- add Person-to-Person hierarchy/social relations;
- infer roles from email signatures, titles, message frequency, salience, tasks, domains, or provider profile;
- let the Assistant create/edit roles;
- expose role mutation through MCP;
- parse screenshots/documents;
- auto-create People from role text;
- change Task actor roles;
- change AH2 Person name-variant logic;
- deploy production;
- migrate production;
- rebuild/install the client for the user;
- make real model/provider calls.

## Required deterministic tests

At minimum prove:

1. **0053 schema**
   - upgrade `0052 -> 0053`;
   - expected table/constraints/indexes exist;
   - downgrade on disposable DB restores `0052`;
   - existing Person/identity/Task rows survive round-trip.

2. **basic add**
   - current-user Person + `Директор` creates one active role fact.

3. **multiple roles**
   - same Person may have `Директор` and `Научный руководитель`.

4. **optional context**
   - `Директор / Arenadata` persists and projects both values.

5. **normalized idempotence**
   - whitespace/case variants of the same role/context do not create a second active fact.

6. **same role, different contexts**
   - both active facts are allowed.

7. **empty/oversize fail closed**
   - blank role, oversize role/context rejected.

8. **active cap**
   - up to cap succeeds;
   - next distinct active fact rejected;
   - retraction frees capacity.

9. **retract**
   - retract removes fact from active projection but preserves DB history;
   - second retract is safe/idempotent.

10. **cross-user isolation**
    - cannot read/add/retract a role on another user's Person.

11. **non-Person isolation**
    - Task/email/file id cannot receive a Person role.

12. **workspace projection**
    - rooted Person payload contains active roles;
    - retracted roles absent;
    - deterministic ordering;
    - no role produces a graph Edge.

13. **identity safety**
    - role add/retract changes no PersonIdentity or PersonIdentityEvidence row.

14. **Task semantics**
    - role add/retract changes no Task actor/dependency edge;
    - SEM1 relation-boundary tests stay green.

15. **client model/API**
    - typed role parsing;
    - add request;
    - retract request;
    - authoritative refresh.

16. **client UI**
    - role section renders;
    - context renders;
    - add form validates required role;
    - retract removes it after successful API refresh;
    - ordinary Person detail without roles remains clean.

17. **existing People regressions**
    - identity correction/bind email;
    - promotions;
    - rooted truth surface;
    - Person consolidation/merge behavior where relevant.

## Required checks

Run at least:

Backend:

- new role service/API tests;
- migration 0053 focused round-trip tests;
- `backend/tests/test_person_graph_workspace.py`;
- `backend/tests/test_person_identity.py`;
- `backend/tests/test_person_identity_review.py`;
- `backend/tests/test_person_promotion.py`;
- `backend/tests/test_person_consolidation.py`;
- `backend/tests/test_ah2_sem1_relation_boundary.py`;
- focused Task relation regressions.

Client:

- focused People workspace screen/model/API tests;
- existing Person identity/promotion/truth-surface tests touched by the projection;
- focused `flutter analyze` on changed files;
- Linux debug build.

Also:

- Ruff/format where applicable;
- `git diff --check`.

Record exact pass/fail counts and identify only genuinely pre-existing failures.

## Expected source boundary

Likely files include:

- `backend/alembic/versions/0053_person_role_facts.py`;
- `backend/app/db/models.py`;
- new role domain/service module;
- `backend/app/api/schemas.py`;
- `backend/app/api/routes/graph_workspace.py`;
- `backend/app/services/person_graph_workspace_service.py`;
- focused backend tests;
- `client/lib/api/api_models.dart`;
- `client/lib/api/secretary_api_client.dart`;
- People UI inside current Graph/People surface;
- focused Flutter tests;
- ledger files.

Do not broaden beyond this without a failing contract that requires it.

## Planned next slice after REL1A — NOT AUTHORIZED YET

REL1B will connect these **confirmed role facts** to personal relevance / proactive attention evidence.

Target later behavior:

- resolve source participants to known Persons through exact identities;
- expose bounded confirmed Person roles as DATA/evidence;
- include whether the sender maps to a known Person and their active Task context;
- let the LLM weigh role together with message content, Task state, deadlines, waiting relationships, labels, participation, and other evidence;
- roles must never become deterministic priority weights;
- absence of a Person/role is weak/unknown evidence, not an automatic “unimportant” judgment.

A later separate slice may add screenshot/document role extraction + proposal workflow.

## Completion protocol

After implementation:

1. append a compact factual REL1A result to `PROJECT_STATE.md`, including the user product intent:
   - Person roles are an importance-evidence dimension, not an org hierarchy;
   - importance integration is deferred to REL1B;
2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - migration SHA/revision details;
   - exact persistence contract;
   - API/UI behavior;
   - exact test counts;
   - any genuine baseline failures;
   - confirmation that proactive/salience/Assistant/MCP were untouched;
   - production remains `2314bf72101fbd83d50a7b264154d73740e28db1`, Alembic `0052 / 0052`;
   - no deploy/migration/client install/model/provider call;
3. commit + push to `main`;
4. STOP.

Do not start REL1B, screenshot import, Organization, Scheduled Activity, deployment, migration rollout, or client installation from HOLD.
