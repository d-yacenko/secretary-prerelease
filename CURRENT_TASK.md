# CURRENT_TASK

## Status

ACTIVE

## REL1D-C2.1 — role-import conversation/session lifecycle fence

REL1D-C2 implementation `dc07dfce13bcaef08b51765ca5930266fa7c188b` is directionally correct but is **not yet Architect source-accepted**.

Source review found one narrow client lifecycle defect:

- role-import uses a separate local ActionPlan/state machine;
- `canSwitchConversation`, `_clearTransientTurnState()`, and `resetSession()` still only account for the pre-existing chat ActionPlan state;
- therefore a pending/preparing/approving/rejecting role-import flow can be hidden by conversation/session transitions, and an in-flight approve may finish server-side after a conversation switch without its deterministic result remaining visible.

Backend C1/C1.1 semantics are accepted and frozen.

This is a **client-only corrective**. No backend/schema/product deploy.

### A. Conversation switching gate

Treat an unresolved role-import confirmation like an unresolved chat ActionPlan for conversation switching.

`canSwitchConversation` must be false while any of these are true:

- role-import request is in flight;
- roleImport phase is `preparing`;
- `pending`;
- `approving`;
- `rejecting`.

A pending role-import plan must not be silently abandoned by starting/selecting another Assistant conversation.

Use the existing concise conversation-switch notice if appropriate; do not invent a second approval mechanism.

Do not make role-import voice-approvable.

### B. Clear role-import state on actual conversation transition

When a conversation switch/new conversation is actually allowed and succeeds, the transient reset path must invalidate the current role-import context exactly as an object-context change does.

After the transition there must be no retained local:

- extraction preview;
- grounding;
- row choices;
- pending/terminal role-import plan;
- plan result;
- source/grounding stale flags;
- role-import errors;
- role-import in-flight marker.

The role-import epochs/fences must advance so any older late prepare response cannot repopulate the new conversation.

Prefer reusing `_clearRoleImportPreview()` / existing clear helpers rather than duplicating reset logic.

### C. Session/auth reset

`resetSession()` must also fully clear/invalidate role-import state and advance its epochs.

This is a user-boundary requirement: role-import data from one authenticated session must not remain in controller memory after session termination/reset.

If an older prepare/approve/reject response completes after reset, it must not repopulate state for the new session.

It is acceptable to null the current role-plan flight token in the clear helper if that makes the fence explicit; correctness must not depend on the old request's `finally`.

### D. Preserve C2 semantics

Do not change:

- explicit row selection;
- Person/promotion choice rules;
- RoleTerm suggestion semantics;
- prepare payload;
- backend frozen presentation;
- approve/reject endpoints;
- deterministic execution result rendering;
- stale source/grounding handling;
- no-resume/no-model/no-chat-message invariant;
- existing voice approval semantics;
- C1 backend behavior.

Do not add production effects.

### Required deterministic tests

Extend focused client tests and prove at minimum:

1. editing role-import with no request/pending plan may switch conversation;
2. successful conversation transition clears extraction, grounding, choices, plan/result/errors/stale flags;
3. `preparing` blocks conversation switch;
4. `pending` blocks conversation switch;
5. `approving` blocks conversation switch;
6. `rejecting` blocks conversation switch;
7. after role-import reaches a terminal state, conversation switching is allowed and clears local role-import state;
8. `resetSession()` clears all role-import state;
9. late prepare after reset/session transition cannot repopulate state;
10. late approve/reject after reset cannot repopulate state;
11. existing ordinary chat ActionPlan switching behavior stays green;
12. role-import still never calls `/assistant/action-plans/{id}/resume`;
13. no extra prepare/approve/reject calls are introduced.

Run:

- `client/test/assistant/role_import_plan_test.dart`;
- existing role-import preview/API tests;
- `client/test/assistant/assistant_action_plan_test.dart`;
- any focused conversation/session controller tests touched;
- `flutter analyze` on changed Dart files;
- `git diff --check`.

All relevant focused tests: 0 failed. The existing unrelated analyzer warning is not part of this slice.

Backend code should remain unchanged. Re-run `backend/tests/test_rel1d_role_import_batch.py` only if backend files are touched unexpectedly; otherwise record that backend was unchanged.

### Production boundary

Source-only corrective.

Do not:

- move `production`;
- deploy;
- migrate;
- install/replace client;
- call model/provider;
- mutate production data.

Production/backend/client remain:

`6f802d6959aca40758376a83d5bdfcbbd77fc537`

Alembic remains:

`0054 / 0054`.

REL1D rollout remains unauthorized.

### Completion

1. implement only this lifecycle corrective;
2. update `PROJECT_STATE.md` with C2.1 SHA and exact focused checks, explicitly saying C2 still awaits Architect acceptance until corrective review;
3. return `CURRENT_TASK.md` to HOLD with implementation SHA and proof;
4. commit + push `main`;
5. STOP.

Do not start rollout.
