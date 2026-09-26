# Current task — Ontology/Harness H1: semantic parity audit

Task Map V8E2 is accepted.

The Task visual/domain model is now stable enough to audit the second projection of the same ontology: the Secretary model-facing Harness / Assistant tools / MCP tools.

This is a DIAGNOSTIC AND DOCUMENTATION phase. Do not fix tool schemas, prompts, domain services, UI, or migrations in H1. The Architect will choose H2 from the findings.

## North star

Use the canonical architecture in `docs/architecture.md`:

- Actor / Person = who;
- Task / Commitment = what must happen;
- Flow = what happened / what arrived and the evidence/context around Tasks;
- Time = a cross-cutting dimension, not a separate workload;
- one ontology, two interfaces: Human UI and Model/Harness must share meaning/state/provenance even when affordances are not one-to-one.

The question is NOT "how many tools exist?"

The question is:

> Can the model reliably understand and operate the same domain concepts the human UI exposes, without missing canonical semantics, inventing parallel semantics, or escaping through overly generic tools?

## Sources of truth to inspect

At minimum inspect the actual current code, not old roadmap text:

- `docs/architecture.md`;
- `backend/app/tools/registry.py`;
- `backend/app/tools/schemas.py`;
- `backend/app/tools/assistant_contracts.py`;
- `backend/app/tools/policy.py`;
- `backend/app/tools/gateway.py`;
- `backend/app/tools/executor.py`;
- `backend/app/services/domain_tool_service.py`;
- `backend/app/llm/openai_assistant_provider.py` including actual `SYSTEM_INSTRUCTIONS`;
- `backend/app/services/task_profile_service.py`;
- `backend/app/services/task_relation_service.py`;
- `backend/app/domain/task_relations.py`;
- Task lifecycle/completion-mode domain code;
- Person assistant / identity / routes services;
- current Graph/Task/Profile REST/UI affordances where needed for Human-vs-Model comparison;
- existing parity/gateway tests such as `backend/tests/test_tool_gateway.py`;
- MCP exposure generated from the registry.

Search the repository for additional tool/prompt/domain paths. Do not assume this list is exhaustive.

## Deliverable A — semantic capability matrix

Create:

`docs/ontology_harness_parity_audit.md`

Build a concise matrix organized by domain capability, not by tool name.

For every capability record:

- canonical domain meaning;
- Human/UI affordance if one exists;
- Assistant tool affordance;
- MCP affordance;
- underlying canonical service/domain implementation;
- read/write/propose/approve semantics;
- provenance/state semantics;
- verdict:
  - `ALIGNED`
  - `MODEL_GAP`
  - `HUMAN_GAP`
  - `OVER_GENERIC`
  - `PARALLEL_SEMANTICS`
  - `STALE_CONTRACT`
  - `INTENTIONALLY_ASYMMETRIC`;
- concrete evidence: file/function/schema names.

Do not score or rank tools. Classify semantic fit.

## Mandatory Task coverage

Audit at minimum:

1. Task discovery / exact read / bounded context.
2. Task Profile and derived operational state.
3. Create Task.
4. Edit title/body/due.
5. Lifecycle status.
6. Soft delete.
7. `completion_mode` finite vs ongoing / Direction:
   - read;
   - create;
   - edit;
   - lifecycle constraints;
   - whether the Assistant can express the same operation as the UI/domain.
8. Task evidence (`references`) add/remove.
9. Actor roles:
   - `requested_by`;
   - `delegated_to`;
   - `waiting_on`;
   - `involves`;
   - add/remove/read symmetry.
10. Dependency `depends_on` add/remove/read.
11. Composition `part_of` add/remove/read:
    - child/source -> parent/target;
    - one-parent/cycle/completion compatibility;
    - whether tool descriptions are sufficiently explicit.
12. Proposed/confirmed/rejected relation state and approval semantics.
13. Task time fields actually present in the canonical domain:
    - due;
    - planned start/end if current;
    - recurrence/scheduled semantics where relevant.
14. Whether generic Graph tools let the model bypass canonical Task semantics.

Explicitly verify the current spot-check:
`CreateTaskInput` / `UpdateTaskInput` versus domain/UI `completion_mode`.
Do not assume the preliminary observation is the final classification.

## Mandatory Person / Actor coverage

Audit at minimum:

1. Resolve a named Person without guessing identity.
2. Read exact/effective identities.
3. Discover identity candidates.
4. Confirm/reject/retract identity evidence.
5. List communication routes.
6. Remember/record route choice.
7. Find communications for a resolved Person.
8. Send email/message to a resolved Person through a grounded route and approval boundary.
9. Read Person-linked open Tasks / Actor roles from the model side.
10. Determine whether the model can answer:
   - who requested this Task?
   - who is it delegated to?
   - whom are we waiting on?
   using canonical data rather than generic text search.
11. Explicit organization/manager/member-of semantics:
   - document whether these are currently absent by design or partially represented;
   - do NOT invent them and do NOT implement them in H1.

Distinguish Person identity/routing from future grounded organizational-role vocabulary.

## Mandatory Flow coverage

Audit whether the model has a coherent provider-neutral path for:

- semantic discovery;
- structured/date/status search;
- exact Object read;
- bounded content/context;
- graph neighbors/provenance;
- using Flow as Task evidence;
- responding/sending through an exact grounded communication context;
- media/file/calendar/message Objects where already supported.

Check for source-specific convenience tools that create a parallel ontology versus legitimate provider-side execution boundaries.

## Mandatory Time coverage

Audit:

- current date/time;
- Task due/planned time visibility and mutation;
- calendar Flow;
- scheduled/reminder activity;
- recurrence;
- whether reminder/scheduled activity semantics conflict with Task/Commitment or remain a legitimate temporal execution primitive.

Do not redesign Time in H1.

## Escape-hatch / redundancy audit

For every generic tool capable of writing semantics, especially `link_objects`:

1. Compare its Assistant JSON schema to service-side validation.
2. Determine whether arbitrary relation strings can reach storage, or whether a canonical allowlist exists later.
3. Determine whether the model can create relations that Human UI/domain projections do not understand.
4. Identify overlap with specialized Task mutations (evidence, actors, dependencies, composition).
5. Decide whether each overlap is:
   - useful composability;
   - harmless redundancy;
   - or an ontology escape hatch.

Also inspect whether Assistant and MCP exposures differ intentionally or accidentally.

Do NOT change any allowlist in H1.

## Harness / prompt comprehension audit

Inspect actual `SYSTEM_INSTRUCTIONS` and individual tool descriptions.

Answer:

- Does the model receive enough explicit semantics to distinguish Task lifecycle from operational state?
- Does it understand finite Task vs ongoing Direction?
- Does it understand Actor roles rather than treating People as contact-book entries only?
- Does it understand `part_of` as composition rather than dependency?
- Does it understand Flow as evidence/context instead of automatically materializing every message/event as a Task?
- Are important semantics encoded only in backend validation, with insufficient tool/prompt description for good first-attempt behavior?
- Are there stale prompt statements that conflict with current capabilities?

Classify prompt gaps separately from missing tools.

## Toolset documentation reconciliation

Update `docs/SECRETARY_TOOLSET_MATRIX.md` so it describes the ACTUAL current registry and capabilities.

This update is documentation only.

At minimum reconcile stale claims about:
- currently implemented scheduled-activity tools;
- external calendar/email/message actions;
- current removable relation types;
- Person tools;
- Task Profile;
- any other drift discovered.

The matrix must still describe capability truth, not become a chronological changelog.

## Deliverable B — gap list for Architect

At the end of `docs/ontology_harness_parity_audit.md`, provide a bounded list grouped as:

### Blocking semantic parity gaps
A model-facing mismatch that prevents correct operation of an already-canonical concept.

### Risky escape hatches / ambiguous contracts
The capability exists, but the model can misuse or reinterpret it.

### Useful but non-blocking affordance gaps
The model can obtain the meaning compositionally, but awkwardly.

### Intentional asymmetries
Different UI/tool affordances that correctly share the same semantics.

### Future ontology, not a tool gap
Examples may include manager/organization relations if they are genuinely not canonical yet.

For every gap propose the SMALLEST likely H2 remedy, but do not implement it.

## Deliverable C — explicit recommendation boundary

Conclude with:

1. whether current Harness/Tools are sufficient to proceed with a People visual prototype without first changing the ontology;
2. which, if any, H2 fixes should be done BEFORE that prototype because they affect core semantic parity;
3. which fixes can wait for the later stabilization/hardening pass.

This is an architectural recommendation based on repository evidence, not code implementation.

## Validation

Because H1 should change documentation only:

- run any existing lightweight tool registry/gateway parity tests needed to verify claims;
- at minimum run the relevant registry definition tests from `backend/tests/test_tool_gateway.py` if practical;
- run `git diff --check`.

Do not modify production Python/Dart to make tests pass.
Do not add a migration.
Do not build Flutter unless production client code is unexpectedly changed; it should not be.

If you discover a code bug, document it as a finding rather than fixing it.

## Scope guard

Do NOT in H1:

- add `completion_mode` to tools;
- restrict `link_objects`;
- change prompts;
- add/remove tools;
- change MCP exposure;
- implement manager/organization relations;
- start People visual redesign;
- fix the known Graph detail-screen failures;
- deploy production.

## Completion

Record in `PROJECT_STATE.md`:

- implementation SHA;
- audit document path;
- count of findings by category;
- highest-impact semantic parity findings;
- whether `SECRETARY_TOOLSET_MATRIX.md` changed;
- exact tests run.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not start H2.
Do not start People visual prototype.
Do not deploy production.
