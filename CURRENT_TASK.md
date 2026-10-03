# Current task — ACTIVE

## REL1B-A — grounded known-Person role evidence in Personal Relevance snapshots

REL1A is **HUMAN-ACCEPTED**.

Exact deployed baseline:

- production backend/source: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- production branch: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- installed Linux client source: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- Alembic: `0054 / 0054`

The user completed the REL1A manual gate successfully.

This task starts REL1B with a read-only evidence slice only.

Do not deploy, migrate, install the client, call a real model/provider, or start REL1B-B / REL1C / REL1D.

## Architecture intent

Person roles are one bounded evidence dimension for personal relevance.

They are NOT:

- deterministic priority weights;
- authority/permission;
- social hierarchy;
- Organization membership;
- Task actor roles;
- graph edges;
- proof that an unknown/unrecorded Person is unimportant.

Missing Person/role evidence means unknown/unavailable evidence, never negative evidence.

This slice only makes exact-grounded Person-role facts available inside the canonical Personal Relevance snapshot.

It deliberately does **not yet expose those new fields to the Proactive LLM seed context**. The next REL1B-B slice will add active Task context plus explicit Proactive consumption/instructions and adversarial judgment tests after this factual read layer is source-reviewed.

## Current Personal Relevance baseline

Current evidence version is `1`.

Each object currently carries bounded factual data such as:

- object kind/provider/origin/state/status/title/timestamps;
- current-user participation roles;
- assigned labels;
- truncation flags.

It does not carry grounded known-Person participants or their REL1A role assignments.

Current Proactive behavior must remain semantically unchanged in this task.

## Required evidence version

Bump:

`PERSONAL_RELEVANCE_EVIDENCE_VERSION = 2`

The version bump is required because object evidence signatures gain new factual dimensions.

Existing stale-fence/signature machinery must naturally treat relevant Person/role changes as evidence changes.

## Required typed evidence shape

Add a small typed provider-neutral representation in `backend/app/personal_relevance/models.py`.

Exact class names may vary, but the payload semantics must be equivalent to:

### PersonRoleEvidence

Fields:

- `role_term_id: UUID`
- `role: str` — canonical RoleTerm display text
- `context: str | None`

Do not expose:

- normalized lexical keys;
- provenance internals;
- raw source identity values;
- hidden priority/weight fields.

### KnownPersonEvidence

Fields:

- `person_id: UUID`
- `display_name: str`
- `source_roles: tuple[str, ...]`
- `roles: tuple[PersonRoleEvidence, ...]`
- `roles_truncated: bool`

### ObjectPersonalRelevanceEvidence additions

Add:

- `known_people: tuple[KnownPersonEvidence, ...]`
- `known_people_truncated: bool`

These fields must be included in the canonical object evidence payload/signature.

## Boundedness

Add explicit constants:

- `PERSONAL_RELEVANCE_MAX_KNOWN_PEOPLE_PER_OBJECT = 8`
- `PERSONAL_RELEVANCE_MAX_ROLES_PER_KNOWN_PERSON = 8`

If more exact-known participants or active roles exist:

- keep a deterministic bounded prefix;
- set the appropriate truncation flag;
- never interpret truncation as negative evidence.

The existing REL1A active-role cap remains 16 and is unchanged.

## Exact source-role vocabulary

Use this factual source-position vocabulary only:

- `sender`
- `recipient`
- `copied_recipient`
- `organizer`
- `attendee`
- `author`
- `mentioned`
- `conversation_peer`

This describes where the known Person appears in the source object.

It is not relationship judgment and must never be converted into `responsible/observer/etc.` by deterministic code.

A Person may have several source roles on one object; serialize each role at most once in the fixed vocabulary order above.

## Grounding rule — exact identities only

A known Person may enter this evidence only through an existing exact active `PersonIdentity` owned by the current user.

Do not use:

- display-name equality alone;
- PER1 name variants;
- fuzzy matching;
- embeddings;
- edit distance;
- transliteration;
- Person promotion candidates;
- salience score;
- message frequency;
- role text similarity;
- LLM inference.

PersonIdentity matching must preserve the existing provider-specific canonical identity semantics already used by the repository.

Where provider canonicalization already exists, reuse it rather than inventing a second incompatible identity rule.

At minimum support factual exact participant extraction for the currently supported source families:

### Email — Gmail / Yandex Mail

Ground exact known Persons from:

- sender/from -> `sender`
- direct recipients/to -> `recipient`
- cc -> `copied_recipient`

Use canonical exact email identity only.

### Calendar — Google Calendar / Yandex Calendar

Ground exact known Persons from:

- organizer -> `organizer`
- attendees -> `attendee`

Use exact attendee/organizer email identities only.

Do not infer a Person from display name when email identity is absent.

### Mattermost

Ground only through existing exact server-realm identity forms:

- author id/username -> `author`
- bounded explicit mentions, where an exact known identity can be proven -> `mentioned`

Preserve existing Mattermost server URL canonicalization/security behavior.

### Telegram

Use only exact Telegram identity forms already canonical in the repository.

For MTProto:

- inbound sender -> `sender`
- outbound private peer -> `conversation_peer`
- inbound public/group author may be `sender` when exact identity is available.

Do not match display names/usernames unless that identity type is already canonical and active.

### Teams

Use the existing exact Microsoft/tenant identity semantics.

- exact inbound sender -> `sender`

Do not weaken GUID/tenant canonicalization.

Unsupported/insufficient provider metadata simply yields no known Person evidence.

## Active Person safety

Matched Person evidence is allowed only when the Person object is:

- owned by the current user;
- kind `person`;
- not rejected;
- not deleted/tombstoned/merged-away;
- visible under the same active-read rules used by REL1A.

An exact identity pointing to a hidden/inactive Person must not leak that Person into Personal Relevance evidence.

Cross-user Person/identity/role rows must never leak.

## Role evidence rule

For each exact-grounded active Person:

- include only active `PersonRoleAssignment` rows;
- join only current-user `PersonRoleTerm` rows;
- use the stored canonical display text;
- preserve optional context exactly as REL1A stores/displays it;
- semantic near-duplicate RoleTerms remain separate;
- retracted assignments are absent;
- role evidence order must be deterministic;
- truncate only at the explicit relevance evidence cap.

Prefer reusing `PersonRoleService.active_for_people()` or the same exact query semantics rather than creating a divergent definition of “active role”.

No role assignment may be created, changed, retracted, or normalized by this read path.

## Object/person de-duplication

Within one object:

- the same Person appears once even if several exact identities/positions resolve to them;
- union the factual `source_roles`;
- one Person with several active role assignments keeps those distinct assignments;
- do not merge semantic near-duplicate RoleTerms.

Known-person ordering must be deterministic and must not encode importance.

Use a neutral stable order, preferably Person UUID, after all exact matches are deduplicated.

## Query discipline

`build_snapshot()` may cover up to the existing bounded object cap.

Do not introduce per-object or per-Person N+1 database queries.

Preferred shape:

1. mechanically extract bounded exact identity keys/positions for all owned snapshot objects;
2. one bounded identity lookup for those keys;
3. one bounded active-Person read for matched ids;
4. one batched active-role read for matched People;
5. assemble object evidence in memory.

Equivalent bounded batching is acceptable.

Add a deterministic query-count or spy-style regression if practical enough to prove roles are not loaded once per object/person.

## Signature / stale-fence requirements

Because known Person-role evidence is part of the object canonical payload:

- adding an active role to a Person who is an exact participant of source object X must change X's object evidence signature;
- retracting that active role must change X's signature;
- changing/adding a role for an unrelated Person who is not a participant of X must NOT change X's object evidence signature;
- participant grounding changes must affect only the corresponding object evidence.

Existing `personal_relevance_evidence_is_stale()` should continue to work from version/signature comparisons; do not add an ad-hoc second stale mechanism.

## Proactive behavior boundary for B-A

This is critical.

Do NOT yet feed `known_people` / role facts into the Proactive LLM UI/seed context.

`seed_context_from_evidence()` must continue to expose the existing semantic input fields only.

It is acceptable/required that:

- `evidence_version` becomes 2;
- internal object evidence signatures now cover known Person-role facts.

But the Proactive provider must not receive the new `known_people` structure in this slice.

Do not change:

- `PROACTIVE_SYSTEM_INSTRUCTIONS`;
- Proactive read-tool allowlist;
- `ProactiveDecision` schema;
- notification thresholds/gates;
- default NONE/silence behavior;
- PersonalRelationship / PersonalDependency enums.

No real model calls.

## Explicitly do not use Person salience as role evidence

Existing Person salience is a separate derived read model.

Do not:

- copy its score/tier into Personal Relevance;
- use salience to select which exact-known Person survives the cap;
- let salience create/infer a role;
- convert communication frequency into a role or importance weight.

You may reuse safe exact provider identity canonicalization helpers where appropriate, but not salience ranking semantics.

## Required deterministic tests

Add focused REL1B-A tests, preferably in a new module such as:

`backend/tests/test_rel1b_person_role_relevance_evidence.py`

At minimum prove:

1. **evidence version**
   - version is exactly 2.

2. **exact email sender grounding**
   - exact current-user PersonIdentity for sender resolves one Person;
   - active role + context appear in snapshot;
   - raw sender email is not duplicated inside known-person role evidence.

3. **unknown sender**
   - no exact PersonIdentity -> `known_people=[]`;
   - no fallback name/fuzzy/role inference.

4. **calendar participant grounding**
   - exact organizer/attendee email can resolve a known Person;
   - source role is factual organizer/attendee.

5. **chat grounding**
   - at least one Mattermost exact author case;
   - Telegram MTProto exact counterpart case;
   - Teams exact sender case;
   - provider realm/canonicalization safety remains intact.

6. **dedupe**
   - multiple exact identity/source positions for the same Person produce one Person record with unioned source roles.

7. **active Person safety**
   - rejected/deleted/merged-away Person does not appear;
   - cross-user Person does not appear.

8. **active roles only**
   - active role appears;
   - retracted role does not;
   - role context is preserved;
   - semantic near-duplicate RoleTerms remain separate.

9. **role bound**
   - more than 8 active roles yields exactly 8 + `roles_truncated=true`;
   - ordering is deterministic.

10. **known-Person bound**
    - more than 8 exact known participants yields exactly 8 + `known_people_truncated=true`;
    - selection/order is deterministic and not salience-ranked.

11. **signature changes**
    - relevant participant role add/retract changes that source object's evidence signature;
    - unrelated Person role mutation does not change it.

12. **existing relevance evidence remains**
    - labels;
    - current-user participation;
    - title/timestamps;
    - existing truncation behavior.

13. **Proactive seed remains behaviorally unexposed**
    - provider seed payload does NOT contain `known_people`, role strings, or role contexts from the new structure;
    - evidence version is 2;
    - existing seed fields remain present.

14. **Proactive stale fence**
    - if a participant's active role changes between initial and fresh snapshot, a pending notify decision is discarded as stale without creating a notification.

15. **no deterministic importance machinery**
    - no role-weight table;
    - no `director=...` style rule;
    - no new salience/priority score field in the evidence classes.

## Regression checks

Run at minimum:

Backend:

- new REL1B-A focused tests;
- `backend/tests/test_rel1a_person_roles.py`;
- `backend/tests/test_workflow_intelligence_personal_relevance_e_b.py`;
- `backend/tests/test_workflow_intelligence_proactive_personalization_e_c.py`;
- `backend/tests/test_proactive_secretary_c.py`;
- focused Person identity tests needed by the exact grounding path;
- focused Person consolidation test proving hidden merged-away Person remains excluded;
- Ruff for changed Python files;
- `git diff --check`.

No Flutter build is required unless client code is unexpectedly touched; client code should not be touched.

## Schema / production boundary

Expected schema head remains `0054`.

Do not:

- add Alembic migration;
- edit `0053` or `0054`;
- move `production`;
- deploy backend;
- run production migration;
- build/install client;
- mutate production role data;
- run a real model;
- call external providers.

Production must remain:

- source/backend `6f802d6959aca40758376a83d5bdfcbbd77fc537`;
- Alembic `0054 / 0054`;
- installed client `6f802d6959aca40758376a83d5bdfcbbd77fc537`.

## Explicit non-goals

Do not start in this task:

- REL1B-B active Task context;
- Proactive consumption of known Person-role evidence;
- role-aware instruction changes;
- adversarial importance comparisons;
- REL1C Assistant role read/write;
- REL1D screenshot/document import;
- Organization ontology;
- Scheduled Activity;
- role weights/rank tables;
- Person-role semantic synonym merging.

## Expected next slice after acceptance

REL1B-B should, only after Architect source review of B-A:

- add bounded active confirmed Task actor context relevant to grounded People;
- expose grounded Person/role/Task evidence into Proactive seed context;
- update Proactive instructions so role is one evidence dimension, never a routing rule;
- preserve default NONE/silence and all current gates;
- add adversarial comparisons where critical unknown-sender content can outrank modest role-bearing content and role alone never forces notification.

Do not start REL1B-B automatically.

## Completion protocol

After implementation:

1. append a compact REL1B-A result to `PROJECT_STATE.md` with:
   - exact evidence version/shape;
   - exact grounding providers/identity rules;
   - bounds/truncation semantics;
   - signature/stale behavior;
   - confirmation Proactive model input/instructions were not exposed/changed;
   - exact test counts;

2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - evidence version = 2;
   - schema head still `0054`;
   - production/client unchanged at `6f802d...`;
   - no deploy/migration/client/model/provider action;
   - REL1B-B not started;

3. commit + push to `main`;

4. STOP.

Do not start the next slice from HOLD.
