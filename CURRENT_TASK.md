# Current task — Assistant persistent-session isolation corrective pass

Architect review of implementation `890ee7ae449d0b009a029d8c6479072552fa3ee7` found one blocking session-boundary defect. Fix only this defect and its focused proof.

Do not start another product feature. Do not deploy to production. Do not apply migration `0047` in production. Do not make live provider/LLM calls.

## Problem — persistent Assistant state survives auth-session termination

`PersonalSecretaryApp` owns one long-lived `AssistantController` and calls `assistantController.resetSession()` from `onSessionTerminated`. The new persistent-conversation fields are not currently reset.

At minimum, a terminated session can leave state such as:
- `persistentMode`
- `conversationId`
- `conversations`
- `hasOlderMessages` / `loadingOlderMessages`
- `_legacyConversationServer`
- `_persistentBootstrapReady`
- `switchBlockedMessage`
- any in-flight persistent-conversation bootstrap/load state

This can make a later authenticated user inherit client-side conversation identity/history metadata from the previous user. Backend ownership checks remain important but are not a substitute for client session isolation.

There is also an async race: simply clearing fields in `resetSession()` is not sufficient if a bootstrap/message/conversation request started before logout can complete afterward and repopulate the controller with the old session's state.

## Required behavior

- `resetSession()` must return the Assistant conversation subsystem to a clean pre-bootstrap state:
  - no selected conversation id;
  - no persisted conversation list/history metadata;
  - no older-page/loading flags;
  - `persistentMode == false`;
  - no legacy-server/bootstrap-ready latch from the previous auth session;
  - no stale conversation-switch notice/error attributable to the previous session.
- The next authenticated session must perform a fresh persistent-conversation bootstrap and resolve its own current conversation.
- Any Assistant async operation started before `resetSession()` must not repopulate user-visible Assistant/conversation state after that reset. Use a small deterministic session-generation/epoch or equivalent invalidation mechanism; do not attempt to cancel Dart Futures by pretending they are cancelled.
- At minimum guard persistent bootstrap/list/message-load and an in-flight Assistant send from committing stale post-await state across session termination. If the same small guard naturally covers new/select/load-older/action-plan continuations, prefer that over one-off special cases.
- Preserve all behavior accepted in `890ee7a`: transcript paging, bounded 12-message model context, retryable transient bootstrap, old-server 404 legacy compatibility, New dialog, switching, plan blocking, stable retry ids, typed/voice conversation parity.
- Do not weaken backend user isolation or approval/action-plan rules.

## Focused proof

Add/extend tests proving at minimum:

1. Existing logout/reset test now verifies all persistent conversation state is cleared, not only messages/object context.
2. User A is bootstrapped with conversation A; session reset occurs; the next bootstrap resolves conversation B and does not expose A's conversation id/title/messages.
3. A bootstrap or conversation-message load started before reset completes afterward: stale completion does not restore A's state.
4. A send started before reset completes afterward: stale response does not append A's user/assistant messages or restore A's conversation state after reset.
5. Existing persistent-conversation suites from the previous corrective pass remain green.

Run the smallest relevant Flutter tests, touched-file analyze, and `git diff --check`. Backend changes are not expected; if none are made, do not rerun unrelated backend suites merely for ceremony.

When complete:
- record exact checks/results and implementation SHA in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP. Do not choose the next phase and do not deploy.
