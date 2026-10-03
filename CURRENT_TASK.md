# CURRENT_TASK

## Status

ACTIVE

## REL1D-B — deterministic grounding-only batch proposal

REL1D-A is **ARCHITECT SOURCE-ACCEPTED**.

Accepted baseline:

- REL1D-A extraction: `d1d4708d7e491131d81ced19de4495bef0c0ddc5`
- REL1D-A.1 audit/accounting corrective: `b596967aefac1f1db093ea01ec67561c578a1a3c`
- REL1D-A.1.1 durable-audit test isolation: `8cba2b58dcbad3b7a3625fd1a6303a7ece140bbc`
- Executor HOLD: `f925fd5a7b5c32bbe5a5d7048e4e8153768acb3d`
- Architect acceptance ledger: `b3f302f5b8047f4b9ef2af68ac861fd3bb5c5b3d`
- schema head: `0054`
- production backend/source: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- installed Linux client source: same exact SHA
- production Alembic: `0054 / 0054`

This task adds **deterministic grounding only** for the proposal returned by REL1D-A.

It must not persist Person, identity, RoleTerm, role assignment, ActionPlan, graph edge, label, Task, notification, or Organization facts.

No model/provider call is authorized in REL1D-B.

REL1D-C will later add explicit batch choice/approval/persistence after B is source-reviewed.

## Product goal

Given the exact REL1D-A extraction proposal:

- source object;
- source revision;
- up to 32 extracted rows of:
  - visible Person name;
  - displayed role;
  - optional context;
  - evidence text;
  - optional source locator;

produce a bounded server-grounded batch preview that answers, for each row:

1. Does this extracted name resolve safely to an existing Person?
2. If not, are there one or more separately grounded Person-promotion candidates from existing direct-contact evidence?
3. Does the extracted role exactly match an existing RoleTerm?
4. If not, what lexical vocabulary suggestions exist while still preserving the exact requested role as a potential new term?
5. Is the proposal still tied to the exact unchanged source revision?

The result is still a draft.

The UI must continue to say:

**Ничего не сохранено**

and must not expose a save/approve/persist action in this slice.

## Core invariants

Do not weaken PER1 or REL1.

### Person

- Existing Person resolution must reuse the human-accepted `PersonAssistantService.resolve()` semantics.
- An exact/accepted resolver result may resolve to one Person.
- Ambiguous remains ambiguous.
- PER1 name variants remain suggestion-only/ambiguous.
- Salience may order legacy resolver candidates internally, but REL1D-B must not auto-select an ambiguous Person by salience.
- No edit distance.
- No embeddings.
- No transliteration.
- No phonetic matching.
- No LLM identity decision.
- No identity attach/merge/create.

### Role

- Exact RoleTerm identity remains REL1A:
  - trim;
  - collapse Unicode whitespace;
  - Unicode casefold.
- Exact existing term is reuse-first.
- Semantic near-duplicates remain separate.
- Suggestions are suggestions only.
- No synonym auto-merge.
- No role hierarchy.
- No role ranking/importance.

### Promotion

A Person-promotion suggestion is not a Person.

It may be shown only when it is independently grounded in existing stored direct-contact evidence under the existing `PersonPromotionService` eligibility rules.

The screenshot/document itself is not enough to create or promote a Person.

No promotion write occurs in B.

## Part 1 — grounding endpoint

Add a focused endpoint, preferred:

`POST /people/role-import/ground`

Exact route name may vary if consistent.

### Strict request

Request fields:

- `source_object_id: UUID`
- `source_revision: str`
- `items: list[RoleImportGroundInputItem]`

No incoming:

- `person_id`
- `role_term_id`
- assignment id
- promotion identity tuple
- ActionPlan id
- “selected candidate” field

The server computes all ids itself.

### Input item

Same bounded factual shape as D-A:

- `person_name: str`
- `role: str`
- `context: str | None`
- `evidence_text: str`
- `source_locator: str | None`

Use the same max lengths and normalization rules as D-A.

Cap input at 32 rows.

Zero rows is allowed and returns an empty grounded proposal.

Extra properties forbidden.

## Part 2 — source revision revalidation

Before any grounding:

1. reload the source through the existing `PersonRoleImportSourceService`;
2. recompute/read the current exact extraction input revision using the D-A rules;
3. compare it to request `source_revision`.

If it differs:

- fail with a typed conflict/validation error;
- do not return stale Person/Role grounding;
- do not call any model/provider;
- do not mutate data.

Preferred typed code/message equivalent to:

`role_import_source_changed`

The client must interpret this as:

**Источник изменился — извлеките роли заново**

and clear stale grounding state.

Do not trust client metadata to establish source freshness.

## Part 3 — Person grounding

For each distinct extracted `person_name`:

- use existing `PersonAssistantService.resolve(name)`;
- do not create a second resolver;
- do not reinterpret salience as authority.

Memoize repeated identical normalized display queries within the request so the same name is not resolved repeatedly.

### Person result states

Return exactly one of:

- `resolved`
- `ambiguous`
- `promotion_candidates`
- `unresolved`

### resolved

Only when existing resolver returns `state=resolved`.

Expose:

- `person_id`
- `title`
- bounded resolver reasons

Do not expose salience score/tier.

### ambiguous

When resolver returns candidates but no resolved Person.

Expose at most existing resolver cap:

- `person_id`
- `title`
- reasons

Sort the REL1D output neutrally:

- title casefold;
- Person UUID tie-break.

Do not expose salience values.

Do not choose one.

### unresolved

When existing resolver returns none and there is no eligible exact-display promotion evidence.

No Person id.

### promotion_candidates

Only when existing Person resolver returns `none`.

Promotion candidates must come from existing direct-contact evidence, not from the screenshot/document.

Add a read-only helper to `PersonPromotionService` or a small companion service that:

- reuses the existing bounded promotion hit/eligibility rules;
- scans existing eligible communication evidence once per grounding request where practical;
- excludes already-owned identities;
- excludes active promotion suppressions;
- preserves the existing repeated-direct-contact threshold;
- respects existing provider/Telegram safety;
- performs **exact display-name matching only** between extracted name and promotion candidate display label.

Exact display-name matching for this promotion bridge:

- collapse Unicode whitespace;
- Unicode casefold;
- otherwise exact string equality.

Do not use:

- `names_match` token-subset logic for promotion;
- PER1 variant families for promotion;
- fuzzy matching;
- salience;
- recency as an auto-choice.

If several eligible exact-display candidates exist:

- return all up to a cap of 3;
- sort neutrally by stable candidate key;
- do not choose one.

### Opaque promotion candidate key

Do not expose raw exact identity canonical values merely for this preview.

Return an opaque deterministic key derived from the exact identity tuple, e.g. SHA-256 over:

- provider;
- identity_type;
- realm;
- canonical_value.

Preferred output fields per promotion candidate:

- `candidate_key`
- `display_name`
- `provider`
- `direct_hit_count`
- `latest_occurred_at`

Optional bounded source-preview facts are acceptable:

- source object id;
- provider;
- title;
- occurred_at;

but do not expose raw message body or identity canonical value.

The key is not an authorization token. REL1D-C must revalidate eligibility later.

## Part 4 — RoleTerm grounding

For each distinct extracted role:

1. normalize with REL1A `role_term_identity()`;
2. batch-load exact current-user RoleTerms by normalized key where practical;
3. exact term present -> `reuse_existing`;
4. no exact term -> `propose_new`.

### reuse_existing

Expose:

- `state="reuse_existing"`
- `role_term_id`
- canonical stored `display_text`
- lexical suggestions may be omitted or shown excluding the exact term

### propose_new

Expose:

- `state="propose_new"`
- exact normalized display text derived from the extracted wording;
- `role_term_id=null`
- up to 5 bounded lexical suggestions from the existing vocabulary search.

Suggestions are advisory only.

A suggestion must never become the selected role automatically.

Example:

- existing term: `генеральный директор`
- extracted role: `директор`

Result:

- `propose_new` for `директор`;
- `генеральный директор` may appear only in suggestions;
- no semantic substitution.

Do not create a RoleTerm.

## Part 5 — grounded proposal response

Preferred response shape:

### RoleImportGroundedProposal

- `source_object_id: UUID`
- `source_revision: str`
- `source_kind: "image" | "text"`
- `source_truncated: bool`
- `items_truncated: bool`
- `grounding_revision: str`
- `items: list[RoleImportGroundedItem]`

Preserve D-A extraction order.

### RoleImportGroundedItem

Include:

- `row_index: int`
- original normalized extraction facts:
  - `person_name`
  - `role`
  - `context`
  - `evidence_text`
  - `source_locator`
- `person_resolution`
- `role_resolution`

No selected/action field.

No approval state.

### grounding_revision

Compute a deterministic SHA-256 over a canonical JSON representation of:

- source object id;
- source revision;
- normalized extraction rows;
- server-computed Person grounding;
- server-computed RoleTerm grounding.

Exclude `grounding_revision` itself.

Use stable key order and stable list ordering.

This revision is a freshness/freeze aid for REL1D-C, not a security credential.

Changing:

- source revision;
- resolved/ambiguous Person set;
- promotion candidate set;
- exact RoleTerm reuse decision;
- extracted row text/context

must change `grounding_revision`.

## Part 6 — no-write guarantee

The grounding endpoint is deterministic/read-only.

It must not mutate:

- Object;
- Edge;
- PersonIdentity;
- PersonIdentityEvidence;
- PersonPromotionFeedback;
- PersonRoleTerm;
- PersonRoleAssignment;
- PendingActionPlan;
- Notification;
- labels;
- Task relations;
- AI audit traces.

No model/provider call.

No OpenAI budget event.

No Assistant conversation/history mutation.

## Part 7 — query discipline

Input cap is 32.

Avoid accidental explosive query behavior.

At minimum:

- memoize repeated Person names;
- batch exact RoleTerm lookup by normalized keys;
- run promotion direct-contact scan at most once per request;
- cache role vocabulary suggestions per distinct missing role.

Do not issue promotion-history scans once per row.

A bounded query-count/spy test is preferred.

Do not broadly refactor PER1 resolver in this slice merely to eliminate every existing internal query.

## Part 8 — client grounding UX

Extend the existing REL1D-A preview.

### Explicit trigger

After a successful extraction proposal with at least one row, show:

**Сопоставить**

or:

**Сопоставить людей и роли**

Do not ground automatically:

- after file attach;
- after extraction;
- after Assistant send;
- on context open.

### Controller state

Maintain separate grounding state:

- idle;
- loading;
- error;
- success.

Grounding request uses exactly the current:

- source object id;
- source revision;
- extracted rows.

Changing object context or re-running extraction must clear old grounded state and invalidate in-flight grounding responses.

A late response for an older extraction/source must not overwrite the current preview.

### Grounded preview

Continue to show:

**Ничего не сохранено**

For each row display enough truth to understand the grounding.

#### resolved Person

Example:

- `Person: Ольга Володько`

#### ambiguous Person

Show:

- `Нужно выбрать Person`
- bounded candidate titles

No selection control yet.

#### promotion candidates

Show wording equivalent to:

- `Можно предложить нового Person`

and candidate display/provider/direct-contact count.

No “Создать”/approve control yet.

#### unresolved Person

Show:

- `Person не найден`

#### existing RoleTerm

Show wording equivalent to:

- `Использовать существующую роль: …`

#### new RoleTerm proposal

Show wording equivalent to:

- `Новая роль: …`

Optional lexical suggestions may appear under:

- `Похожие термины`

but must visually remain suggestions, not selected values.

### Source changed

If backend reports source revision mismatch:

- clear grounded preview;
- keep extraction preview only if useful, but mark it stale;
- show:
  - `Источник изменился — извлеките роли заново`;
- require explicit re-extraction before another valid grounding.

### No persistence controls

REL1D-B UI must have no:

- checkbox selection;
- Person candidate selection;
- RoleTerm suggestion selection;
- save;
- approve;
- “Применить”;
- ActionPlan;
- write endpoint.

Those belong to REL1D-C.

## Part 9 — security / privacy

Do not add extraction text, person names, role text, evidence, promotion identity canonical values, or grounding proposal to AI audit.

D-B makes no AI call and should produce no AI trace.

Do not expose:

- raw PersonIdentity canonical values;
- normalized RoleTerm keys;
- promotion suppression internals;
- salience scores;
- provider credentials;
- server upload path.

Source evidence text already returned by D-A may remain in the user-facing preview.

## Required deterministic backend tests

Add focused module, preferred:

`backend/tests/test_rel1d_role_import_grounding.py`

At minimum prove:

1. exact unchanged source revision grounds successfully;
2. changed image bytes/hash/revision rejects stale grounding;
3. changed stored text revision rejects stale grounding;
4. request cannot inject `person_id`, `role_term_id`, assignment ids, or selection fields;
5. unique exact/accepted Person resolver result returns `resolved`;
6. ambiguous existing People stay ambiguous;
7. PER1 name variant remains ambiguous and never auto-resolves;
8. no Person match returns unresolved when no promotion evidence exists;
9. promotion suggestion appears only from existing eligible repeated direct-contact evidence;
10. screenshot/document name alone cannot create a promotion candidate;
11. promotion display-name bridge requires exact collapsed-whitespace/casefold equality;
12. near/subset/fuzzy display names do not produce promotion suggestion;
13. two exact-display promotion identities return multiple candidates, no auto-choice;
14. promotion output hides canonical identity values;
15. suppressed/already-owned promotion identities are absent;
16. exact RoleTerm is reused;
17. case/Unicode-whitespace role variant reuses the same exact term;
18. semantic near-duplicate role remains `propose_new`;
19. lexical near term may appear only as suggestion;
20. suggestions cap <=5;
21. input order is preserved;
22. repeated same Person name is resolved once/cached;
23. promotion scan runs once per request;
24. exact role lookup is batched/cached;
25. `grounding_revision` is deterministic for same facts;
26. source/Person/Role grounding change changes `grounding_revision`;
27. endpoint leaves product row counts unchanged;
28. endpoint creates no AITrace/AITraceEvent;
29. no model/provider fake is even required/called;
30. cross-user/hidden source safety from D-A remains enforced.

Run existing:

- `test_rel1d_role_import_source.py`
- `test_rel1d_role_import_extraction.py`
- PER1/name-variant focused tests
- Person promotion focused tests
- `test_rel1a_person_roles.py`
- `test_rel1c_assistant_role_reads.py`
- `test_rel1c_assistant_role_writes.py`

All new/focused relevant tests must be 0 failed.

Known unrelated shared-DB/transcription debt must not be repaired in this slice.

## Required deterministic client tests

Extend/add focused role-import preview tests proving:

1. successful extraction shows explicit grounding button;
2. extraction does not ground automatically;
3. grounding request sends current source id + source revision + exact extracted rows;
4. resolved Person and existing role are displayed truthfully;
5. ambiguous Person candidates display with no selection;
6. promotion candidate state displays with no create action;
7. unresolved Person displays clearly;
8. proposed-new role remains new even when suggestions exist;
9. suggestions are visually advisory;
10. `Ничего не сохранено` remains visible after grounding;
11. no save/approve/apply controls exist;
12. source-revision conflict asks for re-extraction;
13. context change clears grounding;
14. re-extraction clears previous grounding;
15. late old grounding response cannot overwrite newer source/extraction state;
16. ordinary Assistant send remains unchanged.

Run focused Flutter analyze for changed Dart files.

Do not install/build production client.

## Expected production-code scope

Backend may include a bounded subset of:

- new `person_role_import_grounding_service.py`;
- existing `person_promotion_service.py` for one read-only exact-display batch helper;
- `person_promotion.py` for a deterministic opaque candidate key helper if needed;
- existing role-import route + strict schemas;
- focused tests.

Client may include:

- `role_import_models.dart`;
- `secretary_api_client.dart`;
- Assistant controller;
- role import preview panel;
- focused tests.

Do not modify:

- Alembic/schema;
- Person identity write semantics;
- Person resolver semantics;
- RoleTerm normalization;
- PersonRoleService write behavior;
- REL1B Personal Relevance;
- Proactive;
- Assistant tool registry/action plans;
- Organization ontology;
- provider/model configuration.

## Explicit non-goals — REL1D-C

Do not implement:

- user selection among ambiguous Person candidates;
- actual Person promotion;
- RoleTerm creation;
- PersonRoleAssignment writes;
- ActionPlan creation;
- batch approval;
- source provenance persistence on assignments;
- merge/alias writes;
- Organization creation;
- deploy/rollout.

## Production / external-effect boundary

Source-only.

Do not:

- move `production`;
- deploy backend;
- migrate;
- build/install/replace client;
- call OpenAI or any real provider;
- mutate production People/roles/sources.

Production/backend/client remain exact:

`6f802d6959aca40758376a83d5bdfcbbd77fc537`

Alembic remains:

`0054 / 0054`

## Expected next slice after acceptance

REL1D-C should convert a source-revalidated grounded proposal into one explicit user-controlled batch confirmation/persistence flow.

It must:

- require source revision + grounding revision freshness;
- let ambiguous Person rows be explicitly selected or skipped;
- let promotion candidates be explicitly selected or skipped;
- preserve exact RoleTerm reuse/new-term intent;
- deduplicate final Person+RoleTerm+context writes;
- stage all durable writes behind explicit confirmation;
- create promoted Person + exact identity only when explicitly selected and still eligible;
- assign roles with source provenance;
- remain atomic/fail-closed enough to avoid half-applied identity/role batches;
- show changed/no-op/skipped results truthfully.

Do not start REL1D-C automatically.

## Completion protocol

After implementation:

1. append a compact REL1D-B result to `PROJECT_STATE.md` with:
   - grounding endpoint/input;
   - source revision fence;
   - exact Person resolver reuse;
   - promotion evidence rule;
   - exact RoleTerm reuse/new semantics;
   - grounding revision;
   - no-write/no-AI guarantee;
   - client grounding UX;
   - exact test counts;

2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - schema still `0054`;
   - exact green test counts;
   - production/client still `6f802d...`;
   - no deploy/migration/client install/model/provider/product-data action;
   - REL1D-C not started;

3. commit + push to `main`;

4. STOP.

Do not start REL1D-C from HOLD.
