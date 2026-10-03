# Current task — ACTIVE

## REL1C-B — approval-gated Assistant Person-role add/retract

REL1C-A is **ARCHITECT SOURCE-ACCEPTED**.

Accepted baseline:

- REL1C-A implementation: `ab6b05c84982275f443faa7877e189ddd6d9c34c`
- REL1C-A HOLD: `4834ff37317453889b1218ec58a3fc44856a08dc`
- Architect acceptance ledger: `103c48bd1151ebda1c7d4b87d5b26dee489d6fab`
- schema head: `0054`
- production backend/source: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- installed Linux client source: same exact SHA
- production Alembic: `0054 / 0054`

This task adds **Assistant Person-role writes**, but only through explicit ActionPlan approval.

Do not deploy, migrate, install the client, call a real model/provider, or start REL1D.

## Product goal

Support user requests such as:

- «Ольга — директор.»
- «Добавь Ивану роль научный руководитель.»
- «Добавь ему роль заведующий кафедрой в контексте кафедры X.»
- «Убери у Ольги роль директор.»
- «Удали именно роль директор в контексте Учебного центра.»

while preserving all REL1 invariants:

- Person roles are descriptive Person facts;
- RoleTerm vocabulary is open-ended;
- exact lexical duplicates collapse;
- semantic near-duplicates never auto-merge;
- optional context stays separate;
- one Person may have multiple roles;
- same RoleTerm may have multiple distinct contexts on one Person;
- role writes never create Task actor facts, labels, generic graph relations, authority, hierarchy, permissions, or deterministic importance;
- durable Assistant role writes always require explicit ActionPlan approval;
- manual UI role behavior remains unchanged.

## Add exactly two Assistant-only mutating tools

Preferred names:

1. `assign_person_role`
2. `retract_person_role`

Both:

- `assistant_exposed=True`;
- `mcp_exposed=False`;
- must require ActionPlan approval in interactive Assistant context;
- must not execute immediately from a normal Assistant turn;
- must have strict typed input + prepare/frozen execution input;
- must not call providers or models.

Permissions:

- `assign_person_role`: `ToolPermission.INTERNAL_WRITE`
- `retract_person_role`: `ToolPermission.DESTRUCTIVE_INTERNAL_WRITE`

Do not classify either as `ANNOTATE`: REL1 architecture requires explicit approval for durable role writes.

## Tool 1 — assign_person_role

### Interactive input

Typed input equivalent to:

- `person_id: UUID`
- exactly one of:
  - `role_term_id: UUID`
  - `new_role: str`
- `context: str | None = None`

Constraints:

- `new_role` uses REL1A role text bounds, max 120 display chars;
- `context` uses REL1A context bounds, max 200 display chars;
- exactly one of `role_term_id` and `new_role` is supplied;
- extra fields forbidden.

### Same-turn Person gate

Before staging:

- `person_id` must be in the current turn's committed `resolved_person_ids`;
- therefore the Assistant must have called `resolve_person` and received `state=resolved`;
- ambiguous/none/invented Person ids fail closed.

Reuse the existing Person resolution allowlist.

Do not let a Person returned only by `find_people_by_role` count as resolved.

### Existing RoleTerm path

If `role_term_id` is supplied:

- it must have been **model-visible in this turn as an exact stored RoleTerm**, not merely invented;
- allowed sources:
  - `get_person_roles.roles[].role_term_id`;
  - `find_people_by_role.exact_match_term_id`;
- a RoleTerm id shown only inside `suggestions` must NOT authorize a write;
- RoleTerm must still belong to the current user at prepare/execution.

Track exact RoleTerm ids in a dedicated role-term allowlist. Do not overload Object ids.

### New RoleTerm path

If `new_role` is supplied:

The Assistant must first have called `find_people_by_role` for the same **canonical lexical key** and received a model-visible result with:

- `exact_match_term_id = null`.

Track that committed no-exact result by REL1A canonical lexical key:

- trim;
- collapse Unicode whitespace;
- Unicode `casefold()`.

Then and only then may `new_role` stage.

Requirements:

- no read evidence -> no new term proposal;
- an exact term already shown -> do not use `new_role`;
- lexical suggestions do not count as exact;
- suggestion ids do not authorize assignment;
- do not silently replace the requested wording with a nearby suggestion;
- do not use fuzzy/semantic/embedding/LLM synonym matching.

Example:

- vocabulary contains only `генеральный директор`;
- user says «Ольга — директор»;
- `find_people_by_role("директор")` returns no exact term and may suggest `генеральный директор`;
- the Assistant may propose the exact new RoleTerm `директор`;
- it must not silently assign `генеральный директор`.

If the user explicitly chooses the suggested term later, the Assistant must perform a fresh exact lookup for that chosen wording so it becomes `exact_match_term_id`.

### Prepare/frozen canonical semantics

Use a prepare method.

The frozen execution payload should contain enough immutable semantic truth for approval, equivalent to:

- `person_id`;
- `role_term_id: UUID | None`;
- `role: str` — canonical display text being assigned;
- `context: str | None` — canonical stored display context;
- `create_if_missing: bool`;
- an opaque `operation_id` generated at prepare time for provenance/idempotent traceability.

Rules:

#### Existing term

At prepare time:

- verify active current-user Person;
- load current-user RoleTerm by the supplied id;
- freeze its canonical `display_text`;
- `create_if_missing=false`.

#### New term

At prepare time:

- normalize/validate `new_role` with REL1A `role_term_identity()`;
- verify no exact current-user RoleTerm exists at that moment;
- freeze canonical display text;
- `role_term_id=null`;
- `create_if_missing=true`.

If an exact RoleTerm has appeared since the no-exact read:

- do not stage a misleading “create new” action;
- fail preparation with a safe tool error telling the Assistant to re-read/reuse the exact term.

Freeze context through the same REL1A context normalization/validation as manual assignment.

### Execution semantics

After user approval:

- revalidate current-user active Person;
- for existing mode, revalidate the frozen RoleTerm id and lexical identity;
- for create-if-missing mode:
  - call the canonical REL1A assignment path with the frozen role text;
  - if an exact lexical term appeared after staging, reuse it rather than creating a duplicate;
- preserve active assignment cap 16;
- same RoleTerm + same context active assignment is idempotent/no-op;
- same RoleTerm + different context is a distinct allowed assignment;
- retracted history remains history;
- no semantic synonym merge.

### Assistant provenance

Manual UI assignments must keep current defaults unchanged:

- `origin=user`
- `provenance_kind=user_manual`
- `provenance_key=user_manual`

Assistant-approved newly created assignments must be distinguishable:

- `origin=agent`
- `provenance_kind=assistant_action_plan`
- `provenance_key` derived from the frozen opaque `operation_id`, bounded to schema length.

No Alembic change is required; current schema already permits these bounded strings.

If the approved operation resolves to an already-active assignment and is a no-op:

- do not rewrite its existing provenance merely to claim Assistant ownership.

Implement this without breaking existing `PersonRoleService.assign()` callers.

Preferred shape:

- add an internal/companion assignment outcome method that returns `(assignment, changed)` while holding the existing user serialization gate;
- keep existing public manual behavior backward compatible.

Equivalent atomic implementation is acceptable.

### assign output

Typed execution output should expose factual result equivalent to:

- `person_id`
- `assignment_id`
- `role_term_id`
- `role`
- `context`
- `changed: bool`
- `state` = active

Do not expose normalized keys/provenance internals to the model/finalization payload unless needed for deterministic tests.

## Tool 2 — retract_person_role

### Interactive input

Typed input:

- `person_id: UUID`
- `assignment_id: UUID`

Extra fields forbidden.

### Same-turn gates

Before staging:

1. Person must be same-turn `resolve_person state=resolved`;
2. the exact pair `(person_id, assignment_id)` must have been model-visible in the current turn from:
   - `get_person_roles`; or
   - `find_people_by_role`.

Track exposed assignment ids **paired to their Person**.

Do not allow:

- invented assignment id;
- assignment id exposed for a different Person;
- retract by role text alone;
- “remove all similar roles” fuzzy behavior.

If several assignments share the same RoleTerm but different contexts and the user's intent does not identify which one:

- Assistant must clarify;
- do not guess.

### Prepare/frozen canonical semantics

Use a prepare method.

At prepare:

- require active current-user Person;
- load the assignment;
- require current user + exact person match;
- require active state;
- load current-user RoleTerm;
- freeze:
  - `person_id`
  - `assignment_id`
  - `role_term_id`
  - `role`
  - `context`
  - opaque `operation_id`.

If already retracted before staging:

- do not create an approval plan;
- return safe no-longer-active tool error.

### Execution semantics

After approval:

- verify assignment still belongs to same current-user Person;
- preserve history;
- set state retracted via canonical `PersonRoleService`;
- never delete RoleTerm;
- never delete assignment row;
- idempotent if it became retracted after staging: return `changed=false`;
- if Person became inactive/hidden before approval, fail closed according to current PersonRole safety; do not mutate a hidden Person role.

Preferred atomic outcome method returns `(assignment, changed)` under existing user gate while keeping existing `retract()` compatibility.

### retract output

Typed output equivalent to:

- `person_id`
- `assignment_id`
- `role_term_id`
- `role`
- `context`
- `changed: bool`
- `state` = retracted

## Reference tracking required in Assistant runner

Add dedicated committed/pending state for role-write truth.

At minimum track:

### Exact RoleTerm ids

From model-visible outputs only:

- `get_person_roles.roles[].role_term_id`
- `find_people_by_role.exact_match_term_id`

Do NOT add suggestion ids.

### Exposed Person-role assignments

Track exact pairs:

- `(person_id, assignment_id)`

from:

- `get_person_roles`;
- `find_people_by_role.people[].assignments[]`.

### No-exact role lexical keys

From model-visible `find_people_by_role` only when:

- `exact_match_term_id is null`.

Canonicalize the returned query with REL1A role identity and store only its canonical key.

Pending ids/keys become usable only after the model-visible output is committed into the next model turn, following the existing reference tracking pattern.

Do not expose these sets outside the turn runner.

## ActionPlan approval presentation

Extend deterministic internal approval presentation for both new tools.

The approval card must show human-readable frozen semantics, not only opaque ids.

### assign presentation

Include:

- target Person entity/title;
- operation = `assign_person_role`;
- role display text;
- optional context;
- vocabulary mode:
  - `reuse_existing`; or
  - `create_if_missing`.

Do not show normalized keys/provenance secrets.

### retract presentation

Include:

- target Person entity/title;
- operation = `retract_person_role`;
- frozen role display text;
- optional context.

The presentation is a snapshot for approval only. Execution must still validate live ownership/state.

## Execution-effect / finalization truthfulness

Extend deterministic execution effects.

### assign_person_role

- `changed=true` -> effect `changed`;
- `changed=false` -> effect `no_op`.

Descriptions must distinguish:

- role assignment added;
- role assignment already active / no additional change.

### retract_person_role

- `changed=true` -> effect `removed` or equivalent explicit retraction effect;
- `changed=false` -> effect `no_op`.

Descriptions must distinguish:

- role assignment retracted;
- already retracted / no additional change.

Update `FINALIZATION_INSTRUCTIONS` only as needed to explicitly cover these tools:

- approval_required is not execution;
- `success=true` does not imply `changed=true`;
- never say a role was added/removed when effect is no-op or failed.

Do not let stored role text/context act as instructions during finalization.

## Assistant behavioral instructions

Replace the temporary REL1C-A “role editing unavailable” guidance.

### Add role workflow

For a named Person:

1. `resolve_person`;
2. require `state=resolved`;
3. call `find_people_by_role` using the exact desired role wording;
4. if exact term exists:
   - call `assign_person_role` with that exact `role_term_id`;
5. if no exact term exists:
   - do not silently choose a suggestion;
   - if the user's wording itself is a clear direct role assertion/request, call `assign_person_role` with `new_role` using that wording;
   - if the desired role is materially ambiguous, clarify instead;
6. pass context only when the user supplied or clearly established that context;
7. after `approval_required`, summarize the proposed change and wait for the approval card;
8. never claim persistence before approved execution succeeds.

### Retract workflow

1. resolve Person;
2. call `get_person_roles` to expose active assignments;
3. select only the exact assignment the user asked to remove;
4. if same role has multiple contexts and target is ambiguous, ask which;
5. call `retract_person_role`;
6. wait for approval;
7. do not claim removal before execution.

### Mutation boundaries

Never substitute:

- `assign_label`;
- Task actor fields;
- `link_objects`;
- `remove_relation`;
- Person rename;
- Person identity feedback.

Role writes never change:

- Task relations;
- labels;
- Person identity;
- salience;
- Personal Relevance directly;
- provider state.

Personal Relevance will pick up approved role changes through its existing evidence/signature machinery.

## Tool contracts

Add strict OpenAI function schemas.

Descriptions must explicitly say:

### assign_person_role

- requires resolved Person this turn;
- existing role path requires exact RoleTerm id shown this turn;
- new role path requires a no-exact `find_people_by_role` result for the same lexical role;
- lexical suggestions are not authorized substitutes;
- always approval-gated.

### retract_person_role

- requires resolved Person;
- exact assignment must have been exposed this turn;
- always approval-gated;
- retracts assignment only, not RoleTerm vocabulary.

No permissive extra properties.

## Schema / migration boundary

No Alembic changes.

Do not modify:

- `0053`;
- `0054`;
- table structure;
- RoleTerm lexical identity;
- assignment active uniqueness;
- cap 16.

Schema head stays `0054`.

## Required deterministic tests

Add focused REL1C-B tests, preferably:

`backend/tests/test_rel1c_assistant_role_writes.py`

At minimum prove:

### Registry/policy

1. both tools exist;
2. Assistant-exposed, not MCP-exposed;
3. assign = INTERNAL_WRITE;
4. retract = DESTRUCTIVE_INTERNAL_WRITE;
5. both have prepare + execution input model;
6. interactive call returns approval_required and does not mutate DB;
7. approved action-plan execution performs the write.

### Person target safety

8. unresolved Person cannot stage assign/retract;
9. ambiguous Person cannot stage;
10. invented/cross-user/hidden Person fails closed.

### Existing RoleTerm reuse

11. exact role lookup exposes exact term id;
12. that id may stage assignment;
13. exact term is reused, no second RoleTerm;
14. case/whitespace lexical variants still reuse same RoleTerm;
15. suggestion-only role_term_id is NOT eligible for assignment;
16. invented role_term_id fails.

### New RoleTerm proposal

17. `new_role` without prior no-exact lookup fails;
18. committed no-exact lookup for same canonical key allows staging;
19. no-exact lookup for a different role does not authorize;
20. if exact term appears before prepare, new-role staging fails and requires reread/reuse;
21. semantic near-duplicate suggestion does not block proposing the exact requested new wording;
22. approved new-role action creates/reuses exact lexical term and assignment only.

### Context/idempotence

23. optional context is preserved;
24. same role + same context already active does not stage a misleading new mutation OR execution returns truthful no-op according to the chosen deterministic design;
25. same role + different context creates distinct active assignment;
26. cap 16 remains enforced.

### Provenance

27. manual UI/service assignment remains:
   - origin user;
   - user_manual provenance.
28. newly changed Assistant-approved assignment records:
   - origin agent;
   - provenance_kind assistant_action_plan;
   - bounded operation-derived key.
29. Assistant no-op against an existing manual assignment does not rewrite manual provenance.

### Retract allowlist

30. assignment not exposed this turn cannot stage;
31. assignment exposed for Person A cannot retract under Person B;
32. assignment from `get_person_roles` may stage after resolved Person;
33. role-first assignment id may stage only after that Person is separately resolved;
34. multiple contexts remain separate exact assignments.

### Retract lifecycle

35. reject ActionPlan -> assignment remains active;
36. approve -> exact assignment retracted; RoleTerm remains;
37. re-approve same executed plan -> no duplicate mutation;
38. if assignment becomes retracted after staging but before approval, execution is truthful no-op;
39. hidden Person before approval -> plan fails closed without retraction.

### Approval presentation

40. assign card includes Person title, role, context, reuse/create mode;
41. retract card includes Person title, role, context;
42. no normalized key/provenance/raw identity leaks into presentation.

### Execution effects/finalization

43. assign changed=true described as added;
44. assign changed=false described as no-op;
45. retract changed=true described as retracted;
46. retract changed=false described as no-op;
47. finalizer cannot narrate add/remove when changed=false;
48. role/context in finalization context remain untrusted data.

### No ontology substitution

49. tests/instruction assertions prove role write does not call/route through:
   - assign_label;
   - Task actor writer;
   - link_objects/remove_relation;
   - Person identity writer.

### Concurrency / stale evidence

50. approved role write still takes existing user serialization gate;
51. REL1B stale-authority concurrency tests remain green;
52. role mutation before authority changes evidence signature and can stale a pending Proactive decision;
53. role mutation after authority cannot commit through the gate until authority releases.

No sleeps as correctness primitives.

## Regression suite

Run at minimum:

- new `test_rel1c_assistant_role_writes.py`;
- `backend/tests/test_rel1c_assistant_role_reads.py`;
- `backend/tests/test_person_assistant.py`;
- `backend/tests/test_assistant_action_plans.py`;
- `backend/tests/test_tool_gateway.py`;
- `backend/tests/test_rel1a_person_roles.py`;
- `backend/tests/test_rel1b_person_role_relevance_evidence.py`;
- `backend/tests/test_rel1b_task_context_relevance.py`;
- `backend/tests/test_workflow_intelligence_proactive_personalization_e_c.py`;
- `backend/tests/test_ah2_sem1_relation_boundary.py`;
- focused approval-presentation/finalization tests;
- focused registry/MCP parity/drift tests;
- Ruff for changed Python files;
- `git diff --check`.

All required suites must report 0 failed.

No real model calls.

## Expected production-code scope

Expected changes are narrowly in some subset of:

- `backend/app/services/person_role_service.py`;
- a dedicated Assistant role mutation service or existing `person_role_assistant_service.py`;
- `backend/app/services/domain_tool_service.py`;
- `backend/app/tools/schemas.py`;
- `backend/app/tools/assistant_contracts.py`;
- `backend/app/tools/registry.py`;
- `backend/app/assistant/reference_ids.py`;
- `backend/app/assistant/tool_runner.py`;
- `backend/app/assistant/approval_presentation.py`;
- `backend/app/assistant/execution_effects.py`;
- `backend/app/llm/openai_assistant_provider.py`;
- focused tests/docs parity.

Do not change:

- Flutter client;
- Alembic;
- Proactive model instructions/evidence shape;
- Task actor vocabulary;
- labels;
- provider configuration;
- Person identity ontology.

## Explicit non-goals

Do not start:

- REL1D screenshot/document import;
- Organization ontology;
- role synonym merge/rename;
- bulk role writes;
- role hierarchy;
- role-based permissions;
- RoleTerm delete/archive UI;
- role-based deterministic priority;
- client UI changes.

## Production / external-effect boundary

Source-only.

Do not:

- move `production`;
- deploy backend;
- run migration;
- build/install client;
- mutate production Person/role data;
- call real model/provider;
- send provider actions.

Production/backend/client remain exact:

`6f802d6959aca40758376a83d5bdfcbbd77fc537`

Alembic remains:

`0054 / 0054`

## Completion protocol

After implementation:

1. append a compact REL1C-B result to `PROJECT_STATE.md` with:
   - exact write tools/policy;
   - reference/allowlist semantics;
   - reuse-vs-create behavior;
   - provenance semantics;
   - ActionPlan presentation;
   - changed/no-op finalization truth;
   - concurrency evidence;
   - exact test counts;

2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - schema head still `0054`;
   - exact green test counts;
   - no deploy/migration/client/model/provider/product-data action;
   - production/client unchanged at `6f802d...`;
   - REL1D not started;

3. commit + push to `main`;

4. STOP.

Do not deploy or start REL1D from HOLD.
