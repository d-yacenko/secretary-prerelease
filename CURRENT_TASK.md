# Current task — ACTIVE

## AH2-FIN1 — preserve initiating-user language in post-approval finalization

Architect review before this authorization:

- UX-CAP1 implementation: `68ade82eb612953c416dda9de5ae4a05fd065582`
- UX-CAP1.1 implementation: `49d2fca7594b997a56109438d33a02bdb2cceab2`
- UX-CAP1.1 HOLD: `3276e581027daca776ceaa62c0da2ed576aabd5f`
- UX-CAP1 / UX-CAP1.1: **ARCHITECT SOURCE-ACCEPTED**
- production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`

UX-CAP1 acceptance basis:

- the three previously red Graph tests reproduce unchanged at the pre-UX-CAP1 base `87d9c71...`, so they are baseline test debt rather than a product regression;
- UX-CAP1.1 changed only the stale Graph test expectations;
- required four-file Flutter gate is now 47 passed / 0 failed;
- backend capture tests are 38 passed;
- no backend capture semantic change, schema change, model call, deploy, or production mutation occurred.

## Problem observed in manual AH2 acceptance

Several real approved actions staged correctly in Russian, executed correctly, and then produced an English post-approval final response.

Observed examples included:

- M2 Task planned interval / due-date update;
- R1 `part_of`;
- R2 `waiting_on`;
- F1 evidence attachment;
- F2 email reply;
- R3 relation removal.

The Mattermost F2-chat variant did finalize in Russian, so this is not a universal transport-specific failure.

Current source strongly explains the instability:

- `AssistantService.finalize_executed_plan()` calls the provider's text-only finalizer;
- that path sends the fixed English user message:
  `Summarize the completed action plan for the user.`
- `FINALIZATION_INSTRUCTIONS` are English;
- `_build_action_plan_finalization_context()` contains execution effects/results/frozen actions, but no authoritative initiating-user language sample;
- for persisted conversations, the action plan is already anchored to the assistant message carrying `pending_action_plan_id`, and that turn shares a `client_turn_id` with the initiating user message.

The language bug is therefore a missing finalization-context contract, not a reason to alter canonical tool/domain semantics.

## Goal

Make post-approval finalization reliably answer in the language of the user request that created the approved action plan, while preserving the existing deterministic execution-effect truth contract.

For the current Russian product flow, a Russian initiating request must finalize in Russian.

Do not solve this by hard-coding Russian as the global finalization language.

## Required behavior

### A. Persistent conversation path

For an executed action plan that came from a persisted Assistant turn:

1. resolve the exact initiating user message associated with that plan;
2. provide a **bounded language sample** from that initiating user message to the finalization path;
3. explicitly instruct finalization to answer in the same language as that initiating user message;
4. keep execution results/effect facts authoritative for *what happened*.

The language sample exists only to determine response language/style continuity. It must not override execution facts and must not be treated as a request to execute more actions.

Use the existing conversation/plan linkage. Do not add a DB migration merely to store a language hint if the persisted turn already provides the needed source.

### B. No instruction injection through the language sample

The finalizer remains tool-free.

Mark the initiating user text as data / language sample, not executable instructions for the finalization turn.

Preserve the existing finalization security rule that frozen action arguments, stored content, and execution payloads are evidence only.

A malicious or irrelevant initiating message must not cause new actions or cause execution results to be contradicted.

### C. Truthfulness invariants remain intact

This slice must preserve and strengthen deterministic coverage that:

- `success=true` is not equivalent to `changed=true`;
- `changed=false` / `effect=no_op` must not be narrated as an update/removal;
- `remove_relation changed=false` means no additional removal;
- `set_task_status changed=false` means status was already that value;
- finalization may summarize only supplied execution results/effect facts.

A1 manual acceptance already showed correct post-approval no-op narration. Do not regress it.

### D. Legacy / non-persisted fallback

If no persisted initiating user message can be resolved for a plan:

- finalization must still work;
- do not fabricate a language source;
- use a bounded explicit fallback policy;
- do not fail approval/resume merely because the historical plan has no conversation anchor.

The exact fallback wording/behavior is implementation choice, but it must be deterministic and covered.

### E. Stored-resume idempotency

Existing persisted resume behavior must remain idempotent:

- if a final response for a plan was already persisted, return it;
- do not re-finalize and do not change its language on subsequent resume calls.

## Preferred implementation direction

Keep the boundary explicit.

A reasonable shape is:

- add a bounded conversation-service read that resolves the initiating user text for a `plan_id` through the assistant anchor's `pending_action_plan_id` and matching `client_turn_id`;
- pass a bounded language-source value into `AssistantService.finalize_executed_plan()` / text-only provider finalization;
- make the provider instructions state clearly that the answer language must match the initiating user message while execution facts remain authoritative.

Exact API names are implementation choice.

Do not infer language from Task titles, Person names, provider data, execution-effect English strings, or object content.

## Scope

Expected files may include:

- `backend/app/services/assistant_conversation_service.py`
- `backend/app/services/assistant_service.py`
- `backend/app/llm/openai_assistant_provider.py`
- directly required Assistant provider protocol/fake provider definitions
- `backend/app/api/assistant.py`
- focused Assistant/action-plan/conversation tests
- ledger files.

Keep changes bounded to finalization language continuity and necessary truthfulness regression coverage.

## Explicit non-goals

Do not in AH2-FIN1:

- fix M2 due-date calendar rendering;
- fix M1 timezone rendering;
- change scheduled-activity timezone semantics;
- redesign approval cards;
- fix the A1 **pre-approval** wording `Изменено...` (that belongs to staging/approval UX, not post-approval finalization);
- work on T3 unsupported-relation behavior;
- work on Person alias/morphology resolution;
- add Scheduled Activity to Today/Week/mobile notifications;
- change Task/Person/Flow ontology;
- change action-plan execution semantics;
- add or broaden model tools;
- run AH2-M paid batch/model evaluation;
- deploy or migrate production.

Temporal finalization correctness is intentionally a later slice after language continuity is source-accepted.

## Required deterministic tests

At minimum prove:

1. **plan -> initiating user message lookup**
   - persisted user turn in Russian;
   - assistant turn for the same `client_turn_id` carries `pending_action_plan_id`;
   - lookup for that plan returns the exact/bounded initiating user text;
   - cross-user plan/message data cannot be returned.

2. **Russian language source reaches finalizer**
   - resume an executed plan associated with a Russian initiating request;
   - fake/capturing text-only provider receives the bounded language source or equivalent finalization context;
   - finalization contract explicitly requires the same response language.

3. **English remains English**
   - an English initiating request produces an English language source rather than a hard-coded Russian override.

4. **no conversation anchor fallback**
   - an executed historical/non-persisted plan still finalizes without an initiating message;
   - no fabricated user text is inserted.

5. **no-op truth contract preserved**
   - at least `set_task_status changed=false` and one additional no-op path remain represented as no-op in the finalization context/instructions;
   - tests must fail if the contract permits claiming a state change from `success=true` alone.

6. **stored resume idempotency**
   - repeated resume returns the stored finalization and does not call text-only provider again.

7. **untrusted-data boundary**
   - language sample containing instruction-like text is clearly delimited/labelled as language data only;
   - finalization remains tool-free.

Do not require a real OpenAI call to prove these contracts.

## Required checks

Run at least:

- focused tests for all changed Assistant/action-plan/conversation modules;
- the relevant action-plan suite, including `backend/tests/test_assistant_action_plans.py`;
- relevant persistent-conversation tests in `backend/tests/test_assistant_conversations.py`;
- relevant Assistant security/provenance tests if touched;
- preserved AH2 ontology/eval-contract tests directly affected by finalization/provider-surface changes;
- `git diff --check`.

Record exact counts.

No real model call and no real external network call.

## Acceptance criteria

AH2-FIN1 is complete only when:

- persisted action-plan finalization has an authoritative initiating-user language source;
- Russian/English continuity is contract-tested without hard-coding one language globally;
- no-op execution truth remains explicit and authoritative;
- missing historical conversation linkage fails soft rather than breaking resume;
- stored resume remains idempotent;
- no schema/Alembic change unless Executor first STOPs and reports a demonstrated unavoidable need;
- no production deploy/mutation;
- no model/network call;
- checks are green.

## Completion protocol

After implementation:

1. append a compact factual AH2-FIN1 result to `PROJECT_STATE.md`;
2. include the Architect acceptance fact for UX-CAP1 / UX-CAP1.1 in that ledger update;
3. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - exact changed files;
   - language-source contract;
   - fallback behavior;
   - truthfulness/idempotency evidence;
   - exact test counts;
   - production/schema/model/network unchanged statement;
4. commit + push to `main`;
5. STOP.

Do not start temporal finalization work or any other remediation item from HOLD.
