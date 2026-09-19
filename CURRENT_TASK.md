# Current task — Telegram MTProto C3B: Inbox transport-event presentation

## Status

Telegram MTProto C3A/C3AR/C3AR2 Flutter account/auth/scope UX is **ACCEPTED and integrated to main**.

Accepted implementation tip:
`b8455ec7b48106a284d81e50c524c8d8ef278d19`

Integration merge:
`f6f66dff6e03ae290dc7fc68d945734eba9a99a5`

This task authorizes only **C3B — Telegram-specific Inbox presentation for already-existing MTProto source objects and deterministic transport notifications**.

Production remains untouched:
- production runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- production Alembic `0041`;
- repository Alembic head must remain `0046`;
- M3 NOT authorized;
- Bot API retirement NOT authorized.

## Goal

Make Telegram MTProto messages/events understandable in the existing Flutter Inbox without changing the accepted backend notification semantics.

Use existing:
- `InboxSourceObjectOut`;
- `NotificationOut`;
- existing Inbox notification actions;
- existing object/context navigation.

Do not invent a parallel Telegram inbox.

## Transport-event identification

A deterministic Telegram MTProto transport notification is identified only when proposal fields match:
- `type == "transport_event"`;
- `provider == "telegram"`;
- `transport == "mtproto"`.

Supported event types:
- `message_created`;
- `message_edited`;
- `message_deleted`.

Unknown/malformed proposal values must fall back safely to generic notification presentation.

## Required presentation

For Telegram MTProto transport events, present human-readable localized UI rather than raw proposal type/action labels.

At minimum:
- created -> clearly indicate a new Telegram message;
- edited -> clearly indicate a Telegram message was edited;
- deleted -> clearly indicate a Telegram message was deleted;
- show `conversation_title` when present;
- show notification body/preview when meaningful;
- show a sensible timestamp using `occurred_at`, and for edits optionally `edited_at`;
- do NOT show raw `event_key`, `account_id`, `peer_id`, `message_id`, provider references, access hashes, session data, or credentials.

The generic existing notification presentation must remain unchanged for non-transport notifications.

## Notification actions

The backend C2B contract is already accepted:
- transport-event `accept` is generic/non-task and creates no task/object/edge/embed job;
- ignore/resolve are generic;
- mark-read is existing API.

Client behavior for Telegram transport events:
- do not label the primary action as if it creates/approves a task;
- use a neutral completion label such as `Готово` for the existing accept action;
- keep `Пропустить` for ignore;
- keep/open context using existing `source_object_id` context path;
- opening context for a new unread transport event should mark it read using the existing mark-read API before/alongside navigation, without blocking context opening on a non-auth mark-read failure;
- 401 from mark-read must still use the global AuthController failure path;
- do not introduce new backend endpoints.

Non-transport notification buttons and semantics must remain exactly as before.

## Source object presentation

Telegram MTProto materialized message objects already enter the generic Inbox feed.

Ensure Telegram MTProto source objects:
- retain existing generic feed ordering/grouping/bookmark/review-rail behavior;
- display Telegram provider identity consistently through existing provider/icon/presentation helpers;
- do not expose provider-reference/access-hash/session metadata;
- are not duplicated into a second Telegram-only feed.

If the existing generic source card already satisfies these invariants, prefer tests/presentation helpers over a large rewrite.

## Client helpers/models

Prefer small typed/helper accessors around `NotificationOut.proposal` rather than scattering raw map lookups through widgets.

Helpers should safely parse:
- whether this is Telegram MTProto transport event;
- event type;
- conversation title;
- occurred/edited timestamp;
- source object id already supplied by `NotificationOut.sourceObjectId`.

Malformed values must return null/fallback, never throw during Inbox rendering.

## Testing

Add focused Flutter tests covering at minimum:
- created event card presentation;
- edited event card presentation;
- deleted event card presentation;
- conversation title/body preview;
- no raw event/account/peer/message identifiers rendered;
- malformed/unknown transport proposal safely falls back;
- non-transport notification presentation/actions unchanged;
- transport-event primary button label is neutral and still calls existing accept endpoint;
- ignore still calls existing ignore endpoint;
- open context uses source object path and invokes mark-read for unread/new transport event;
- mark-read non-auth failure does not prevent context navigation;
- mark-read 401 routes to AuthController;
- already-read transport event does not issue redundant mark-read;
- Telegram source objects remain in normal Inbox feed and do not duplicate.

Also run relevant existing Inbox/notification/API regressions.

## Required checks

- focused C3B Flutter tests;
- relevant existing Inbox/notification/API tests;
- `dart format --output=none --set-exit-if-changed` on changed Dart files;
- full `flutter analyze`.

If full analyze is non-zero, use the same accepted baseline method:
- exact base `f6f66dff6e03ae290dc7fc68d945734eba9a99a5`;
- C3B head;
- same command;
- report base/head/common/base-only/head-only;
- head-only must be zero.

Also:
- `git diff --check`;
- repository Alembic head exactly `0046`;
- clean worktree.

Backend changes are not expected or authorized.

## Explicitly out of scope

Do NOT implement:
- a separate Telegram inbox/navigation tree;
- reply/edit/delete compose UX in Inbox;
- OS-level notifications;
- websocket/SSE;
- realtime Telethon listener;
- client-side Telegram SDK;
- backend notification redesign;
- new backend endpoints;
- migration `0047`;
- production deploy/ref move;
- production DB/env mutation;
- Bot API retirement.

## Branch / deliverable

Create:
`review/telegram-mtproto-c3b-inbox`

Start from exact:
`C3B_BASE_SHA=f6f66dff6e03ae290dc7fc68d945734eba9a99a5`

If main later moves only for Architect task/state/recovery documentation, do NOT rebase merely for those docs.

Return:
- `C3B_BASE_SHA`;
- `C3B_SHA`;
- changed files;
- transport-event helper/presentation design;
- action/mark-read behavior;
- focused test matrix/results;
- existing regressions;
- analyzer/base comparison;
- Dart format;
- `git diff --check`;
- Alembic `0046`;
- clean worktree;
- remote branch SHA;
- backend/migrations/production untouched.

Final marker:
`TELEGRAM_MTPROTO_C3B_INBOX_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
