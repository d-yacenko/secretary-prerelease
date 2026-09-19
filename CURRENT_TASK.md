# Current task — Telegram MTProto C3AR: client auth-state and scope UX corrective

## Status

Telegram MTProto C2B/C2BR/C2BR2 deterministic notifications are ACCEPTED / INTEGRATED TO MAIN.

C3A implementation under review:
`d761d1aeab6b99530910a0292ba82e322a5885b3`

C3A is **REJECTED pending this narrow C3AR corrective**.

Accepted C3A direction:
- Flutter-only integration over the existing `/telegram/mtproto/*` backend contract;
- typed API models/client methods;
- in-memory auth challenge state;
- folder/scope/group controls in the existing Account screen;
- no backend, migration, or production changes.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- production Alembic `0041`;
- repository Alembic head must remain `0046`;
- M3 NOT authorized;
- Bot API retirement NOT authorized.

## Blocking issue 1 — code challenge and 2FA states are conflated

At C3A SHA `d761d1aeab6b99530910a0292ba82e322a5885b3`, once `auth/start` succeeds, the UI renders BOTH:
- Telegram code input/submit;
- 2FA password input/submit.

The password field is therefore visible and actionable before the backend has returned `password_required`.

Correct this with an explicit in-memory auth step/state.

Required behavior:
- after `auth/start`: show code challenge only;
- before `password_required`: do NOT render or enable password input/submit;
- after code result `password_required`: clear the code, transition to password-only state, and render obscured password input;
- after code result `authorized`: clear challenge/code/password state and refresh connected status without ever showing the password step;
- after password authorization: clear challenge/code/password state and refresh connected status;
- abandon/restart clears code/password and returns to phone/start state;
- challenge/password-required state remains memory-only and does not survive widget/app reconstruction.

Add widget tests for BOTH:
1. phone -> code -> authorized, proving password UI never appears;
2. phone -> code -> password_required -> password -> authorized.

## Blocking issue 2 — reconciled peers are not actionable

The backend `POST /telegram/mtproto/sync-scope/reconcile` returns `peers`, but C3A currently renders only reconcile counts. Per-peer sync rows are rendered only for preview dialogs.

Required:
- render reconciled peers as well;
- private/group/supergroup peers returned by reconcile must be visible and have the existing explicit scope-peer sync action;
- avoid duplicate rows if the same peer is already visible from the current preview; one clear current-scope list is preferred;
- preserve sanitized sync summary behavior.

Add a widget test where reconcile returns at least one peer and prove its per-peer sync button calls:
`POST /telegram/mtproto/sync-scope/peers/{peer_id}/sync`
and renders the returned summary.

## Blocking issue 3 — required manual-group metadata is incomplete

C3A required the group list to expose:
- title;
- username;
- kind;
- forum status;
- availability;
- selected state.

Current UI renders title, username, kind and selected controls, while forum/availability are not explicitly presented.

Required:
- present forum status when `is_forum=true`;
- present unavailable state explicitly in text/semantics, not only by disabled controls;
- unavailable group selection/sync remains disabled;
- selected state remains represented by the existing control.

Add focused widget coverage for:
- forum group presentation;
- unavailable group presentation and non-actionability.

## Blocking issue 4 — authenticated-session failure handling is inconsistent

`AuthenticationException` extends `ApiException`.

C3A handles it explicitly in status/auth/load-scope, but these action methods currently catch only `ApiException`:
- save folders;
- preview scope;
- reconcile scope;
- toggle group;
- sync scope peer;
- sync group.

Therefore an HTTP 401 on those paths is consumed as ordinary UI error instead of invoking the existing global `AuthController.handleAuthenticationFailure()` convention.

Correct consistently:
- on `AuthenticationException`, invoke `authController.handleAuthenticationFailure()`;
- do not also surface it as a Telegram provider error;
- preserve 400/404/409/410/422/503 handling through the existing safe `ApiException` presentation conventions.

Add at least one focused widget regression for an authenticated MTProto action returning 401 and prove the AuthController transitions through the existing authentication-failure path.

## Verification gap — prove required C3A flows, not only aggregate test count

The C3A report says 39 focused/regression tests passed, but the new focused files contain only six top-level tests and do not explicitly prove all required UX transitions.

For C3AR, return an acceptance matrix:
`required invariant -> exact test name -> file`

The matrix must include at minimum:
- server not configured presentation;
- configured/disconnected;
- connected identity;
- direct code authorization without 2FA;
- password-required flow;
- duplicate-submit protection;
- sensitive code/password gone after success;
- zero-folder selection save remains zero;
- ignore-muted request/response behavior;
- preview truncated/skipped counts;
- reconcile counts + reconcile peer action;
- group selected toggle;
- forum label;
- unavailable group label/non-actionability;
- manual group sync summary;
- scope-peer sync summary;
- sanitized 400/409/410/503 presentation;
- 401 global auth failure behavior.

Do not add redundant tests if an existing exact widget/API test already proves an invariant; cite exact existing names where appropriate.

## Flutter analyze acceptance

The previous report states:
- targeted analyze PASS;
- full `flutter analyze` has existing repository baseline findings.

C3AR acceptance requires one of:
1. full `flutter analyze` PASS; OR
2. exact evidence that the full-analyze diagnostics are pre-existing:
   - run the same full command at exact C3A base `0cdcbaa0498f8e4c1ef3033c5c7d544bb8590319`;
   - run it at C3AR head;
   - report diagnostics/count for both;
   - C3AR must introduce zero new analyzer diagnostics.

Do not modify unrelated baseline files merely to make this task green.

## Required checks

Run:
- focused C3A/C3AR Flutter tests;
- relevant existing Account/API client regressions;
- `dart format --output=none --set-exit-if-changed` on changed Dart files;
- full `flutter analyze` with the baseline comparison rule above if non-zero;
- `git diff --check`;
- repository Alembic head exactly `0046`.

Backend changes are not expected and are not authorized unless a hard blocker is first reported instead of implemented.

## Explicitly out of scope

Do NOT implement:
- C3B Telegram-specific Inbox/notification presentation;
- backend MTProto auth/scope redesign;
- new backend endpoints;
- disconnect/delete account semantics;
- OS notifications;
- websocket/SSE;
- realtime Telethon listener;
- client-side Telegram SDK;
- migration `0047`;
- production deploy/ref move;
- production DB/env mutation;
- Bot API retirement.

## Branch / deliverable

Continue existing branch:
`review/telegram-mtproto-c3a-client-account`

Continue from exact:
`C3AR_BASE_SHA=d761d1aeab6b99530910a0292ba82e322a5885b3`

Create exactly one corrective commit on top.
Do not rewrite/squash the reviewed C3A commit.

Return:
- `C3AR_BASE_SHA`;
- `C3AR_SHA`;
- changed files;
- exact auth-state correction;
- reconcile-peer rendering/action correction;
- group metadata correction;
- 401 handling correction;
- acceptance matrix mapping invariants -> exact tests;
- focused/regression test results;
- full analyze result or exact base/head baseline comparison;
- Dart format check;
- `git diff --check`;
- Alembic head `0046`;
- clean worktree;
- remote branch SHA;
- backend/migrations/production untouched.

Final marker:
`TELEGRAM_MTPROTO_C3AR_CLIENT_ACCOUNT_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
