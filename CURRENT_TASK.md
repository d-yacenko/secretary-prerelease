# Current task — Persistent Assistant conversations corrective pass

Authorized scope: review/fix the already implemented persistent/resumable Assistant conversations MVP at implementation SHA `6acea4d49a175b43b0bb4a187d17e748dfa08a8b`.

Do not start another product feature. Do not deploy to production. Migration `0047` remains unapplied in production; production Alembic remains `0046 / 0046`.

## 1. Wire conversation transcript pagination end to end

Backend `GET /assistant/conversations/{id}/messages` already supports `has_more` and `before_id`, but Flutter currently restores only the first/default page.

Required:
- add optional `before_id` support to the Flutter API client;
- retain and consume `has_more` in Assistant state;
- make older messages reachable from the Assistant UI without loading an unbounded transcript at once;
- prepend older pages in stable chronological order with no duplicates;
- conversation switching/restart must preserve the exact selected conversation;
- UI pagination must not change the existing bounded server-owned model-history contract.

Focused proof:
- a conversation with more than 50 stored messages restores the newest page correctly;
- older page(s) can be loaded using `before_id`;
- ordering is stable and messages are not duplicated;
- model history remains bounded by the existing `MAX_ASSISTANT_HISTORY_MESSAGES` contract.

## 2. Do not permanently fall back to legacy mode after a transient bootstrap failure

Current problem: `AssistantController.restorePersistentConversation()` marks restore as started before network bootstrap and catches generic API failures by switching to legacy mode. A temporary network/5xx failure can therefore prevent another restore attempt for the rest of the client process.

Required:
- keep legacy in-memory fallback only for the intended route-absent/old-server compatibility case;
- transient bootstrap/list/message-load failures must remain retryable;
- after a transient persistent-bootstrap failure, do not silently send a legacy/stateless Assistant turn;
- a later retry must be able to restore/create the persistent conversation and continue normally;
- once persistent sending begins, retry of the same user turn must continue to reuse the same `client_turn_id`;
- typed and voice turns must continue to use the same selected conversation.

Focused proof:
- first persistent bootstrap fails transiently, later retry succeeds;
- no legacy `POST /assistant/message` is emitted during the failed bootstrap;
- route-absent compatibility still uses the legacy path;
- existing New dialog, conversation switching, unresolved-plan blocking, rehydrated references/action-plan cards, and stable retry-id tests remain green.

Run the smallest relevant backend and Flutter tests, touched-file Ruff/compile/analyze, and `git diff --check`.

When complete:
- record exact checks/results and implementation SHA in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP. Do not choose the next phase and do not deploy.
