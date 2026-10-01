# Current task — AH2-E executable Secretary agent eval harness

AH2-P, AH2-D, and AH2-T are SOURCE-ACCEPTED. None has been deployed yet.

AH2-E builds the deterministic evaluation harness that will be reused by AH2-M for a real-model run.

This slice does **not** call OpenAI or any external model and does **not** change product runtime behavior.

## Purpose

AH1 produced a human-readable scenario catalogue:

`docs/SECRETARY_AGENT_EVAL_SCENARIOS.md`

It currently defines 15 scenarios across Person, Task, Flow, Time, relations, approval/provenance, prompt injection, and ambiguity/no-op.

Static prompt/tool tests prove contract text. They do not answer:

> Given a user utterance and bounded state, did the agent choose the semantically correct tools, preserve approval/provenance, avoid forbidden mutations, and end in the correct canonical state?

AH2-E must turn that specification into a reusable executable scoring layer.

AH2-M will later plug a real model into this harness. Do not bake a fake-model-only design that must be replaced for AH2-M.

## Architectural boundary

Keep eval code outside production request paths.

Preferred location:

- `backend/evals/secretary_agent/`

A small package is acceptable, for example:

- `models.py` — run/scenario/score records;
- `catalog.py` — executable scenario definitions;
- `recording.py` — tool-call recorder adapter;
- `scorer.py` — deterministic scoring;
- `cli.py` — local score/validate command.

Exact file split is flexible. Keep it coherent and small.

Nothing under `backend/app/` should need runtime behavior changes merely to support the eval.

Do not add a new third-party dependency.

## 1. Canonical eval run format

Define a serializable run record suitable for both:

- deterministic AH2-E fixtures;
- later AH2-M live-model capture.

At minimum capture:

### Run identity

- scenario id;
- utterance;
- run id or stable local identifier;
- optional model/config metadata;
- timestamp may be omitted from deterministic equality checks.

### Tool trace

For each call, in order:

- sequence number;
- tool name;
- arguments;
- success/status;
- result/effect facts needed for scoring;
- whether the call returned/staged `approval_required`;
- optional error category.

Do not store chain-of-thought.

Do not require persisted `AITrace` payload capture for correctness. AH2-M must be able to record this in memory while running the provider.

### Approval/provenance trace

Represent enough to distinguish:

- no approval expected;
- action staged / approval required;
- action executed after approval;
- rejected/not executed;
- immediate annotation when canonically allowed.

Do not equate `approval_required` with execution.

### Final state facts

Use normalized semantic facts, not raw full database dumps.

Examples:
- Task title/status/completion mode;
- planned interval;
- relation type/source/target/state;
- counts of matching Tasks;
- whether a send occurred;
- whether state stayed unchanged.

The run format should allow scenario-specific facts without forcing one giant universal schema.

### Final answer

Store the user-visible answer string for later review.

Never store hidden reasoning.

## 2. Recording tool-runner adapter

Implement an eval-only recorder that can wrap the same callable interface used by the Assistant provider loop.

It must:

- forward the call to a delegate runner;
- record tool name + arguments before/with result;
- record result status/success/output/effect facts;
- preserve delegate behavior exactly;
- forward `commit_model_visible_outputs()` when the delegate exposes it;
- never mutate tool arguments;
- never bypass `PerTurnToolBudget`, allowlists, or approval policy.

This adapter is the bridge AH2-M will use around the real `BoundAssistantToolRunner`.

Add deterministic tests with a fake delegate proving:
- call order preserved;
- arguments preserved;
- statuses/effects captured;
- commit forwarding preserved;
- delegate exceptions/failures are represented without inventing success.

Do not change `BoundAssistantToolRunner` itself unless a tiny read-only interface extraction is strictly necessary. Prefer no production change.

## 3. Executable scenario catalogue

Create executable definitions for every current documented scenario id:

- P1
- T1
- T2
- T3
- F1
- F2
- M1
- M2
- R1
- R2
- R3
- A1
- A2
- S1
- N1

The executable definition must preserve the documented meaning.

For each scenario encode, as applicable:

- category;
- utterance;
- expected required tool/sequence constraints;
- allowed tool alternatives;
- forbidden tools;
- allowed mutation count/scope;
- approval expectation;
- clarification expectation;
- required semantic argument constraints;
- final-state expectations;
- dimensions that require manual answer review.

Do not silently “improve” the scenario meanings.

If a documented scenario is ambiguous to encode, keep the documentation wording and represent that check as manual rather than inventing a rule.

## 4. Deterministic structural scorer

Score these dimensions from the run record where evidence is machine-checkable:

- semantic correctness;
- tool-choice correctness;
- minimality / bounded context;
- provenance correctness;
- approval correctness;
- final-state correctness;
- truthful final response.

### Status vocabulary

Use an explicit non-numeric status enum such as:

- `PASS`
- `FAIL`
- `NOT_APPLICABLE`
- `MANUAL_REVIEW`

Do not use arbitrary weighted scores.

A required `FAIL` makes the scenario fail.

A required `MANUAL_REVIEW` means the run is **incomplete for acceptance**, not passed.

Do not silently count manual review as pass.

### Structural checks

The scorer must support at least:

- required tool before another tool;
- one-of allowed alternatives;
- exact relation type;
- exact direction constraints when symbolic fixture ids are supplied;
- exact actor field use;
- forbidden tool calls;
- maximum mutation count;
- mutation forbidden entirely;
- approval required before execution;
- no execution when approval is pending;
- exact edge id requirement after `list_neighbors`;
- no-op effect vs changed effect;
- final-state fact equality/count checks.

Do not parse free-form assistant prose with brittle keyword heuristics to manufacture a “truthful” pass.

## 5. Final-answer truthfulness policy

For free-form final text:

- the harness may make deterministic failures only when supported by explicit structured evidence and a robust condition;
- otherwise mark `truthful_final_response = MANUAL_REVIEW`.

Examples where structural evidence is enough to demand review:
- pending approval but answer text exists;
- no-op effect;
- ambiguous Person requiring clarification;
- prompt-injection scenario.

Do not build a Russian/English phrase blacklist and call it semantic evaluation.

AH2-M can include a human adjudication step; an LLM-as-judge is not authorized in AH2-E.

Update the scenario doc rubric if needed so this manual-review state is explicit and internally coherent.

## 6. Symbolic fixture references

Do not hardcode UUIDs into scenario definitions.

Allow expectations to refer to symbolic fixture names, for example:

- `task_id`
- `person_id`
- `pdf_id`
- `child_task_id`
- `parent_task_id`
- `edge_id`

A run supplies a symbol→actual-id mapping.

The scorer resolves expected arguments/directions through that mapping.

This is required so the same scenario definition works for deterministic fixtures and AH2-M ephemeral DB state.

## 7. Golden and negative deterministic fixtures

For every scenario, provide at least one **golden structural run** that passes all automatable dimensions and leaves only genuinely textual dimensions for manual review.

Also provide targeted negative fixtures covering the most important failure classes.

At minimum prove the harness catches:

1. T1 creates finite instead of ongoing.
2. T2 creates a duplicate Task.
3. F1 creates a Task from the PDF or uses `related_to`.
4. M1 creates a Task instead of a reminder.
5. M2 writes the work window only as `due_at` or omits one planned boundary.
6. R1 reverses child/parent or uses `depends_on`.
7. R2 uses `related_to` instead of `waiting_on_person_ids`.
8. R3 invents an edge id or calls remove without `list_neighbors`.
9. A1 records `changed=true` for an actual no-op fixture.
10. A2 treats pending approval as executed.
11. S1 performs any mutation.
12. P1 sends before ambiguity is resolved.
13. N1 mutates on a bare name.

Negative fixtures do not need one file per case; table-driven tests are preferred.

## 8. Catalogue drift checks

Add deterministic drift tests between docs and executable catalogue.

At minimum:

- every documented scenario heading id exists in executable catalogue;
- no executable scenario id is undocumented;
- category grouping remains consistent;
- every tool name referenced as executable exists in current `TOOL_REGISTRY`;
- generic relation names used by expectations are from `GENERIC_RELATION_TYPES`;
- current actor role names are from `TASK_ACTOR_ROLES`.

Do not parse arbitrary prose. Parse only stable scenario heading/id structure or keep a simple explicit documented-id manifest.

## 9. CLI / report

Provide a local command that can score a serialized run artifact without model access.

Example shape, exact command is flexible:

`cd backend && python -m evals.secretary_agent.cli score <run.json>`

Output:

- scenario id;
- overall status: PASS / FAIL / INCOMPLETE;
- one row per dimension;
- concise failure/manual-review reasons.

Support machine-readable JSON output as well as a human-readable summary.

The command must not require:
- OpenAI key;
- network;
- production DB;
- production environment variables.

A catalogue validation command is useful:

`... validate-catalog`

Do not add CI deployment behavior in this slice.

## 10. Relationship to production AITrace

The repo already has persisted AI audit traces.

Do not repurpose or weaken their retention/privacy model.

AH2-E run artifacts are explicit local eval artifacts.

The recorder may later be fed from the provider loop directly. It must not depend on long-lived raw AITrace payload retention.

Do not persist eval artifacts automatically in the product database.

## 11. Tests

Run focused tests for:

- run record JSON round-trip;
- recorder forwarding/capture;
- symbolic id resolution;
- ordering constraints;
- alternatives;
- forbidden tools;
- mutation count;
- approval pending vs executed;
- no-op handling;
- final-state fact checks;
- manual-review propagation;
- all 15 golden scenario fixtures;
- required negative cases above;
- docs/catalog drift;
- registry/relation/actor vocabulary drift.

Also keep green:

- `backend/tests/test_ah1_doc_registry_drift.py`;
- `backend/tests/test_assistant_ontology_kernel.py`;
- `backend/tests/test_ah2d_task_tool_descriptions.py`;
- `backend/tests/test_ah2t_planned_interval.py`.

Do not run external LLM calls.

Do not spend AH2-E repairing the known unrelated local action-plan DB fixture or Person identity conflict test unless the new harness directly depends on it. Prefer harness isolation.

## 12. Documentation

Update `docs/SECRETARY_AGENT_EVAL_SCENARIOS.md` only as needed to:

- state that AH2-E now provides an executable harness;
- document `MANUAL_REVIEW` / incomplete semantics;
- link each documented scenario to the same executable id;
- explain that passing deterministic harness checks is not evidence that a model chooses the correct trace.

Do not mark any AH1 `BEHAVIOR_UNVERIFIED` verdict as passed.

Add a short harness usage section.

## Explicitly out of scope

- external/OpenAI calls;
- real-model scoring;
- production deploy;
- migrations;
- prompt changes;
- tool/domain changes;
- UI changes;
- model configuration changes;
- LLM-as-judge;
- auto-approval of production actions;
- relation confirm tool;
- fixing unrelated Person identity debt;
- fixing unrelated action-plan DB fixture debt.

## Completion contract

When complete:

1. record harness architecture, executable scenario coverage, deterministic positive/negative evidence, tests, and limitations in `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD` plus:
   - implementation SHA;
   - harness command;
   - scenario count;
   - positive/negative test summary;
   - explicit “no model was called” statement;
   - production unchanged;
3. commit/push to `main`;
4. STOP.

Do not begin AH2-M or deploy AH2-P/D/T.
