# Current task — ACTIVE

## REL1B-B — confirmed active Task context + model-visible role-aware Personal Relevance

REL1B-A and REL1B-A.1 are **ARCHITECT SOURCE-ACCEPTED**.

Accepted source:

- REL1B-A evidence: `0859fc4ebeb49db06f9ab12efc2f9acb552ecab9`
- REL1B-A.1 stale-authority corrective: `9d13d9ec36b10b0861e002c25ba5715e5ed48ec7`
- Executor HOLD: `8e112e5b87612625c251472ce959b5d6d06a39d8`
- Architect acceptance ledger: `4be22538775b284d50ac2230802104eee553ec86`

Production remains intentionally behind source:

- production backend/source: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- installed Linux client source: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- Alembic: `0054 / 0054`

This task completes the first source-level REL1B behavioral slice.

It adds bounded **confirmed active Task actor context** to Personal Relevance evidence and deliberately exposes grounded Person roles + that Task context to the Proactive model as evidence.

Do not deploy, migrate, install the client, or make a real model/provider call in this task.

## Product invariant

Role is evidence, never a weight.

Do not introduce rules such as:

- `директор = +50`;
- `студент = -20`;
- “known Person always outranks unknown Person”;
- “role-bearing Person always deserves a notification”;
- “requested_by always means responsible”;
- “waiting_on always maps directly to one PersonalDependency value”.

The model must judge the combination of:

- current source content/context;
- current-user participation;
- exact-grounded known Person facts;
- active Person role terms + optional role contexts;
- confirmed active Task actor context;
- due/planned Task timing;
- labels;
- Personal Semantic Context;
- read-tool evidence when needed.

Missing or truncated Person/role/Task evidence is unknown/incomplete, never negative evidence.

## Required evidence version

Bump:

`PERSONAL_RELEVANCE_EVIDENCE_VERSION = 3`

The version changes because canonical object evidence gains Task context and therefore stale signatures must change.

Do not create a second version mechanism.

## Required internal Task evidence shape

Add provider-neutral typed evidence in `backend/app/personal_relevance/models.py`.

Exact class names may vary, but semantics must be equivalent to:

### RelatedTaskActorEvidence

Fields:

- `person_id: UUID`
- `actor_role: str`

`actor_role` must be exactly one of the existing Task actor vocabulary:

- `requested_by`
- `delegated_to`
- `waiting_on`
- `involves`

### RelatedActiveTaskEvidence

Fields:

- `task_id: UUID`
- `title: str`
- `status: str | None`
- `start_at: datetime | None`
- `due_at: datetime | None`
- `planned_start_at: datetime | None`
- `planned_end_at: datetime | None`
- `actor_links: tuple[RelatedTaskActorEvidence, ...]`

### ObjectPersonalRelevanceEvidence additions

Add:

- `related_tasks: tuple[RelatedActiveTaskEvidence, ...]`
- `related_tasks_truncated: bool`

These fields participate in the canonical object evidence payload/signature.

Do not include Task body/description in this automatic seed evidence.

Do not include generic relations, Organization inference, Person salience, role weights, or proposed Task relations.

## Which Tasks qualify

For a source object X:

1. start from X's already accepted exact-grounded `known_people`;
2. inspect Task actor edges whose target is one of those known Person IDs;
3. include only edges where:
   - `Edge.user_id` is current user;
   - `Edge.type` is one of the four canonical Task actor roles;
   - `Edge.state == confirmed`;
4. include only source Task objects where:
   - current user owns the Task;
   - `kind == task`;
   - Task object `state == confirmed`;
   - Task is not rejected/deleted/tombstoned/merged-hidden;
   - Task status is not terminal for reads:
     - done;
     - completed legacy;
     - cancelled;
     - archived;
     - deleted.

A proposed Task or proposed actor edge is not confirmed Personal Relevance evidence.

A generic `related_to` edge is never an actor fact.

Do not infer an actor edge from a Person role or vice versa.

## Boundedness and neutral ordering

Add:

`PERSONAL_RELEVANCE_MAX_RELATED_TASKS_PER_OBJECT = 8`

For each source object:

- de-duplicate related Tasks by `task_id`;
- union all confirmed actor links from grounded People for each kept Task;
- de-duplicate actor links by `(person_id, actor_role)`;
- order related Tasks neutrally by Task UUID bytes;
- order actor links by Person UUID bytes, then canonical actor-role order;
- keep at most 8 related Tasks;
- if more relevant active confirmed Tasks exist, set `related_tasks_truncated=true`.

Selection must not rank by:

- Person role text;
- Person salience;
- due date;
- actor role;
- message frequency;
- inferred importance.

The evidence is bounded factual context, not a pre-ranked attention list.

### Query boundedness

Do not load an unbounded history of Task actor edges.

Preferred batched shape:

1. collect the deduplicated known Person IDs across the bounded snapshot;
2. use one bounded query/CTE/windowed read for confirmed actor links + active confirmed Tasks;
3. cap candidate unique Tasks per Person at `MAX_RELATED_TASKS_PER_OBJECT + 1` using neutral Task UUID order so truncation can be detected;
4. assemble each source object's union in memory;
5. no per-object or per-Person Task query.

Equivalent bounded batching is acceptable.

Add a query-count or spy regression that proves this does not become N+1.

## Model-visible Proactive projection

REL1B-A intentionally kept `known_people` hidden from the model.

REL1B-B now exposes a **smaller bounded projection** in `seed_context_from_evidence()`.

Do not simply dump the entire internal snapshot objects.

Add explicit Proactive projection caps:

- `PROACTIVE_MAX_KNOWN_PEOPLE_PER_SEED_OBJECT = 4`
- `PROACTIVE_MAX_ROLES_PER_KNOWN_PERSON = 4`
- `PROACTIVE_MAX_RELATED_TASKS_PER_SEED_OBJECT = 4`

Equivalent clearly named constants are acceptable.

For each seed object expose:

### `known_people`

At most 4, preserving neutral internal order:

- `person_id`
- `display_name`
- `source_roles`
- `roles`:
  - `role`
  - `context`
- `roles_truncated`

Do NOT expose to the model:

- `role_term_id`;
- normalized lexical keys;
- assignment provenance internals;
- raw identity canonical values.

Model-visible `roles_truncated` must be true if either:

- internal REL1B-A role evidence was already truncated; or
- the Proactive 4-role projection truncated it further.

Add a model-visible known-People truncation flag that is true if either the internal evidence or the 4-Person projection truncated.

### `related_tasks`

At most 4, preserving neutral internal order:

- `task_id`
- `title`
- `status`
- `start_at`
- `due_at`
- `planned_start_at`
- `planned_end_at`
- `actor_links`:
  - `person_id`
  - `actor_role`

Add a model-visible Task truncation flag that is true if either internal Task evidence or the 4-Task projection truncated.

The model-visible Task list may only reference Person IDs present in the internal grounded evidence for that source object.

Do not send Task bodies automatically. The model already has bounded read tools when deeper context is justified.

## Proactive instruction changes

Update `PROACTIVE_SYSTEM_INSTRUCTIONS` narrowly.

Preserve:

- default decision = NONE;
- silence is successful;
- current confidence threshold;
- current output schema;
- current read-tool allowlist;
- current write prohibition;
- current duplicate-task avoidance;
- current source-object ID fencing.

Add explicit guidance equivalent to all of the following:

1. **Person roles are descriptive evidence**
   - stored Person role terms/context may help interpret why a source matters to the user;
   - a role term is not a rank, permission, hierarchy, or automatic priority.

2. **Task actor facts are Task-scoped**
   - `requested_by`, `delegated_to`, `waiting_on`, `involves` describe explicit links on a specific Task;
   - they are not Person roles;
   - they do not deterministically map to `PersonalRelationship` or `PersonalDependency`.

3. **Known does not automatically beat unknown**
   - an unknown/unrecorded sender can still carry the most important or critical item;
   - absence of a known Person, role, or Task link does not mean low relevance.

4. **Role alone never forces interruption**
   - a senior-sounding or otherwise notable role with routine/non-actionable content is insufficient by itself;
   - combine source content, current Task context, timing, participation, and other evidence.

5. **Active work context can matter**
   - modest wording from a known Person may become important when the source materially advances/blocks/changes active confirmed work involving that Person;
   - when related Task summary looks material, use `get_task_profile` before proposing a duplicate Task or when dependencies/operational state matter.

6. **Truncation is incomplete**
   - role/known-Person/related-Task truncation flags mean more evidence may exist;
   - never treat omitted evidence as negative proof.

7. **Untrusted data**
   Explicitly include:
   - known Person names;
   - Person role terms;
   - role contexts;
   - related Task titles;
   - Task actor roles;
   in the existing untrusted-data rule.

Do not add specific lexical role rankings or examples that imply one role title has an inherent score.

## Stale-fence / authority extension for Task evidence

Because Task context is now model-visible and part of evidence signatures, it must receive the same correctness guarantees as known-Person roles.

### 1. Authority locks initial related Task rows

Extend `acquire_personal_relevance_authority()` so the caller passes deduplicated Task IDs present in the **initial** snapshot's `related_tasks`.

Lock only those Task Object rows:

- current user;
- kind=task;
- deterministic UUID-byte order;
- `FOR UPDATE`;
- `populate_existing=True`.

Do not lock every Task in the graph.

A Task field mutation before authority is allowed to commit and must make the fresh snapshot stale.

A Task field mutation after authority must be unable to commit until the notification transaction releases its lock.

### 2. Serialize Task actor relation writes through the user gate

In `TaskRelationService`:

- `add_actor()` must take the existing user serialization gate before reading/mutating actor facts;
- `remove_actor()` must do the same.

Do not add this gate to read-only Task Profile operations.

### 3. Cover low-level actor-edge mutations too

The raw `GraphService` edge primitives can technically mutate actor-edge state outside `TaskRelationService`.

For edge types in `TASK_ACTOR_ROLES`, acquire the same user serialization gate before mutation in all low-level paths that can change actor evidence, including:

- `create_edge()`;
- `delete_edge()`;
- `set_edge_state()`;
- `reject_confirmed_agent_relation()`.

Do not serialize unrelated generic edge writes merely for this task.

Do not redesign or remove the low-level edge API in this slice.

This is a concurrency fence, not a new ontology writer.

### 4. Existing role/identity/Person locks remain

Do not weaken REL1B-A.1.

Initial known Person rows remain locked during authority.

Role/identity/consolidation writes remain user-gated.

## Required signature/stale behavior

Prove:

- adding a confirmed actor link between a grounded Person and an active confirmed Task changes only relevant source object evidence signatures;
- removing/rejecting that confirmed actor link changes those signatures;
- proposed actor links do not affect signatures;
- proposed Task objects do not affect signatures;
- terminal Tasks disappear from related Task evidence;
- changing relevant Task title/status/due/planned fields changes the source signature;
- changing an unrelated Task does not change the source signature;
- role-only changes retain REL1B-A behavior.

Use the existing evidence signature/stale comparison. Do not add a second stale system.

## Required deterministic tests — evidence

Add a focused REL1B-B module, for example:

`backend/tests/test_rel1b_task_context_relevance.py`

At minimum prove:

1. evidence version is exactly 3;

2. confirmed actor context:
   - exact-grounded Person participates in an active confirmed Task;
   - Task appears with the correct explicit actor role and timing fields;

3. all four actor roles are represented exactly without semantic remapping;

4. proposed actor edge is absent;

5. proposed Task is absent even with a confirmed-looking actor edge;

6. terminal Task is absent;

7. rejected/deleted/foreign Task is absent;

8. `related_to` does not become actor evidence;

9. de-duplication:
   - same Task linked to two grounded People appears once;
   - actor links retain both People/roles;
   - duplicate equivalent edges cannot duplicate a model fact;

10. Task bound:
    - more than 8 relevant unique active Tasks yields exactly 8 + `related_tasks_truncated=true`;
    - ordering is UUID-neutral, not due-date/role/salience order;

11. batching:
    - multiple source objects/People do not cause per-object/per-Person Task queries;

12. signatures:
    - relevant actor add/remove changes signature;
    - relevant Task title/due/status/planned change changes signature;
    - unrelated Task change does not.

## Required deterministic tests — Proactive model projection

Prove:

1. model seed now contains bounded `known_people` with role/context evidence;

2. `role_term_id`, normalized keys, provenance, and raw identity keys are absent from model-visible JSON;

3. model seed contains bounded `related_tasks` with actor links;

4. projection caps are 4 People / 4 roles / 4 Tasks per seed object and truncation remains truthful;

5. role contexts and Task titles are serialized only as data, not parsed into instructions/rules;

6. existing participation/labels/user context fields remain present;

7. evidence version in seed is 3.

## Required deterministic tests — adversarial importance contract

No real model call is authorized, so acceptance here is server/instruction-contract evidence, not a claim about stochastic model quality.

Use scripted Proactive providers plus instruction assertions to prove:

### A. Role alone does not force a notification

- seed source resolves to a known Person with one or more role terms;
- no material active Task context is required;
- scripted model returns NONE;
- server persists no notification;
- there is no deterministic server-side role routing/override.

### B. Unknown critical source is allowed to win

Construct one review with at least:

- seed 1: known role-bearing Person with modest/routine source context;
- seed 2: unknown/unrelated sender/source with clearly critical/urgent source title/context.

Scripted provider selects seed 2 for a valid notify decision.

Prove the server accepts/persists that decision and does not force the known Person seed to win.

Instruction assertions must explicitly say known Person/role does not automatically outrank unknown source evidence.

### C. Known Person + active work is allowed to matter

- seed resolves to known Person with role evidence;
- confirmed active Task actor context exists;
- scripted provider selects it for a valid notify decision;
- server accepts it subject to existing gates;
- no role-specific server rule is involved.

### D. No hard-coded role taxonomy/weights

Production code changed by REL1B-B must not contain:

- a role-title -> score map;
- fixed lexical role ranking;
- deterministic “known Person wins” branch;
- new priority/salience numeric field derived from Person role.

Do not use specific role titles in production routing code.

## Required deterministic tests — concurrency

Extend existing isolated multi-session tests to prove:

1. confirmed Task actor write **before authority** commits, changes fresh evidence, and discards notification as stale;

2. Task actor write **after authority** through `TaskRelationService` cannot acquire the user gate under short lock timeout;

3. low-level `GraphService` actor edge mutation after authority cannot bypass the user gate;

4. relevant Task title/due/status mutation after authority cannot commit because the initial related Task row is locked;

5. unrelated Task update is not globally locked merely because another source has one related Task;

6. existing role/identity/Person concurrency tests remain green.

No sleeps as correctness primitives.

## Proactive audit privacy

Do not put raw Person names, role text/context, or Task titles into AI audit metadata merely for this slice.

Existing signatures and bounded booleans/counts are sufficient.

If audit metadata is extended, only sanitized counts/truncation/state markers are allowed.

## Required regression checks

Run at minimum:

- new REL1B-B focused evidence/projection/adversarial/concurrency tests;
- `backend/tests/test_rel1b_person_role_relevance_evidence.py`;
- `backend/tests/test_rel1a_person_roles.py`;
- `backend/tests/test_workflow_intelligence_personal_relevance_e_b.py`;
- `backend/tests/test_workflow_intelligence_proactive_personalization_e_c.py`;
- `backend/tests/test_proactive_secretary_c.py`;
- `backend/tests/test_task_relations.py`;
- `backend/tests/test_ah2_sem1_relation_boundary.py`;
- focused Person identity/consolidation regressions touched by authority;
- focused Task mutation/status tests needed by Task row locking;
- Ruff on changed Python files;
- `git diff --check`.

All required suites must be 0 failed.

Do not “fix” tests by deleting historical product data.

## Expected production-code scope

Expected changes are narrowly in:

- `backend/app/personal_relevance/models.py`;
- `backend/app/services/personal_relevance_evidence_service.py`;
- `backend/app/services/proactive_review_service.py`;
- `backend/app/proactive/instructions.py`;
- `backend/app/services/task_relation_service.py`;
- `backend/app/services/graph_service.py`;
- focused tests.

A small helper module for bounded Task evidence is acceptable if it keeps the service readable.

Do not change:

- Alembic/schema;
- client;
- Person role schema/normalization;
- Task relation vocabulary;
- PersonalRelationship/PersonalDependency enums;
- ProactiveDecision schema;
- tool allowlist;
- confidence threshold;
- notification persistence/gates;
- provider configuration.

If another production file is genuinely required, record why; do not broaden unrelated architecture.

## Explicit non-goals

Do not start:

- REL1C Assistant role reads/writes;
- REL1D screenshot/document import;
- Organization ontology;
- Scheduled Activity;
- role synonym merging;
- role hierarchy;
- role-based permissions;
- deterministic importance score;
- salience changes;
- client UI changes.

## Production / external-effect boundary

This task is source-only.

Do not:

- move `production`;
- deploy backend;
- run migration;
- build/install client;
- mutate production People/roles/Tasks;
- send real notifications for testing;
- run a real model;
- call external providers.

Production/backend/client must remain exact:

`6f802d6959aca40758376a83d5bdfcbbd77fc537`

Alembic remains:

`0054 / 0054`

## Completion protocol

After implementation:

1. append a compact REL1B-B result to `PROJECT_STATE.md` with:
   - evidence version 3;
   - exact related-Task shape and bounds;
   - confirmed-only Task/actor semantics;
   - model-visible projection caps;
   - instruction semantics;
   - stale/authority Task locking + actor writer gate;
   - adversarial contract evidence;
   - exact test counts;

2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - evidence version 3;
   - schema head 0054;
   - exact green test counts;
   - Proactive seed now receives bounded grounded Person role + confirmed active Task context;
   - no hard-coded role weights/ranking;
   - production/client unchanged at `6f802d...`;
   - no deploy/migration/client/model/provider/product-data action;
   - REL1C/REL1D not started;

3. commit + push to `main`;

4. STOP.

Do not deploy or start the next slice from HOLD.
