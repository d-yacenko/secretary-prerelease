# Current task — Person Graph G1R: human/UI semantics and boundedness correction

Architect review of Person Graph G1 implementation `221deca7a69a283e9c48bebb0cc0ef54d12614a4` confirms the core direction:
- `Задачи | Люди` is the correct human projection;
- overview uses canonical Person Objects;
- salience orders instead of hard-filtering;
- rooted People view shows existing graph state and linked open Tasks;
- no CRM entities / org inference / migration were introduced.

G1 is not yet accepted because four narrow semantic/boundedness defects remain. Fix only these. Do not start Task Refinement, organization inference, media adapters, or deployment.

Known unrelated baseline failures remain outside this task:
- `tests/test_graph_workspace.py::test_rooted_deleted_task_can_be_inspected` (404 vs legacy expectation);
- three existing Flutter Graph detail tests that expect `Удалить` / `Спросить секретаря` after `Подробнее`;
- previously documented repository baseline failures.

## 1. People search must use effective identities only

Current `PersonGraphWorkspaceService._matches()` iterates attached `PersonIdentity` rows directly.

Therefore an identity explicitly suppressed by active `user_rejected` evidence can still find the Person via People search even though the same identity is hidden from effective presentation/routes.

This violates the accepted effective-identity semantics from P5R2.

### Required

For identity-based People search:
- match only identities that are effective for that Person;
- active `user_rejected` must suppress search by that identity;
- retraction/confirmation restores searchability;
- Person title search remains independent and must still find the Person;
- conflicting identity may remain visible/searchable as conflict if it is still effective, but never silently resolve ownership.

Do not mutate identities during search.

## 2. First-party People UI must NOT inherit Telegram AI quarantine

G1 currently calls model-facing `PersonAssistantService.find_identity_candidates()` and `list_routes()`.

Those methods intentionally use `telegram_mtproto_ai_enabled()` / `telegram_mtproto_ai_predicate()`, which is correct for LLM-visible tools but wrong for the authenticated first-party human UI.

The durable Telegram architecture is:
- MTProto transport/storage/Inbox and first-party user-facing data continue normally;
- `TELEGRAM_MTPROTO_AI_ENABLED` gates ML/LLM/model-visible processing, not the user's own UI access.

### Required

People Graph UI presentation must use a non-AI first-party read path for stored Person identities/candidates/routes.

For the human UI:
- effective stored Telegram identity may be shown even when `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- an already-known exact private Telegram route may be shown even when the AI gate is false;
- deterministic source-derived Telegram identity candidate may be shown for user correction when it comes from stored MTProto communication;
- no LLM/model call is introduced;
- no live provider/directory lookup is introduced;
- no group/channel Telegram route becomes a Person route;
- same private/1:1 exact-route safety from P6 remains;
- user isolation and active-object checks remain.

Assistant/Harness behavior must remain unchanged:
- model-facing `find_person_identity_candidates`, `list_person_routes`, communications retrieval, etc. keep the existing Telegram AI gate.

Prefer factoring shared low-level deterministic route/candidate discovery with an explicit visibility policy over copying large P6 logic. A small UI-specific bounded read helper is acceptable if it preserves exactly the same identity/1:1 safety invariants.

Do not weaken `telegram_mtproto_ai_predicate` globally.

## 3. UI feedback provenance must not masquerade as Assistant feedback

Current first-party endpoint delegates directly to `PersonAssistantService.confirm_person_identity()` / reject / retract, producing provenance keys such as:
- `assistant:user_confirmed:...`
- `assistant:user_rejected:...`

For a click in first-party Graph UI, this provenance is incorrect.

### Required

Keep the existing evidence types:
- `user_confirmed`;
- `user_rejected`.

Keep `provenance_kind="user_feedback"`.

But first-party Graph correction must use a stable UI-specific provenance namespace, e.g.:
- `graph_ui:user_confirmed:...`;
- `graph_ui:user_rejected:...`.

Requirements:
- idempotent repeated click does not inflate evidence;
- confirm retracts active rejection by existing ledger semantics;
- reject retracts active confirmation by existing ledger semantics;
- retract must retract the active user feedback for that Person+exact identity, including prior Assistant-created feedback when the user is explicitly undoing it from UI;
- ownership conflicts / multiple confirmations still fail closed;
- an arbitrary invented tuple supplied directly to the endpoint must not become new confirmation/rejection evidence merely because it normalizes.

Server must revalidate that the exact identity is grounded for that Person:
- attached/effective/rejected identity already associated with that Person, or
- deterministic source-derived candidate currently exposed by the People service.
For `confirm`, a candidate must be confirmable and not owned by another Person.

The UI must continue showing the exact identity being changed.

## 4. Bound People workspace scans

G1 response limits are bounded, but several implementation paths iterate all matching rows in Python:
- all active People for overview/search;
- all Person edges in `_open_tasks`;
- all Person edges in `_communication_count`;
- rooted neighbor scan before trimming.

This contradicts the product's large-volume bounded-read architecture.

### Required

Make reads operationally bounded without changing visible semantics.

Acceptable approaches:
- DB `count()` for counts instead of loading every edge;
- SQL filters/joins for active open Tasks;
- `limit(cap + 1)` for visible neighbor/search scans with honest `truncated`;
- salience-ranked ids first plus deterministic bounded fallback People query;
- a documented finite scan cap where exact SQL filtering is awkward.

Requirements:
- overview still orders salient People first;
- low-salience known Person remains reachable by search/root_id;
- search is bounded and reports truncation;
- rooted view remains bounded;
- do not hard-filter by salience;
- do not eagerly create People.

Do not add a migration merely for this correction.

## Focused proof

Add/extend tests proving at minimum:

1. Attached email identity is searchable while effective.
2. User rejects that identity -> search by email no longer finds the Person.
3. Person title still finds the Person after identity rejection.
4. Retract/confirm restores identity search.
5. With `TELEGRAM_MTPROTO_AI_ENABLED=false`, first-party People detail can still show an existing effective Telegram identity.
6. With AI gate false, first-party People detail can still show an existing exact private Telegram Person route.
7. With AI gate false, deterministic stored Telegram candidate can be shown/corrected in UI when otherwise valid.
8. The same Telegram data remains hidden from model-facing Assistant paths according to existing P5/P6 tests.
9. Telegram group/channel is never presented as a Person route.
10. UI confirm writes `user_confirmed` with `graph_ui:` provenance, not `assistant:`.
11. UI reject writes `user_rejected` with `graph_ui:` provenance.
12. Repeating the same UI correction is idempotent/no score inflation.
13. UI retract can undo active feedback safely and does not delete history.
14. Direct API request with an invented/non-grounded identity tuple fails closed.
15. Identity owned by another Person still cannot be confirmed/reassigned.
16. Multiple-confirmation conflict remains explicit.
17. Overview/search/rooted scans are demonstrably capped or SQL-counted; a large synthetic set does not cause unbounded Python iteration.
18. Search/rooted access still reaches a low-salience Person outside the overview top-N.
19. Existing People workspace UI remains `Задачи | Люди`.
20. Existing Graph Refined and Graph task tests remain unchanged except known baseline failures.
21. No org/job-title/social inference, Task Refinement, media adapter, migration, or deploy.

Run:
- `tests/test_person_graph_workspace.py`;
- Graph Refined focused tests;
- current Graph workspace backend tests;
- Telegram MTProto self-authored/AI policy tests;
- Flutter people workspace + graph controller/screen tests;
- Ruff/compile for touched Python;
- Flutter analyze for touched Dart;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose the next roadmap phase and do not deploy.
