# Current task — AH2-D align Task tool descriptions with canonical profile semantics

AH2-P is SOURCE-ACCEPTED. Do not deploy it yet.

This slice is narrow and model-facing: improve Assistant tool descriptions so the model can correctly interpret Task profile output and the typed actor/dependency fields that already exist.

## Scope

Allowed product change:
- `backend/app/tools/assistant_contracts.py` description strings and per-field JSON-schema `description` text only.

Allowed tests:
- deterministic tool-contract tests;
- existing ontology/tool schema tests.

Do NOT change:
- Pydantic input/output field sets;
- runtime domain services;
- registry/exposure flags;
- tool permissions;
- API;
- database/schema/Alembic;
- client/UI;
- prompt text in `openai_assistant_provider.py`;
- production deployment.

No external LLM calls.

## Why

AH1 found two remaining description-level weaknesses:

1. `get_task_profile` returns more semantic information than its tool description advertises:
   - `completion_mode`;
   - `parent_task`;
   - actor roles;
   - `depends_on` and dependent tasks;
   - `planned_start_at` / `planned_end_at`;
   - evidence;
   - operational projection.

2. `create_task` / `update_task` currently expose actor/dependency JSON fields without per-field semantic descriptions. The top-level tool description only says those lists are additive. That makes the model rely disproportionately on the system prompt.

The goal is not to duplicate the whole prompt. The goal is to make every field/tool self-describing enough that a model presented with the schema alone still sees the canonical meaning.

## A. `get_task_profile` description

Update the tool description to explicitly say that the profile returns:

- lifecycle `status`;
- `completion_mode`:
  - `finite` = completable Task;
  - `ongoing` = continuing Direction/Activity;
- confirmed `parent_task` for `part_of` composition, when present;
- `requested_by`, `delegated_to`, `waiting_on`, `involves`;
- `depends_on` plus dependent Tasks;
- `planned_start_at` / `planned_end_at`;
- evidence;
- derived read-only `operational.operational_state`.

Preserve existing truth:
- lifecycle `status` is not the same as derived `operational_state`;
- operational projection is deterministic;
- proposed relations do not affect operational state;
- overdue may coexist with blocked/waiting/delegated;
- the tool does not mutate.

Keep this concise. Do not enumerate every response JSON key if that makes the description noisy.

## B. Typed actor-field descriptions

Add per-field JSON-schema descriptions to both `create_task` and `update_task` definitions.

Required semantics:

### `requested_by_person_id`
The Person who explicitly requested/asked for the Task.

Rules:
- Task→Person typed actor role;
- use only when that role is actually stated/known;
- not a generic “related person”.

### `delegated_to_person_ids`
Persons to whom the Task/work is delegated or assigned.

Rules:
- Task→Person typed actor role;
- additive list;
- not equivalent to `waiting_on` or `involves`.

### `waiting_on_person_ids`
Persons whose response/action the Task is waiting for.

Rules:
- Task→Person typed actor role;
- additive list;
- not a delegation substitute.

### `involved_person_ids`
Persons involved in the Task when no stronger requested/delegated/waiting role is intended.

Rules:
- Task→Person typed actor role;
- additive list;
- use as the weaker participation role, not as a catch-all when a stronger role is known.

### `depends_on_task_ids`
Tasks that are prerequisites for this Task.

Rules:
- source/current Task depends on each target/prerequisite Task;
- additive list;
- not `part_of` composition.

Use the same wording on create and update unless a tiny create/update distinction is required.

Do not introduce Russian trigger phrases into tool descriptions; describe the semantics.

## C. Evidence field description

AH1 did not mark this as a gap, but while touching field descriptions, make `evidence_object_ids` self-describing if it currently lacks description:

- Flow/evidence objects attached via `references`;
- additive;
- not Task materialization;
- not removal.

Do not add unrelated field prose just for completeness.

## D. Preserve canonical boundaries

Descriptions must not imply:

- actor roles can be written via `link_objects`;
- `part_of` is an actor/dependency field;
- omission removes an existing relation;
- proposed relations count as confirmed profile state;
- `operational_state` is writable;
- planned interval is writable yet — AH2-T handles that later;
- generic arbitrary relation names are valid.

The description may say planned interval is returned/readable even though current create/update tools cannot write it. That asymmetry is intentional until AH2-T.

## Deterministic tests

Add/update focused tests that inspect the actual tool definitions.

At minimum prove:

1. `get_task_profile` description mentions:
   - lifecycle `status`;
   - `completion_mode`;
   - `parent_task` / composition context;
   - all four actor roles;
   - dependencies;
   - planned interval;
   - evidence;
   - operational state;
   - read-only / non-mutating nature.

2. Both `create_task` and `update_task` field schemas contain descriptions for:
   - `requested_by_person_id`;
   - `delegated_to_person_ids`;
   - `waiting_on_person_ids`;
   - `involved_person_ids`;
   - `depends_on_task_ids`;
   - `evidence_object_ids`.

3. Actor-field descriptions contain the canonical role distinction and do not mention `related_to` as the write path.

4. `depends_on_task_ids` explicitly says dependency/prerequisite and not composition.

5. Evidence field remains additive and does not say omission removes links.

6. No input field set changes:
   - exact tool parameter property names before/after remain the same;
   - required sets remain the same.

7. Existing `link_objects` description still carries canonical:
   - `related_to`;
   - `references`;
   - `depends_on`;
   - `part_of`;
   - actor roles stay typed Task fields.

Run at minimum:

- focused new/changed tool-description tests;
- `backend/tests/test_assistant_ontology_kernel.py`;
- `backend/tests/test_domain_tools.py`;
- `backend/tests/test_ah1_doc_registry_drift.py`;
- `backend/tests/test_task_relations.py`.

If existing tool-definition contract tests cover the same files, include them.

Do not repair unrelated baseline action-plan or Person identity failures in AH2-D.

## Documentation / audit handling

Do not rewrite the AH1 audit yet.

After AH2-D implementation:
- append `PROJECT_STATE.md` with exact description changes and tests;
- state that the AH1 “tool description weak” finding is addressed at the contract-text level;
- keep behavior verdict `BEHAVIOR_UNVERIFIED` until AH2-M.

Do not change `SECRETARY_AGENT_EVAL_SCENARIOS.md` unless an exact factual reference to a tool description became false. Prefer no docs change in this slice.

## Deployment strategy

Do NOT deploy AH2-D automatically.

Architect intent:
- AH2-P and AH2-D are both model-facing backend contract text;
- AH2-T is the next likely product parity slice;
- prefer one later schema-neutral rollout of the reviewed AH2-P + AH2-D + AH2-T stack before live model/human verification.

No client build is required.

## Completion contract

When complete:

1. change only scoped description text/tests;
2. append `PROJECT_STATE.md` with implementation SHA and test evidence;
3. replace this file with `# Current task — HOLD` plus:
   - implementation SHA;
   - exact description changes;
   - test results;
   - production unchanged;
   - rollout pending;
4. commit/push to `main`;
5. STOP.

Do not begin AH2-T, AH2-E, AH2-M, or AH2-C.
