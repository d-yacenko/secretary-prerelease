# Current task — HOLD

AH2-AP1 is implemented and waiting for Architect review. Do not start the next slice from this HOLD.

## AH2-AP1 — frozen semantic approval presentation

- Implementation: `09ab0309a6147320340a2468e4fbb751e34df566`
- AH2-FIN2 remains ARCHITECT SOURCE-ACCEPTED at `c649981c6342b24eb3eee71c1b727e16b25b1744` (HOLD `56cfaff981aace5b1da43afc6e2eaa2b0992acf0`, ledger `2b8c562dbce9d8e18ae6b563a71313328d080134`)
- Production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`
- Health remains PASS

## Changed files

- `backend/app/assistant/approval_presentation.py`
- `backend/app/services/action_plan_service.py`
- `backend/app/services/assistant_service.py`
- `backend/app/services/assistant_conversation_service.py`
- `backend/app/api/assistant.py`
- `backend/tests/test_ah2_ap1_approval_presentation.py`
- `client/lib/api/api_models.dart`
- `client/test/api/task_lifecycle_labels_test.dart`
- `client/test/assistant/assistant_action_plan_test.dart`

## Presentation contract

Optional per-action object persisted in the existing JSON action payload:

`presentation: { operation, entities: [{ role, id, title, kind, status? }], relation_type?, fields: [{ name, value }] }`

Titles are bounded to 120 characters. Linked entity lists are capped at 8. The snapshot is structured data. Flutter formats the Russian card. The model does not author card copy.

Supported operations: `create_task`; `create_direction` when `completion_mode=ongoing`; `update_task`; `set_task_status`; `delete_task`; `link_objects`; `remove_relation`; `create_scheduled_activity`.

`send_email`, `send_message`, and calendar actions receive no snapshot. Their existing previews stay.

## Frozen versus legacy

`create_plan` discards a client-supplied `presentation` and rebuilds the snapshot from canonical user-owned state. Conversation reload, GET, approve, and reject return that stored snapshot. A later rename does not rewrite it. Execution still uses the frozen object id.

A stored plan with no `presentation` still loads, approves, rejects, and resumes. The client uses the previous English tool and UUID label. No snapshot is invented from current mutable state.

## Execution independence

`execute_approved_actions_with_tools` reads only `tool_name` and `arguments`. A regression rewrites a stored presentation to claim status `open` and a different title; approved execution still applies the frozen argument `done` on the original object.

## Checks

- `test_ah2_ap1_approval_presentation.py`: 13 passed
- `test_assistant_action_plans.py`: 45 passed
- `test_assistant_conversations.py`: 15 passed
- `test_ah2m_eval_runner.py` filtered to F1, M2, R1, R2, R3, and A1: 9 passed, 36 deselected
- Flutter `task_lifecycle_labels_test.dart` and `assistant_action_plan_test.dart`: 35 passed
- `flutter analyze` of `client/lib/api/api_models.dart`: 0 issues
- `git diff --check`: clean

Model calls: 0. Real network calls: 0. No schema migration. No deploy. No client install.

Observed outside this slice and not edited: M1 scripted approval fails because fixture `run_at` `2026-10-02T09:00:00+02:00` is now before `utcnow()`, so staging produces no action; `test_product_code_matches_production_release` fails because `backend/app` has diverged from production `aa3f475a3a0ee49b938364e6d53f3657711b1a9b` since AH2-FIN1.

Do not start staging-prose truthfulness, T3, Person aliases, or Scheduled Activity product integration from this HOLD.
