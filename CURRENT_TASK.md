# Current task — HOLD

AH2-STG1 is implemented and waiting for Architect review. Do not start the next slice from this HOLD.

## AH2-STG1 — deterministic pre-approval truth boundary

- Implementation: `10b1a53c4e017d84849b603ccb09af1142709903`
- AH2-AP1 remains ARCHITECT SOURCE-ACCEPTED at `09ab0309a6147320340a2468e4fbb751e34df566` (HOLD `18e8776abf613d54fe511eaa02ecb94c5ae33fbc`, ledger `a8bf1e4eafa2388f3a44b91738864359dc3a7bcf`)
- Production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`
- Health remains PASS

## Changed files

- `backend/app/services/assistant_service.py`
- `backend/tests/test_ah2_stg1_staging_truth.py`
- `client/lib/assistant/assistant_controller.dart`
- `client/lib/assistant/assistant_screen.dart`
- `client/test/assistant/assistant_action_plan_test.dart`
- `client/test/assistant/voice_assistant_a_test.dart`

## Staging-answer contract

If the turn persists a real pending ActionPlan, the user-facing assistant answer is the empty string. The model-authored staging prose is discarded for display and persistence. No second model call is made. Turns with no pending plan keep the model answer unchanged.

The approval card, including the AP1 semantic snapshot, remains the description of the proposed action.

## Persistent reload

The stored assistant message for a staged turn is the empty answer plus the hydrated pending plan. Reloading the conversation does not restore the discarded prose. A later turn's server-owned history does not contain that prose. Legacy mode, a message without `conversation_id`, uses the same empty-answer contract.

## Voice

An internal pending plan without a deterministic voice preview speaks only «Это действие нужно подтвердить на экране.» It does not speak model staging prose. Gmail and Mattermost plans keep their existing deterministic previews.

## Approval, rejection, and finalization

Execution, rejection, FIN1 language continuity, and FIN2 temporal finalization are unchanged. After approval, resume returns the text-only finalizer answer. The staging message stays empty. Rejection marks the plan rejected and does not add an execution claim.

## Checks

- `test_ah2_stg1_staging_truth.py`: 7 passed
- `test_assistant_action_plans.py`: 45 passed
- `test_ah2_fin2_temporal_finalization.py`: 9 passed
- those three files together: 61 passed
- `test_assistant_conversations.py`: 15 passed
- Flutter `assistant_action_plan_test.dart` and `voice_assistant_a_test.dart`: 50 passed
- `flutter analyze` of `assistant_controller.dart` and `assistant_screen.dart`: 0 errors, 1 pre-existing warning on the Linux drop target, which this slice did not edit
- `git diff --check`: clean

Model calls: 0. Real network calls: 0. No schema migration. No deploy. No client install.

The stale-date M1 fixture and `test_product_code_matches_production_release` were not modified.

Do not start T3, Person aliases, Scheduled Activity integration, or rollout from this HOLD.
