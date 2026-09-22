# Current task — Telegram MTProto Inbox UX: routine new messages must not require attention

## Context

Client acceptance proved transport delivery works: fresh inbound Telegram MTProto messages reach Secretary.

However current production behavior is wrong for the intended Inbox UX:
- each ordinary new inbound MTProto message is materialized as the correct canonical `chat_message`;
- it also creates an unresolved Notification with proposal:
  - `type=transport_event`
  - `provider=telegram`
  - `transport=mtproto`
  - `event_type=message_created`;
- Flutter renders unresolved notifications under `Требует внимания` with `Готово / Пропустить`.

This makes routine communication look like an actionable item and visually dominates the Inbox.

Architecture decision has been revised:
ordinary inbound MTProto `message_created` belongs in the normal Inbox/source feed only.

## Goal

Implement a schema-neutral correction so:

1. future routine inbound MTProto `message_created` events do NOT create Notification rows;
2. existing historical MTProto `transport_event/message_created` Notification rows remain stored but are excluded from the Inbox `Требует внимания` unresolved presentation;
3. the canonical Telegram source object remains visible in `Последние входящие`;
4. `message_edited` and `message_deleted` transport notifications remain unchanged.

CODE/TEST ONLY. No production deploy.

## Required backend changes

### A. Stop creating notifications for new inbound messages

In the MTProto history/new-message path, do not call/create
`TelegramMtprotoTransportNotificationService.message_created(...)`
for routine inbound message creation.

Do not alter:
- canonical object materialization;
- incoming/outgoing direction metadata;
- scope visibility;
- recurring sync cadence;
- edit/delete reconciliation;
- AI quarantine.

Keep the notification service methods for edit/delete.

If `message_created` method becomes unused, it may be removed only if no compatibility/test/API consumer requires it. Prefer the smallest clear cleanup.

### B. Hide historical created-event notifications from Inbox attention

Do not delete or mutate historical rows.

Introduce an explicit Inbox-attention query/filter so unresolved notifications included in `GET /inbox` exclude only:

- proposal.type == `transport_event`
- proposal.provider == `telegram`
- proposal.transport == `mtproto`
- proposal.event_type == `message_created`

Do not globally change generic notification listing semantics unless required.

Prefer a dedicated NotificationService method such as an Inbox-attention/unresolved selector rather than embedding JSON filtering directly in the API handler.

Existing edited/deleted Telegram transport notifications must still be returned as unresolved attention items.

### C. Preserve ordinary Inbox visibility

Regression must prove a newly materialized inbound active-scope MTProto object is still eligible through `RecentSourceService` / `GET /inbox` recent source objects after removing the notification side effect.

No client-side hiding of the source object.

## Required regressions

At minimum prove:

1. new inbound MTProto message materialization creates/updates the canonical object but does not create `message_created` Notification;
2. replay/idempotent sync still does not create such notification;
3. outbound message behavior remains unchanged;
4. edit transport event still creates deterministic notification;
5. delete transport event still creates deterministic notification;
6. generic Notification API/list behavior for historical `message_created` rows remains compatible;
7. Inbox unresolved/attention selector excludes historical MTProto `message_created` transport notifications;
8. the selector does NOT exclude:
   - Telegram `message_edited`;
   - Telegram `message_deleted`;
   - non-Telegram notifications;
   - non-MTProto Telegram notifications if any historical row exists;
9. `GET /inbox` returns the Telegram source object in ordinary recent-source feed while omitting its historical created-event notification from unresolved attention;
10. no schema migration;
11. `TELEGRAM_MTPROTO_AI_ENABLED=false` behavior unchanged;
12. no provider call added.

## Client

No Flutter behavior change should be necessary if backend contract is corrected.

Add/adjust a client regression only if an existing test explicitly assumes that `message_created` transport notifications belong under `Требует внимания`.

Do not redesign the Inbox UI in this task.

## Validation

Run:
- focused Telegram notification/history tests;
- Inbox/NotificationService tests;
- relevant client tests if touched;
- backend compile;
- Ruff;
- `git diff --check`.

## Authorization

AUTHORIZED:
- code/tests/docs for this Inbox-attention correction;
- update `PROJECT_STATE.md`;
- commit/push canonical `main`.

NOT AUTHORIZED:
- production deploy;
- production SSH;
- direct DB mutation/cleanup;
- migration;
- historical notification deletion/update;
- Telegram provider calls;
- MTProto config/scope changes;
- AI enablement.

## Required report

Return:
- commit SHA;
- files changed;
- exact new `message_created` behavior;
- exact Inbox historical-filter semantics;
- proof ordinary source object remains Inbox-visible;
- proof edit/delete notifications remain;
- tests/compile/Ruff/diff-check;
- migration=none;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_ORDINARY_INBOX_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
