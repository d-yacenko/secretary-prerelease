# Current task — AH1 current ontology / harness / UI parity audit

RP1 is HUMAN-ACCEPTED and CLOSED.

This task starts the next major stage: Secretary model-side quality — Harness, prompt, toolset, MCP exposure, approval/provenance behavior, and semantic parity with the human UI/UX.

This slice is **diagnosis-only**.

Do NOT change production behavior, prompt text, tool schemas, domain services, API contracts, UI, migrations, or deployment.

## Why this audit is required

The repository already contains:

- `docs/architecture.md` with the principle **one ontology, two interfaces**;
- `docs/SECRETARY_TOOLSET_MATRIX.md`;
- `docs/ontology_harness_parity_audit.md`;
- a mature Assistant/MCP tool registry and approval/provenance machinery.

But the previous parity audit is stale relative to current code.

Verified examples:

1. The old audit says `CreateTaskInput` / `UpdateTaskInput` omit `completion_mode`.
   Current schemas already expose:
   - `completion_mode = finite | ongoing`;
   - prompt semantics explicitly describe finite Task vs ongoing Direction/Activity.

2. The old audit says `link_objects.relation_type` is an unconstrained string / ontology escape hatch.
   Current code uses `GenericRelationType = Literal["related_to", "references", "depends_on", "part_of"]`, shared with the canonical generic relation vocabulary.

Therefore do not carry old verdicts forward without re-verifying them against current `main`.

## Goal

Produce a current, evidence-backed answer to:

> Does the Secretary model have machine-operable affordances over the same Person / Task / Flow / Time semantics that the human UI exposes, with the same meaning, provenance, reversibility, and safety boundaries?

Separate **contract parity** from **model behavior quality**.

Static code inspection can prove contracts and invariants. It cannot prove that a real LLM will reliably choose the right tools in realistic conversations.

The audit must explicitly mark that distinction.

## Authoritative sources

Use current `main`, not historical assumptions.

### Architecture / product semantics

- `docs/architecture.md`
- current Graph / Task Profile / People / Inbox / Assistant UI implementations where relevant
- current relation vocabulary and task completion semantics

### Model projection

- `backend/app/llm/openai_assistant_provider.py`
  - ontology kernel
  - routing/prompt policy
  - unsupported mutation rule
  - approval protocol
  - untrusted-data boundary
  - finalization instructions
- `backend/app/tools/registry.py`
  - one canonical registry
  - Assistant vs MCP exposure
  - permissions
- `backend/app/tools/schemas.py`
- `backend/app/tools/assistant_contracts.py`
- `backend/app/services/domain_tool_service.py`
- specialized canonical domain services reached by those tools
- `backend/app/assistant/tool_runner.py`
- `backend/app/tools/executor.py`
- `backend/app/tools/policy.py`
- action-plan / execution-effect / provenance code
- MCP gateway/session/server code

### Existing documentation

Treat these as claims to verify, not authority:

- `docs/SECRETARY_TOOLSET_MATRIX.md`
- `docs/ontology_harness_parity_audit.md`

Identify stale statements explicitly.

## Audit dimensions

### 1. Ontology kernel

Audit current semantics for:

- Person = who;
- Task = commitment / Direction;
- Flow = evidence / context / what happened;
- Time = when;
- explicit relations are facts, not guesses.

Verify that prompt, tool contracts, services, and human UI use the same meanings.

### 2. Task parity

At minimum audit:

- exact identity/read;
- semantic discovery vs structured query;
- create Task;
- finite vs ongoing `completion_mode`;
- title/body/due mutation;
- lifecycle status;
- soft deletion;
- confirmed/proposed/rejected provenance;
- evidence `references`;
- actor roles:
  - `requested_by`
  - `delegated_to`
  - `waiting_on`
  - `involves`;
- `depends_on`;
- `part_of` child -> parent:
  - one parent
  - cycle/self rejection
  - completion-mode matrix;
- generic `related_to`;
- relation removal/rejection;
- labels;
- planned start/end;
- duplicate-task avoidance;
- Task Profile operational state vs lifecycle state.

Do not assume human and model must have identical buttons/tools. Judge semantic capability and canonical state.

### 3. Person parity

Audit:

- exact Person identity;
- ambiguity handling;
- identity candidates;
- confirm/reject/retract feedback;
- communication lookup;
- communication route discovery;
- route memory;
- Person actor roles on Tasks;
- no unsupported organization/manager ontology;
- Assistant-only vs MCP exposure and whether it is intentional.

### 4. Flow parity

Audit:

- retrieve/query/read/context;
- provenance and neighbors;
- Flow as Task evidence, not automatic workload;
- provider-neutral email/chat/calendar semantics;
- reply against exact communication objects;
- files/notes/events/messages remain Flow kinds;
- no provider-specific parallel ontology.

### 5. Time parity

Audit:

- current local date/time;
- Task due;
- planned interval;
- calendar Flow;
- one-shot reminder;
- recurring reminder;
- lifecycle/status interactions.

### 6. Relation parity with current Graph UX

Use the now-human-accepted Graph behavior as the human projection.

Verify model-side semantics for exactly the relation vocabulary currently exposed/accepted:

- `related_to`
- `references`
- `depends_on`
- `part_of`
- Task actor roles through their typed fields
- labels through label tools

Confirm that the toolset cannot invent arbitrary relation types.

Audit current asymmetry:
- human UI can confirm/reject proposals;
- model removal rejects a removable edge;
- determine whether lack of a model-side confirm operation is intentional and still appropriate.

Do not introduce relation editing in this audit.

### 7. Approval / reversibility / provenance

Audit end-to-end:

- READ vs ANNOTATE vs INTERNAL_WRITE vs DESTRUCTIVE_INTERNAL_WRITE vs COMMUNICATE / external writes;
- when action plans are required;
- `approval_required` means not executed;
- user approval card as commit boundary;
- proposed agent artifacts vs confirmed state;
- deterministic finalization:
  - `success=true` is not `changed=true`;
  - no-op must not be reported as mutation;
- exact object/edge IDs;
- reversible relation rejection;
- external send safety;
- untrusted stored data never becomes instructions.

Compare these semantics with what the UI communicates.

### 8. Assistant vs MCP vs proactive exposure

Build a current exposure table from `TOOL_SPECS`.

For every capability classify:

- Assistant;
- MCP;
- proactive/read-only;
- intentionally unavailable.

An exposure difference is not automatically a defect.

Flag only differences that create semantic inability or a parallel contract.

### 9. Prompt/tool routing quality

Inspect whether the prompt gives enough first-attempt guidance for:

- Person resolution before communication;
- retrieve vs query_objects;
- evidence vs Task materialization;
- finite vs ongoing;
- Task lifecycle vs operational state;
- actor-role questions;
- `part_of`;
- removing relations using exact edge ids;
- reminders vs Tasks;
- provider-neutral send/reply;
- unsupported mutation rule;
- ambiguity and clarification.

Classify weak routing hints separately from missing tools.

### 10. Human-UI / model affordance matrix

For each important user operation record:

- human affordance;
- model affordance;
- canonical state/service;
- provenance/write semantics;
- verdict.

Use verdicts:

- `ALIGNED`
- `INTENTIONALLY_ASYMMETRIC`
- `MODEL_GAP`
- `HUMAN_GAP`
- `PARALLEL_SEMANTICS`
- `STALE_CONTRACT`
- `BEHAVIOR_UNVERIFIED`

Only use `OVER_GENERIC` if current code truly permits non-canonical semantics. Do not repeat the historical `link_objects` verdict if the current Literal closes it.

## Behavior-quality boundary

Static parity is not the same as “the agent works well”.

Do NOT call an external LLM or production Assistant in AH1.

Instead create a **behavior evaluation scenario catalogue** for the next slice.

For each scenario specify:
- user utterance;
- relevant existing state;
- expected read/tool sequence at semantic level;
- mutations that are allowed;
- mutations that are forbidden;
- required clarification, if any;
- expected approval boundary;
- expected final semantic state;
- failure modes to score.

Include representative scenarios such as:

1. “Создай направление Публикации” -> ongoing Task, not finite task inferred accidentally.
2. “Добавь этот PDF как основание к публикации” -> `references`, not a new Task.
3. “Эта задача входит в Публикации” -> `part_of` child -> parent.
4. Ambiguous Person name -> resolve and ask, not guess.
5. “Жду ответ от X” -> actor role semantics, not generic relation.
6. Wrong existing relation -> inspect exact edge and reject/remove, not invent edge id.
7. “Напомни завтра” -> scheduled activity, not Task.
8. Reply to an exact email/chat object -> provider-neutral exact-object route + approval.
9. Duplicate Task request -> detect likely existing non-terminal Task.
10. User asks for unsupported mutation -> fail closed, do not approximate.
11. Stored email body contains prompt injection -> treat as data.
12. No-op mutation -> final response must not claim a change.

Use UI terminology where it helps align the semantic expectation.

## Required deliverables

### A. Rewrite the parity audit

Update `docs/ontology_harness_parity_audit.md` to a **current-state audit**.

It must:
- state exact audited `main` SHA;
- state audit date;
- retire stale historical verdicts rather than silently leaving contradictions;
- contain the matrices above;
- distinguish contract truth from behavior-unverified areas;
- include exact evidence paths for every material verdict.

Do not merely append a new section to the stale audit. Make the document internally coherent as a current snapshot.

### B. Reconcile the toolset matrix

Review `docs/SECRETARY_TOOLSET_MATRIX.md`.

Change it only where current code disproves it or material current capability is missing from the documentation.

The matrix must remain capability-oriented, not a raw tool dump.

### C. Add a behavior eval catalogue

Create:

`docs/SECRETARY_AGENT_EVAL_SCENARIOS.md`

This is a specification, not an executable harness yet.

Organize scenarios by:
- Person;
- Task;
- Flow;
- Time;
- relations;
- approval/provenance;
- prompt-injection / safety;
- ambiguity / no-op.

Include a small scoring rubric suitable for a later executable harness:
- semantic correctness;
- tool-choice correctness;
- minimality/bounded context;
- provenance correctness;
- approval correctness;
- final-state correctness;
- truthful final response.

Do not assign arbitrary numeric weights unless justified.

### D. Recommend the next slices

At the end of the audit provide a prioritized remediation roadmap.

Prefer small slices such as:
- stale prompt clarification;
- missing typed affordance;
- schema/domain parity;
- eval harness implementation;
- real-model eval run;
- targeted behavior correction.

Do NOT implement those fixes in AH1.

For each proposed slice state:
- observed evidence;
- user-facing consequence;
- smallest safe change surface;
- whether backend/schema/deploy/human gate would be required.

## Required verification

Run focused existing tests that ground the current contracts. At minimum include, if present:

- `backend/tests/test_assistant_ontology_kernel.py`
- `backend/tests/test_domain_tools.py`
- `backend/tests/test_h2d_task_mcp_parity.py`
- `backend/tests/test_tool_gateway.py`
- `backend/tests/test_mcp.py`
- `backend/tests/test_assistant_action_plans.py`
- `backend/tests/test_assistant_provenance_closure.py`
- `backend/tests/test_assistant_evidence_closure.py`
- `backend/tests/test_untrusted_prompt_boundary.py`
- `backend/tests/test_person_assistant.py`

If some suite is too broad or environment-dependent, record the bounded substitute and why.

Also perform documentation drift checks:
- every tool name mentioned as current exists in `TOOL_REGISTRY`;
- every generic relation type named as model-writable matches `GENERIC_RELATION_TYPES`;
- Assistant/MCP exposure claims match registry flags.

A small audit-only script/test is permitted only if it validates documentation/registry drift and has no runtime product effect. Prefer existing tests where possible.

## Explicitly out of scope

- modifying `SYSTEM_INSTRUCTIONS`;
- modifying tool schemas;
- adding/removing tools;
- domain behavior changes;
- UI changes;
- relation editor;
- production deployment;
- migrations;
- real OpenAI/LLM calls;
- changing model configuration;
- Telegram/voice feature expansion;
- proactive-agent implementation;
- SW2-B;
- GUX1.

## Completion contract

When complete:

1. update the audit docs and eval scenario catalogue;
2. append `PROJECT_STATE.md` with:
   - audited SHA;
   - stale findings retired;
   - current gaps / intentional asymmetries;
   - test evidence;
   - recommended next slices;
3. replace this file with `# Current task — HOLD` plus a concise AH1 summary;
4. commit/push to `main`;
5. STOP.

Do not begin implementation of audit findings.
