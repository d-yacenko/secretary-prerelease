# Current task — ACTIVE

## REL1A — emergent Person role vocabulary + manual assignments

This task supersedes the earlier paused REL1A draft. Execute only this version.

User product direction, 2026-10-03:

- Person roles are useful primarily as future evidence for Secretary attention/importance reasoning;
- the role vocabulary must NOT be a closed predefined dictionary;
- roles should behave like an emergent keyword/tag vocabulary;
- existing terms should be suggested and reused first;
- a genuinely new role must still be creatable on demand;
- trivial lexical duplicates must collapse deterministically;
- semantic near-duplicates must NOT be silently merged;
- Organization hierarchy, social hierarchy, proactive ranking, and screenshot import are later work.

Examples of valid emergent role terms include:

- `директор`
- `студент`
- `заведующий кафедрой`
- `научный руководитель`
- `главный бухгалтер`
- `оппонент`

The system must not need code changes when a new real-world role appears.

## Accepted baseline

- Main before this authorization: `79707126d69129975be16b25e5e510838276adf9`
- Production backend: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Installed Linux client source: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Production Alembic: `0052 / 0052`
- Production health: PASS
- AH2 remediation/client human gate: accepted

Current Person truth already includes canonical Person objects, exact identities/evidence, promotion, salience, Task actor roles, routes, and identity-grounded communications.

There is currently no canonical durable vocabulary for roles of OTHER Persons.

Do not conflate this with the user's own roles from `UserIdentityProfile` / personal-relevance user context. REL1A is about roles assigned to Person objects in the user's People graph.

## Canonical model

REL1A has two separate concepts.

### 1. RoleTerm

A user-scoped canonical vocabulary term, created incrementally through use.

Examples:

- `директор`
- `студент`
- `заведующий кафедрой`

RoleTerm is NOT:

- an enum;
- a hard-coded application dictionary;
- an Organization;
- a Person-to-Person edge;
- a Task actor role;
- a numeric priority/importance class.

### 2. PersonRoleAssignment

A durable fact:

> this Person has this RoleTerm, optionally in this short context.

Examples:

- `Иван Иванов -> директор -> Arenadata`
- `Пётр Петров -> студент -> МГУ`
- `Анна Сидорова -> директор -> [no context]`

One Person may have several assignments.

The same RoleTerm may be assigned to many Persons.

The same Person may hold the same RoleTerm in different contexts.

## Schema — additive Alembic 0053

Create revision `0053` from `0052`.

Preferred tables:

### `person_role_terms`

Minimum fields:

- `id` UUID PK;
- `user_id` FK users;
- `display_text` required;
- `normalized_key` required;
- `created_at`;
- `updated_at`.

Required invariant:

- unique `(user_id, normalized_key)`.

REL1A has no standalone role-term delete/retire UI. Terms are vocabulary and remain reusable even if all current assignments are later retracted. Do not add role administration CRUD just to manage the dictionary.

### `person_role_assignments`

Minimum fields:

- `id` UUID PK;
- `user_id` FK users;
- `person_object_id` FK objects;
- `role_term_id` FK person_role_terms;
- `context_text` nullable;
- `context_key` required; empty string when context absent;
- `origin` required;
- `state` = `active|retracted`;
- `provenance_kind` required;
- `provenance_key` required;
- `source_object_id` nullable FK objects;
- `created_at`;
- `updated_at`;
- `retracted_at` nullable.

Required active uniqueness:

- at most one active `(user_id, person_object_id, role_term_id, context_key)`.

Manual UI assignments use:

- `origin=user`;
- a clear provenance kind/key such as `user_manual`.

Keep `source_object_id` available for later grounded screenshot/document imports, but REL1A does not implement those imports.

## Lexical normalization

Normalization is for exact lexical identity only.

For both RoleTerm text and assignment context key:

- trim outer whitespace;
- collapse internal Unicode whitespace runs to one ordinary space;
- Unicode-aware case-fold for the normalized key;
- preserve the first accepted human-readable display text separately.

Bounds:

- role display text: 1..120 chars after trim/collapse;
- context display text: 0..200 chars after trim/collapse.

These MUST collapse to the same RoleTerm:

- `Директор`
- ` директор `
- `ДИРЕКТОР`

These MUST NOT be auto-merged:

- `директор`
- `генеральный директор`
- `директор компании`
- `директор организации`

Do not:

- stem;
- translate;
- use embeddings;
- use edit distance for identity;
- use LLM synonym decisions;
- infer hierarchy;
- silently alias semantic near-duplicates.

If the exact normalized term already exists, always reuse it.

## Vocabulary UX — reuse first, creation still open

The manual Role field behaves like tags/keywords.

When the user types:

- show bounded existing RoleTerms matching the typed text;
- encourage selecting an existing RoleTerm;
- if no desired existing term applies, offer an explicit action:
  - `Создать роль «<typed text>»`
  - equivalent localized wording is acceptable.

Do not require a separate “manage roles” screen.

Autocomplete matching may be lexical prefix/substring matching only. It must be user-scoped, bounded, deterministic, and must not claim semantic equivalence.

If the typed text normalizes exactly to an existing term, the UI/backend must reuse it rather than creating a duplicate.

## Backend service contract

Add a focused Person-role vocabulary/assignment service.

Required behavior:

- role terms are per-user;
- Person target must be active, current-user, `kind=person`;
- cross-user ids fail closed;
- non-Person ids fail closed;
- rejected/deleted Persons fail closed;
- assigning an existing normalized RoleTerm reuses it;
- assigning a new lexical term creates one RoleTerm atomically with the assignment;
- if assignment creation fails, do not leave an orphan RoleTerm from that failed transaction;
- duplicate active assignment is idempotent;
- retract is idempotent and preserves history;
- listing assignments returns active rows by default;
- role vocabulary search is bounded and user-isolated;
- no graph Edge is created;
- no PersonIdentity/PersonIdentityEvidence/PersonPromotion data changes;
- no Task actor/dependency relation changes;
- no salience/proactive value changes.

Preferred active assignment cap per Person: 16. Reject the next distinct active assignment rather than silently dropping/truncating a write. A retracted assignment frees capacity.

## First-party API

Use narrow People APIs. Preferred shapes:

### Role vocabulary search

`GET /graph/person-role-terms?q=<text>&limit=<bounded>`

Returns typed existing terms:

- `id`;
- `display_text`.

Requirements:

- current user only;
- deterministic order;
- bounded limit;
- no fuzzy/semantic matching;
- empty query may return a small deterministic reusable vocabulary page.

Equivalent endpoint naming is acceptable if consistent with existing graph API conventions.

### Assign role to Person

`POST /graph/people/{person_id}/roles`

Preferred body:

```json
{
  "role": "Директор",
  "context": "Arenadata"
}
```

Backend normalizes the role, reuses an exact existing RoleTerm or creates a new one, then creates/reuses the active assignment atomically.

Response exposes at least:

- assignment id;
- person id;
- role_term_id;
- role display text;
- context;
- origin;
- state.

### Retract assignment

`DELETE /graph/people/{person_id}/roles/{assignment_id}`

This is semantic retract, not physical delete.

No standalone RoleTerm creation/delete API is required in REL1A. RoleTerm creation occurs only as part of assigning a genuinely new role.

## People workspace projection

Extend typed `PersonPresentation` with bounded active role assignments.

Each projected item must expose:

- assignment id;
- role_term_id;
- role display text;
- context nullable;
- origin;
- state.

Requirements:

- current-user active facts only;
- deterministic ordering;
- no N+1 query per Person: batch-load assignment + term data for People workspace;
- rooted Person detail receives the full bounded active set;
- overview/card projection may use the same bounded typed data;
- retracted assignments are absent.

Role assignments are descriptive facts, not graph edges.

## Flutter/Linux UI

Implement manual use inside the existing People surface.

### Rooted Person detail

Add a `Роли` section:

- show active assignments;
- render context compactly when present, e.g. `Директор · Arenadata`;
- allow multiple roles;
- `Добавить роль`;
- explicit retract/remove affordance per assignment.

### Add role flow

Role input must be autocomplete/reuse-first:

- as user types, query/show existing RoleTerms;
- selecting a suggestion uses the existing term;
- typed text that is not the desired existing term can be created by explicit `Создать роль …`;
- optional `Контекст` field;
- do not force context;
- do not create Organization objects.

After successful assign/retract, refresh from authoritative People workspace state.

### People graph/card visibility

Without changing graph topology or edges, show a compact role summary on the Person presentation where the current People card design permits it.

Minimum required presentation:

- rooted Person detail shows all active roles;
- Person card/overview shows at least the first 1–2 distinct role terms when available, with an overflow cue if necessary.

Do not redesign layout/world positioning in REL1A. If compact card roles cause a layout regression, keep the required truth in detail and use the smallest non-topological card treatment possible.

## Important semantic boundaries

### Role is not hierarchy

A role string `директор` does not create:

- `manager_of`;
- `colleague`;
- `member_of`;
- `role_at`;
- any Person-to-Person relation.

### Role is not Task actor semantics

Preserve AH2-SEM1.

A Person role `менеджер` or `директор` must never be mapped to:

- `delegated_to`;
- `involves`;
- `requested_by`;
- `waiting_on`;
- `related_to`.

### Role is not authority or priority

REL1A does not assign:

- priority scores;
- importance weights;
- rank tiers;
- notification authority;
- approval authority.

A future LLM may use confirmed roles as one evidence dimension together with message content, Task state, deadlines, waiting relations, participation, labels, and other facts.

Absence of a known Person or role must never mean “unimportant”.

## Future-agent reuse rule — design compatibility only

REL1A does NOT add Assistant role-write tools.

But the data/API design must support the later REL1C policy:

- agent first sees/searches existing RoleTerms;
- agent prefers reuse when an existing term actually matches;
- if source says `Генеральный директор` and vocabulary only has `директор`, agent must not silently collapse them;
- it may propose using existing `директор` or creating new `генеральный директор`;
- durable assignment remains explicit/confirmed.

Do not implement this model behavior now.

## Future screenshot/document import compatibility

REL1A must support later REL1D use cases such as:

- company org-chart screenshot;
- university department staff page/screenshot;
- other user-supplied authoritative visual/document.

Later flow may:

1. extract Person names + displayed roles;
2. resolve grounded known Persons;
3. search/reuse existing RoleTerms;
4. propose new terms only where needed;
5. propose Person promotion for grounded identities not yet in People graph;
6. write assignments only after explicit user confirmation;
7. retain source provenance via `source_object_id`.

REL1A must not implement OCR/image parsing/import itself.

## Explicit non-goals

Do not in REL1A:

- change PersonalRelevanceEvidence;
- change ProactiveReviewService or proactive instructions;
- change Inbox importance/ranking;
- add hard-coded role weights;
- add LLM/Assistant role reads or writes;
- expose role mutation through MCP;
- parse screenshots/documents;
- create Organization objects;
- add org membership;
- add social/hierarchy graph edges;
- add standalone role-dictionary management UI;
- add semantic synonym merge;
- change Person name-variant matching;
- change Task relation ontology;
- change Scheduled Activity;
- deploy production;
- migrate production;
- rebuild/install the user's client;
- make real model/provider calls.

## Required deterministic tests

At minimum prove:

1. **0053 migration**
   - `0052 -> 0053`;
   - both new tables/constraints/indexes exist;
   - downgrade restores `0052`;
   - disposable round-trip preserves existing Person/identity/Task data.

2. **RoleTerm exact normalization**
   - `Директор`, ` директор `, `ДИРЕКТОР` reuse one term;
   - preserved display text is deterministic;
   - no duplicate normalized key per user.

3. **Near-duplicates remain distinct**
   - `директор` and `генеральный директор` create distinct terms;
   - no fuzzy/synonym auto-merge.

4. **Per-user vocabulary isolation**
   - same normalized term may exist independently for two users;
   - search never leaks another user's terms.

5. **Assignment basic**
   - assign existing term to Person;
   - assign new term atomically creates term + assignment.

6. **Multiple roles**
   - one Person can hold several active role terms.

7. **Context**
   - same role without context and with `Arenadata` are distinct assignments;
   - same role with two different contexts is allowed;
   - context case/whitespace exact normalization prevents trivial duplicate assignment only.

8. **Idempotence**
   - repeat same normalized role/context does not create a second active assignment.

9. **Bounds**
   - blank/oversize role rejected;
   - oversize context rejected;
   - assignment cap enforced;
   - retraction frees capacity.

10. **Retract/history**
    - retract removes assignment from active projection;
    - row/history remains;
    - second retract safe/idempotent;
    - RoleTerm remains reusable after last assignment retracts.

11. **Person safety**
    - cross-user, Task/email/file, rejected/deleted Person fail closed.

12. **No side effects**
    - no Edge created;
    - no PersonIdentity/IdentityEvidence/Promotion mutation;
    - no Task actor/dependency mutation;
    - no salience/proactive changes.

13. **Vocabulary search**
    - lexical user-scoped bounded search;
    - deterministic output;
    - no semantic/fuzzy promise.

14. **Workspace projection**
    - active roles projected;
    - retracted roles absent;
    - deterministic ordering;
    - no N+1 query regression if the test harness can assert query shape/count.

15. **Client API/model**
    - RoleTerm suggestion parsing;
    - Person role assignment parsing;
    - search;
    - assign;
    - retract;
    - authoritative refresh.

16. **Client UX**
    - existing term suggestion selectable;
    - explicit create-new action available for genuinely new text;
    - exact lexical duplicate does not create a second term;
    - optional context;
    - multiple roles render;
    - retract refreshes;
    - Person with no roles remains clean;
    - compact Person card role summary does not expose raw ids.

17. **Regression**
    - Person identity correction/email bind;
    - promotion;
    - merge/consolidation;
    - People truth surface;
    - AH2-SEM1 relation boundary;
    - Task relation core.

## Required checks

Backend:

- new role vocabulary/assignment tests;
- migration 0053 disposable upgrade/downgrade/round-trip;
- `backend/tests/test_person_graph_workspace.py`;
- `backend/tests/test_person_identity.py`;
- `backend/tests/test_person_identity_review.py`;
- `backend/tests/test_person_promotion.py`;
- `backend/tests/test_person_consolidation.py`;
- `backend/tests/test_ah2_sem1_relation_boundary.py`;
- focused Task relation regressions.

Client:

- focused People workspace/model/API tests;
- identity/promotion/truth-surface tests affected by PersonPresentation;
- focused `flutter analyze` on changed files;
- `flutter build linux --debug`.

Also:

- Ruff/format where applicable;
- `git diff --check`.

Record exact pass/fail counts. Do not hide genuine pre-existing failures; identify them precisely.

## Planned next slices — NOT AUTHORIZED

### REL1B — role-aware personal relevance / importance evidence

Feed bounded confirmed Person identity + active role assignments + relevant active Task context into personal-relevance/proactive evidence.

Important future rules:

- role is evidence, not a deterministic score;
- message content still matters;
- active Task/waiting/deadline context still matters;
- unknown sender can still be important;
- absence of role is unknown/weak evidence, not “low priority”.

Target behavior includes comparing a plain but consequential message from a known role-bearing Person against noisy “urgent” wording from an unrelated sender without hard-coded `director=+N` weights.

### REL1C — Assistant role read/write

Secretary can inspect roles and propose assignments/reuse/new terms through approval-safe semantics.

### REL1D — grounded screenshot/document role import

User-supplied org charts/staff pages can produce grounded Person/RoleTerm proposals with provenance and explicit confirmation.

Organization ontology remains separate and later.

## Completion protocol

After implementation:

1. update `PROJECT_STATE.md` with:
   - product intent: emergent reusable Person role vocabulary, not closed dictionary/hierarchy;
   - exact schema/model;
   - exact normalization/idempotence rules;
   - UI reuse-first/create-new behavior;
   - exact test/build evidence;
2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - migration revision and disposable migration evidence;
   - exact API/UI behavior;
   - test counts;
   - genuine baseline failures if any;
   - explicit confirmation that PersonalRelevance/Proactive/Assistant/MCP were untouched;
   - production remains `2314bf72101fbd83d50a7b264154d73740e28db1`;
   - production Alembic remains `0052 / 0052`;
   - no production deploy/migration/client install/model/provider call;
3. commit + push to `main`;
4. STOP.

Do not start REL1B, REL1C, REL1D, Organization, Scheduled Activity, deployment, migration rollout, or client installation from HOLD.
