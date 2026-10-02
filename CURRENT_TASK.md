# Current task — ACTIVE

## AH2-STG1 — deterministic pre-approval truth boundary for staged action plans

Architect review before this authorization:

- AH2-AP1 implementation: `09ab0309a6147320340a2468e4fbb751e34df566`
- AH2-AP1 HOLD: `18e8776abf613d54fe511eaa02ecb94c5ae33fbc`
- AH2-AP1: **ARCHITECT SOURCE-ACCEPTED**
- production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`

AH2-AP1 acceptance basis:

- new internal plans store a bounded server-authored semantic presentation snapshot in the existing JSON action payload;
- `create_plan` removes any supplied presentation and rebuilds it from canonical user-owned state;
- snapshot survives reload and does not change after later object rename;
- legacy plans without presentation still load and execute;
- Flutter prefers semantic labels over raw UUID/tool-name labels;
- execution ignores presentation and still reads only `tool_name + arguments`;
- tests/analyze are green for the authorized slice;
- no schema, model, network, deploy, or client-install change occurred.

Two known red checks are outside AH2-AP1 and are not to be repaired in this slice:

1. the fixed-date M1 scripted fixture now uses a `run_at` that is in the past relative to current runtime;
2. `test_product_code_matches_production_release` is expected to fail while accepted remediation code on `main` has not yet been rolled out to `production`.

Do not weaken those guards just to make this slice green.

## Problem observed in manual acceptance

A1 exposed a pre-approval truth contradiction.

The user asked to set an already-open Task to `open`.

Before approval, Secretary said essentially:

- “Изменено статус ... на open.”
- and then immediately admitted the change had not yet been executed and awaited approval.

The card correctly represented a pending ActionPlan, and after approval finalization correctly reported `changed=false`.

The defect is therefore **staging narration**, not action execution or finalization.

Current architecture still allows this because:

- the model stages a mutating action;
- the same model turn also authors free-form assistant prose;
- `AssistantService` persists/returns that free-form answer even when a real `pending_action_plan` exists;
- AP1 now gives the approval card a frozen semantic snapshot, so the model-authored prose is no longer needed to explain the action.

A staged action must never be narrated as already completed.

## Goal

Make pending ActionPlan truth deterministic:

**When a real pending ActionPlan exists, the user-facing truth source for the proposed mutation is the pending-plan card / semantic presentation, not model-authored free prose.**

The pre-approval turn must not contain a model-authored claim that the mutation already happened.

This must be guaranteed structurally, not merely encouraged by prompt wording.

## Core behavior

### A. Staged mutation response

If an interactive Assistant turn ends with one or more staged actions and a real `pending_action_plan` is persisted:

- do not expose the model's free-form final answer as user-facing mutation status;
- the response must make no claim that create/update/send/link/delete/status-change already happened;
- the approval card remains the semantic description of what is proposed;
- no additional model call is allowed.

Preferred deterministic behavior:

- return/persist an empty assistant prose body for the staging turn;
- let the approval card/status communicate “requires confirmation”.

If current client rendering requires a small deterministic non-model phrase for layout/accessibility, keep it client-owned and state-only, e.g. equivalent to “Требует подтверждения”; do not generate action semantics in free prose because AP1 already owns those semantics.

Do not hard-code Russian on the backend as the canonical assistant answer.

### B. Non-staged turns unchanged

If no real pending ActionPlan exists:

- keep the current model-authored answer path unchanged;
- clarification/read-only/search/summarization responses continue normally.

This slice must not blank ordinary Assistant answers.

### C. Persistent conversation behavior

For a staged turn in persistent mode:

- stored assistant message content must follow the same truth-safe staging contract;
- reloading the conversation must not resurrect the discarded contradictory model prose;
- the pending-plan card must hydrate exactly as before.

The raw provider answer may remain available only in existing AI trace/audit telemetry if already captured there. Do not add a new DB field merely to preserve discarded staging prose.

### D. Approval / rejection / finalization

- approval execution semantics are unchanged;
- rejection semantics are unchanged;
- after execution, the separate resume/finalization message remains the authoritative post-execution prose;
- FIN1 language continuity and FIN2 temporal finalization remain unchanged;
- AP1 semantic approval presentation remains unchanged.

A completed plan should not cause the old staging prose to reappear after reload.

### E. Voice behavior

For a pending plan:

- external send/message actions that already have deterministic voice previews keep using those previews;
- internal plans without a deterministic voice preview must not speak discarded model-authored staging prose;
- keep the existing safe fallback equivalent to “Это действие нужно подтвердить на экране.”

Do not add voice approval for new internal action types in this slice.

### F. Truth source hierarchy

For pending plans:

1. frozen executable `tool_name + arguments` = execution contract;
2. AP1 frozen semantic presentation = approval-card explanation;
3. pending status = truth that execution has not happened;
4. model free prose = **not a user-facing execution-status source**.

For executed plans:

1. execution result/effect facts = state truth;
2. FIN2 verified temporal display facts = user-facing time/date wording;
3. FIN1 initiating-user language sample = language continuity.

Do not blur pending and executed truth boundaries.

## Preferred implementation boundary

Keep the fix small and explicit.

Likely touch points:

- `backend/app/services/assistant_service.py`
- persistent conversation tests/service only if needed
- `client/lib/assistant/assistant_message_body.dart` or the nearest message rendering point if empty staged prose needs graceful rendering
- `client/lib/assistant/assistant_controller.dart` only for voice fallback verification if needed
- focused tests.

A reasonable server shape is:

1. obtain the provider result;
2. persist the ActionPlan from staged actions;
3. if `pending_action_plan != null`, replace the user-facing answer with the deterministic staging-safe representation (prefer empty string);
4. persist/return that safe answer.

Do not inspect natural-language verbs to guess whether the model claimed execution. Do not regex-rewrite Russian/English prose.

## Explicit non-goals

Do not in AH2-STG1:

- change AP1 approval presentation schema/copy except what is strictly required to render an empty staging body cleanly;
- change post-approval finalization;
- change action-plan execution;
- change T3 unsupported relation behavior;
- change Person alias resolution;
- add Scheduled Activity to Today/Week/mobile;
- fix the expired absolute-date M1 eval fixture;
- change the production-parity guard;
- deploy backend or install a client;
- add schema/Alembic migration;
- call a real model or external provider.

## Required deterministic tests

At minimum prove:

1. **A1 hostile staging prose is suppressed**
   - fake provider returns a response equivalent to “Статус изменён на open”;
   - same turn stages `set_task_status`;
   - returned Assistant result contains a real pending plan;
   - user-facing answer does not expose that model prose;
   - plan/card still contains the AP1 semantic `open -> open` snapshot.

2. **generic mutation claim is suppressed**
   - fake provider returns “Создано/Отправлено/Удалено” while staging a mutation;
   - no such model prose reaches the user-facing staging answer.

3. **read-only answer preserved**
   - provider returns a normal read-only/clarification answer and stages no action;
   - answer remains unchanged.

4. **persistent reload**
   - staged turn is persisted;
   - stored assistant content follows the safe staging contract;
   - conversation reload returns the same safe content plus hydrated pending plan;
   - discarded provider prose does not reappear.

5. **legacy/non-persistent mode**
   - if the API still supports legacy history mode, a staged turn uses the same safe answer contract there too.

6. **approval finalization unaffected**
   - execute an approved staged plan;
   - resume/finalization still appends/returns the real post-execution answer;
   - the staging message remains safe.

7. **rejection unaffected**
   - rejected plan remains rejected and does not acquire post-execution claims.

8. **voice internal-plan fallback**
   - pending internal plan without deterministic voice preview does not speak model staging prose;
   - it speaks only the existing safe confirmation-on-screen fallback.

9. **external send voice preview regression**
   - Gmail/Mattermost deterministic preview remains unchanged.

10. **AP1 card regression**
   - semantic internal approval card still renders target titles/relation semantics;
   - empty staging prose does not hide or break the card.

11. **FIN1/FIN2 regression**
   - post-approval language and temporal finalization tests remain green.

## Required checks

Run at least:

- `backend/tests/test_assistant_action_plans.py`;
- `backend/tests/test_assistant_conversations.py`;
- focused new staging-truth tests;
- relevant Assistant service/security tests;
- focused Flutter Assistant action-plan/widget tests;
- voice approval/narration tests directly affected;
- FIN1/FIN2 finalization tests;
- `git diff --check`.

Record exact pass counts.

Do not require the known stale-date M1 fixture or the production-code parity guard to be green for this slice; record them as known external debt if encountered, without modifying them.

Model calls: 0.
Real external network calls: 0.

## Acceptance criteria

AH2-STG1 is complete only when:

- a staged ActionPlan structurally cannot expose model-authored prose as if execution already happened;
- ordinary non-staged answers remain unchanged;
- persistent reload cannot resurrect unsafe staging prose;
- AP1 card remains the semantic proposal surface;
- internal voice fallback cannot speak unsafe model staging prose;
- approval/rejection/finalization semantics are unchanged;
- FIN1/FIN2 remain green;
- no schema/model/network/deploy/client-install occurs.

## Completion protocol

After implementation:

1. append a compact factual AH2-STG1 result to `PROJECT_STATE.md`;
2. record AH2-AP1 Architect source acceptance in the same ledger update;
3. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - exact staging-answer contract;
   - persistent/reload behavior;
   - voice behavior;
   - AP1/FIN1/FIN2 regression evidence;
   - exact test counts;
   - confirmation of no schema/model/network/deploy;
4. commit + push to `main`;
5. STOP.

Do not start T3, Person aliases, Scheduled Activity integration, or rollout from HOLD.
