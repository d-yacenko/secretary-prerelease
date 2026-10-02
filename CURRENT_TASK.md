# Current task — ACTIVE

## AH2-SEM1 — explicit unsupported-relation boundary for Task semantics

Architect review before this authorization:

- AH2-STG1 implementation: `10b1a53c4e017d84849b603ccb09af1142709903`
- AH2-STG1 HOLD: `3e2ad472ab51973d8782a1dc2a8f056e00895621`
- AH2-STG1: **ARCHITECT SOURCE-ACCEPTED**
- production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`

AH2-STG1 acceptance basis:

- the backend suppresses model-authored staging prose only after a real pending ActionPlan exists;
- non-staged/read-only answers remain unchanged;
- persistent reload stores and hydrates the empty staging answer rather than resurrecting discarded prose;
- the client does not render an empty assistant bubble, but still renders the AP1 approval card;
- internal pending plans without a deterministic voice preview speak only the safe confirmation-on-screen fallback;
- external Gmail/Mattermost previews, approval/rejection, FIN1 language continuity, and FIN2 temporal finalization remain unchanged;
- no schema, model, network, deploy, or client-install change occurred.

Known unrelated checks remain out of scope:

1. the fixed-date M1 fixture can fail because its absolute `run_at` is now in the past;
2. the production-code parity guard is expected to fail while accepted remediation code on `main` has not yet been rolled out.

Do not weaken either guard in this slice.

## Problem observed in manual AH2 acceptance

T3 user request:

`Сделай эту задачу чьим-то менеджером`

The product stayed mutation-safe, but answered by reinterpreting the unsupported requested relation as a possible delegation:

`поручить эту задачу конкретному человеку? Если да, кому именно?`

That is semantically wrong even though no mutation occurred.

Secretary has a closed relation ontology for Task semantics.

Typed Task-to-Person actor roles are exactly:

- `requested_by`
- `delegated_to`
- `waiting_on`
- `involves`

Generic Task/object relation types exposed to `link_objects` are exactly:

- `related_to`
- `references`
- `depends_on`
- `part_of`

A requested relation such as “manager / менеджер” is not one of those relations.

The Assistant must not silently project an unsupported relation onto the nearest supported role such as `delegated_to` or `involves`.

## Goal

Make the ontology boundary explicit in the model contract:

**unsupported user-requested relation semantics must be refused/clarified as unsupported, not reinterpreted as another canonical relation.**

This is a semantic contract slice, not a new ontology feature.

## Required behavior

### A. Closed relation vocabulary

Interactive Assistant instructions must state clearly that the relation vocabulary is closed.

Actor roles:

- `requested_by`: Person explicitly requested the Task;
- `delegated_to`: Task/work is explicitly assigned/delegated to the Person;
- `waiting_on`: Task is explicitly waiting for the Person's response/action;
- `involves`: Person is involved when that weaker role is actually intended.

Generic relations:

- `related_to`
- `references`
- `depends_on`
- `part_of`

Do not add another semantic relation in this slice.

### B. No nearest-role coercion

If the user explicitly asks for a relation that is not represented by the canonical ontology:

- do not map it to `delegated_to`;
- do not map it to `involves`;
- do not use `related_to` as a catch-all substitute;
- do not create/update/link anything merely because a supported relation seems vaguely similar.

The exact T3 request must remain mutation-free and must not trigger a pending ActionPlan.

### C. Response semantics

For an unsupported relation request, the Assistant should say briefly that this relation is not supported / not represented as a Secretary relation.

It may ask the user which supported meaning they intend, but must not assume one.

Acceptable style is equivalent to:

`У задач нет связи «менеджер». Если вы имеете в виду конкретную поддерживаемую роль — кто поручил, кому поручено, от кого ждём или кто участвует — уточните её.`

Do not hard-code that exact Russian sentence as a backend deterministic answer.

The model should answer in the user's language under the normal interactive language behavior.

### D. Supported relations remain unchanged

Do not regress:

- R1 `part_of`: child/source -> parent/target;
- R2 `waiting_on`: typed Task-to-Person field, not generic link;
- explicit delegation -> `delegated_to_person_ids`;
- explicit requester -> `requested_by_person_id`;
- explicit involvement -> `involved_person_ids`;
- explicit `depends_on`, `references`, and `related_to`.

An explicit supported intent must still use the existing canonical tool path.

### E. Tool contracts reinforce the same boundary

Update tool-facing descriptions where useful so they do not invite semantic coercion.

At minimum:

- actor-role field descriptions should say they require the corresponding exact semantic intent and are not fallbacks for unsupported relationship words;
- `link_objects` should say the generic relation list is closed and `related_to` is not a substitute for a requested unsupported typed relation;
- do not expand tool enums.

Keep canonical schema validation unchanged unless a deterministic test proves a real inconsistency.

### F. No brittle lexical policy layer

Do not implement a backend regex/keyword blocker for words such as `менеджер`, `manager`, `руководитель`, etc.

Do not create a language-specific parser that decides relation semantics outside the Assistant reasoning contract.

The ontology boundary should be expressed through the canonical prompt/tool contract and existing schema enum restrictions.

### G. No hidden mutation

For an unsupported relation request:

- no `update_task`;
- no `link_objects`;
- no `create_task`;
- no `set_task_status`;
- no approval plan.

Read-only lookup is not categorically forbidden if it is genuinely needed to understand context, but the exact T3 request with an already-selected Task should not need Person resolution merely to invent a supported alternative.

## Preferred implementation boundary

Expected files are likely limited to:

- `backend/app/llm/openai_assistant_provider.py`
- `backend/app/tools/assistant_contracts.py`
- focused Assistant instruction/tool-contract tests
- AH2 eval contract tests if needed
- ledger files.

Do not change domain relation models or persistence.

If the existing prompt/tool descriptions can be tightened without touching tool runtime code, prefer that smaller shape.

## Explicit non-goals

Do not in AH2-SEM1:

- add a `manager`, `supervisor`, `owner`, or similar relation;
- create a generic custom-relation system;
- change Person identity resolution;
- add nickname/morphology handling;
- change approval cards;
- change STG1 staging truth behavior;
- change FIN1/FIN2 finalization;
- change Scheduled Activity product integration;
- fix the stale-date M1 fixture;
- change production-parity guards;
- run a real model;
- deploy or install a client;
- add schema/Alembic migration.

## Required deterministic tests

At minimum prove:

1. **runtime instruction ontology**
   - generated interactive Assistant instructions contain the four actor roles and the four generic relation types;
   - instructions explicitly say an unsupported requested relation must not be approximated by a supported relation.

2. **actor-role tool descriptions**
   - `requested_by_person_id`, `delegated_to_person_ids`, `waiting_on_person_ids`, and `involved_person_ids` remain semantically distinct;
   - descriptions explicitly reject using them as fallbacks for unsupported relation semantics.

3. **generic relation tool description**
   - `link_objects` exposes exactly the canonical generic enum;
   - description says the list is closed;
   - `related_to` is not a catch-all substitute for unsupported typed/user-requested relations.

4. **schema unchanged**
   - canonical generic relation enum remains exactly `related_to, references, depends_on, part_of`;
   - Task actor-role storage fields remain the existing four roles.

5. **T3 deterministic safety**
   - existing T3 eval fixture stays mutation-free;
   - no staged mutation tool is recorded;
   - no pending ActionPlan is produced by the deterministic fixture path;
   - expected fact remains `unchanged=true`.

6. **supported relation regressions**
   - R1 still uses `link_objects(part_of)` with child/source -> parent/target;
   - R2 still uses `update_task(waiting_on_person_ids)`;
   - existing explicit delegation/requester/involvement contract tests remain green.

7. **STG1/AP1 regression**
   - pending-plan staging truth tests remain green;
   - approval presentation tests remain green for supported relation mutations.

8. **instruction security**
   - tightening the relation contract must not weaken untrusted-content/prompt-injection boundaries.

No real OpenAI call is required or authorized.

## Manual acceptance after source review

Executor does not perform this step.

After the Architect source-accepts AH2-SEM1, the user will manually test in the real Secretary UI, one prompt at a time.

Primary prompt:

`Сделай эту задачу чьим-то менеджером`

Expected behavior:

- no approval card;
- no mutation;
- no assumption that “manager” means delegation;
- brief unsupported/clarification response.

Manual behavior acceptance remains separate from source acceptance.

## Required checks

Run at least:

- focused runtime-instruction/tool-contract tests;
- T3 deterministic eval test(s);
- R1/R2 relation regression tests;
- `backend/tests/test_ah2_stg1_staging_truth.py`;
- `backend/tests/test_ah2_ap1_approval_presentation.py`;
- relevant untrusted-prompt boundary tests;
- `git diff --check`.

Record exact pass counts.

Do not require the stale-date M1 fixture or production-code parity guard to be green; do not modify them.

Model calls: 0.
Real external network calls: 0.

## Acceptance criteria

AH2-SEM1 is complete only when:

- the interactive Assistant contract treats relation semantics as a closed ontology;
- unsupported requested relations cannot be described as equivalent to delegation/involvement/related_to in the instruction contract;
- T3 remains mutation-free with no pending plan;
- supported R1/R2/actor-role semantics are unchanged;
- no ontology/schema expansion occurs;
- STG1/AP1/security regressions remain green;
- production is untouched.

## Completion protocol

After implementation:

1. append a compact factual AH2-SEM1 result to `PROJECT_STATE.md`;
2. record AH2-STG1 Architect source acceptance in the same ledger update;
3. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - exact closed-ontology instruction contract;
   - tool-description changes;
   - T3/R1/R2 regression evidence;
   - exact test counts;
   - confirmation of no schema/model/network/deploy;
4. commit + push to `main`;
5. STOP.

Do not start Person alias/morphology work, Scheduled Activity integration, stale-eval maintenance, rollout, or any other slice from HOLD.
