# Current task — AH2-P prompt semantic routing for Task relations

AH1 is Architect-reviewed and ACCEPTED.

This slice is intentionally narrow: update the Assistant system prompt so its routing guidance matches the already-canonical Task relation semantics exposed by the UI and tool contracts.

## Scope

Allowed product change:
- `backend/app/llm/openai_assistant_provider.py` — `SYSTEM_INSTRUCTIONS` only.

Allowed tests:
- existing prompt/ontology tests;
- one small focused prompt-contract test or bounded additions to an existing prompt test.

Do NOT change:
- tool schemas;
- assistant tool definitions/descriptions;
- registry/exposure;
- domain services;
- API;
- database/schema/Alembic;
- client/UI;
- approval/provenance mechanics;
- relation vocabulary;
- model/provider configuration;
- production deployment.

No external LLM calls.

## Why

AH1 found that the tool contracts already encode the correct ontology, but the system prompt is thinner in three places:

1. actor roles are available as typed Task→Person fields but the prompt does not name their meanings;
2. `part_of` is correctly defined by `link_objects`, but the prompt does not explicitly distinguish composition child→parent from dependency;
3. the prompt says how to remove evidence and `related_to`, but does not clearly say that `depends_on`, `part_of`, and actor-role edges are also removed through exact `edge.id` + `remove_relation`.

This can make a model choose a generic `related_to`, create a new Task, reverse `part_of`, or try to “remove” an additive role by omission.

## Canonical semantics to express

Keep the ontology kernel unchanged:

- Person = who;
- Task = commitment / Direction;
- Flow = evidence / context;
- Time = when;
- relations are explicit facts, never inferred.

Add concise routing guidance after Task evidence/materialization guidance and before/around Task lifecycle guidance.

### A. Actor roles are typed Task→Person facts

The prompt must explicitly name:

- `requested_by` — the Person who requested/asked for the Task;
- `delegated_to` — the Person the Task/work is delegated or assigned to;
- `waiting_on` — the Person whose response/action the Task is waiting for;
- `involves` — a Person involved in the Task when no stronger requested/delegated/waiting role is stated.

Required behavior:

- use the typed Task fields on `create_task` / `update_task`;
- do NOT use `link_objects(related_to)` as a substitute for an actor role;
- do NOT silently map one actor role to another;
- do NOT infer a role merely from message frequency, contact prominence, job title, or generic association;
- if the intended role is materially ambiguous, ask a brief clarification.

Do not add keyword routing or Russian-phrase tables to the production prompt. State the semantic meanings.

### B. Task composition vs dependency

Prompt must explicitly distinguish:

- `part_of` = Task composition. Source is the child; target is the parent. Human UI meaning: “child входит в parent”.
- `depends_on` = prerequisite dependency. Source/dependent depends on target/prerequisite.

Required behavior:

- use `link_objects(relation_type="part_of")` only for explicit composition intent;
- never reverse child/parent;
- do not treat composition as dependency;
- do not infer `part_of` merely because two Tasks share a topic, Direction, Person, or evidence;
- do not invent a second parent; domain validation remains authoritative.

The prompt does not need to duplicate every backend validation rule; it must teach the semantic direction and distinction.

### C. Relation removal uses exact edge identity

Generalize the existing removal sentence.

For removable semantic Task relations:
- `references`;
- `related_to`;
- `depends_on`;
- `part_of`;
- actor-role edges `requested_by`, `delegated_to`, `waiting_on`, `involves`;

the prompt must say:

1. inspect `list_neighbors` to obtain the exact `edge.id`;
2. if several edges plausibly match and intent is ambiguous, clarify;
3. call `remove_relation(edge_id)`;
4. never invent an edge id;
5. never try to remove an additive relation by omitting it from `update_task` lists;
6. do not use a different relation mutation as a substitute.

Do not imply that protected/source/system edges are always removable. The tool/domain layer remains authoritative and fail-closed.

### D. Preserve existing behavior

Do not weaken or duplicate these existing prompt rules:

- retrieve vs query routing;
- duplicate Task avoidance;
- evidence is Flow, not automatic Task materialization;
- finite vs ongoing completion mode;
- reminder vs Task;
- Person resolution before communication;
- exact-object reply routing;
- unsupported mutation rule;
- untrusted stored data boundary;
- approval protocol;
- deterministic finalization/no-op truthfulness.

Prefer a compact addition. Avoid making `SYSTEM_INSTRUCTIONS` materially more verbose than needed.

## Focused tests

Add/adjust deterministic tests that do not call a model.

At minimum prove:

1. ontology kernel still precedes routing guidance.
2. the prompt contains all four exact actor role names:
   - `requested_by`
   - `delegated_to`
   - `waiting_on`
   - `involves`.
3. prompt text explicitly says actor roles use typed Task fields rather than generic `related_to`.
4. prompt contains `part_of` and states source child → target parent semantics.
5. prompt distinguishes `part_of` from `depends_on`.
6. removal guidance covers `depends_on`, `part_of`, and actor-role edges through `list_neighbors` + exact `edge.id` + `remove_relation`.
7. additive update lists are not described as a removal mechanism.
8. existing completion-mode, reminder, unsupported-mutation, approval, and untrusted-data markers remain present.

Run at minimum:
- `backend/tests/test_assistant_ontology_kernel.py`;
- the new/changed prompt-contract test;
- `backend/tests/test_ah1_doc_registry_drift.py`.

Also run a bounded relevant contract set that does not require the known-broken local action-plan DB path, preferably:
- `backend/tests/test_domain_tools.py`;
- `backend/tests/test_task_relations.py` if present.

Do not spend this slice repairing unrelated baseline failures.

## Documentation / ledger

AH2-P is a product prompt change, so after implementation:

- record exact prompt additions and tests in `PROJECT_STATE.md`;
- note the known AH1 baseline test debt separately:
  - action-plan local DB FK failures;
  - Person owned-identity conflict test disagreement;
- do not claim behavior quality is proven. Static prompt tests only prove the contract text exists.

Do not update the AH1 audit verdicts from `BEHAVIOR_UNVERIFIED` to `ALIGNED` merely because the prompt text changed. Real behavior stays unverified until AH2-M.

## Deployment / human gate boundary

This changes backend Assistant prompt behavior.

After source implementation/test review:
- do NOT deploy production automatically;
- no migration is expected;
- a separate schema-neutral backend rollout authorization will be required before live human/model verification.

No client build is required for a prompt-only backend slice.

## Completion contract

When complete:

1. update `SYSTEM_INSTRUCTIONS` only as scoped;
2. add/update focused deterministic tests;
3. append implementation/test evidence to `PROJECT_STATE.md`;
4. replace this file with `# Current task — HOLD` plus:
   - implementation SHA;
   - exact prompt-routing summary;
   - test counts/results;
   - production unchanged;
   - rollout/human/model verification pending;
5. commit/push to `main`;
6. STOP.

Do not begin AH2-D, AH2-T, AH2-E, AH2-M, or AH2-C.
