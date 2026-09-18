# Current task — Telegram MTProto C2B: deterministic notification/event surface

## Status

Telegram MTProto C2A/C2AR/C2AR2/C2AR3/C2AR4 reconciliation is **ACCEPTED and integrated to main**.

Accepted implementation tip:
`802d9aacb217bd2d3b3e012bdd2a644059d55ad4`

Integration merge:
`5823d1f557e7040b0396e895032ed3c3b16d4d0d`

Accepted C2A semantics include:
- Telegram recurring default cadence 60 seconds;
- A3 history remains canonical new-message ingestion;
- bounded exact-message reconciliation for remote edits/deletes;
- independent recent-head and historical sweep traversal;
- fair account peer rotation;
- <=5 provider lookups/peer/run;
- <=20 provider lookups/account/run;
- canonical title normalization;
- read-error/auth/FloodWait classification;
- confirmed exact absence -> tombstone;
- Q1 AI quarantine preserved.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- production Alembic `0041`;
- M3 NOT authorized;
- Bot API retirement NOT authorized.

Canonical AI flag remains:
`TELEGRAM_MTPROTO_AI_ENABLED=false` by default.

## C2B goal

Add a deterministic Telegram MTProto user notification/event surface using the **existing** Notification persistence/API.

Do not create:
- a Telegram-specific notification table;
- a new migration;
- an LLM/AI notification path;
- client push/websocket/OS notification transport yet.

C2B creates deterministic rows in the existing `notifications` table so the existing
`/notifications` API can expose Telegram transport events.

C3 will decide how the client renders them.

## Core invariant — no AI

Telegram transport notifications must be generated entirely from deterministic provider/object facts.

Do NOT use:
- `SecretaryService`;
- `SecretaryNotificationService`;
- LLM summaries;
- semantic classification;
- inferred urgency/priority;
- embeddings;
- proactive AI.

This is true regardless of `TELEGRAM_MTPROTO_AI_ENABLED`.

The AI flag controls AI eligibility, not deterministic transport notifications.

## Event types

Canonical proposal payload type:

`type = "transport_event"`

Provider/transport:

`provider = "telegram"`
`transport = "mtproto"`

Supported C2B event types:

1. `message_created`
   - new inbound MTProto message observed after forward sync is already established;

2. `message_edited`
   - an already-known inbound MTProto message receives a confirmed provider-side semantic edit;

3. `message_deleted`
   - an already-known inbound MTProto message receives a provider-confirmed exact absence and is tombstoned.

Do NOT create deterministic notifications for:
- outgoing messages;
- Telegram service messages;
- legacy Bot/Business messages;
- inactive-scope messages;
- initial history import/backfill;
- unchanged reconciliation;
- metadata-only changes that do not represent user-visible message content change;
- mark-read;
- local outgoing send/edit/delete success.

## Initial sync / backfill anti-spam rule

This is mandatory.

The first history import/backfill for a peer can contain many historical messages.
It MUST NOT generate C2B notifications.

A `message_created` transport event is allowed only when all are true:
- canonical MTProto inbound message;
- active scope;
- message was newly materialized by a **forward incremental sync**;
- the peer already had an established forward history cursor before this sync;
- provider message_id is strictly newer than the prior forward cursor.

Initial connection, initial page, bounded historical backfill, replay of existing history, and passive reconciliation must not create "new message" notification storms.

Add tests explicitly proving 100 historical initial messages -> 0 notifications.

## Deterministic notification service

Add a narrow service, e.g.:

`TelegramMtprotoTransportNotificationService`

It may use `NotificationService` internally or create `Notification` rows directly through a small reusable deterministic helper.

Do not overload `SecretaryNotificationService`.

### Notification fields

For all Telegram transport events:

- `priority = "normal"`
- `status = "new"` on first creation
- `source_object_id = canonical Telegram Object.id` where the row still exists
- `related_object_id = None`
- `result_object_id = None`

Title/body must be deterministic, human-readable, and bounded.

Recommended:

### message_created
title:
`Telegram · <conversation title>`

body:
message body/text, bounded to a reasonable deterministic preview limit.

### message_edited
title:
`Telegram · message edited · <conversation title>`

body:
current edited body preview.

### message_deleted
title:
`Telegram · message deleted · <conversation title>`

body:
None or a fixed deterministic string such as `"Message deleted"`.

Do not expose:
- session strings;
- provider peer references;
- api_hash;
- encrypted credentials;
- access_hash;
- raw provider exception content.

## Proposal/event payload

Use existing `Notification.proposal_` JSON.

Required fields:

- `type: "transport_event"`
- `provider: "telegram"`
- `transport: "mtproto"`
- `event_type`
- `event_key`
- `account_id`
- `peer_id`
- `message_id`
- `object_id`
- `occurred_at`
- `edited_at` where applicable
- safe `conversation_title` if useful

No secrets/reference/session material.

## Idempotency

Repeated sync/reconciliation must not produce duplicate notifications for the same provider event.

No migration is authorized, so do not add a DB unique constraint.

Use deterministic Notification IDs, preferred approach:

- define a fixed UUID namespace constant;
- derive Notification.id with UUIDv5 from:
  `user_id + event_key`;
- insert under a nested transaction;
- on PK conflict, fetch and return the existing notification.

Equivalent concurrency-safe approach is acceptable, but a query-then-insert alone is NOT enough if concurrent source jobs can race.

Canonical `event_key` rules:

### message_created
Stable forever:
`telegram:mtproto:<account_id>:<peer_id>:<message_id>:created`

### message_deleted
Stable forever:
`telegram:mtproto:<account_id>:<peer_id>:<message_id>:deleted`

### message_edited
Must identify a real provider edit revision.

Preferred:
`telegram:mtproto:<account_id>:<peer_id>:<message_id>:edited:<edited_at_iso>`

Requirements:
- identical reconciliation of the same edit -> no duplicate;
- a later distinct provider edit with a later provider `edited_at` -> a new deterministic edit event;
- if provider edit lacks a trustworthy `edited_at`, do not invent an edit event revision from arrival time; fail closed for notification creation while still allowing Object convergence.

Do not key edit events by body hash unless necessary and explicitly justified.

## New inbound event integration

Integrate with the accepted A3 history path.

The code needs access to:
- previous `history_latest_message_id` before the forward page;
- `TelegramMaterializeResult.change`;
- normalized direction/service metadata.

Create `message_created` only when:
- previous latest cursor existed;
- current entry message_id > previous latest cursor;
- materializer result is `created`;
- normalized direction == inbound;
- non-service;
- active scope.

Do not notify an outgoing message merely because another client/device sent it and it later appears in sync.

Do not notify duplicate/replayed pages.

## Remote edit event integration

C2A exact-message reconciliation already materializes provider edits through A3 normalization/materializer.

Create `message_edited` only when:
- existing canonical object was inbound before/after normalization;
- materializer reports semantic `change == "updated"`;
- provider supplied a trustworthy non-null `edited_at`;
- same object/external_id is retained;
- event key for that `edited_at` does not already exist.

Do not emit for:
- `metadata_updated`;
- unchanged;
- outgoing;
- service messages;
- AI pipeline activity.

If the body changed but provider `edited_at` is absent:
- update the Object through normal materialization;
- create zero edit notifications.

## Remote delete event integration

C2A exact-message reconciliation tombstones on trustworthy exact absence.

Before tombstoning, freeze only safe facts needed for the deterministic event:
- Object id;
- account_id;
- peer_id;
- message_id;
- conversation title;
- direction.

Create `message_deleted` only when:
- object was active/not already tombstoned;
- canonical MTProto;
- inbound;
- exact provider absence confirmed;
- tombstone actually changes the object from active -> deleted.

Repeated confirmed absence after already tombstoned:
- zero new notification;
- zero duplicate event.

Transient/provider failure/mismatch:
- zero tombstone;
- zero notification.

## Transaction semantics

Object convergence and deterministic event creation should commit atomically in the same source-sync DB transaction where practical.

Do not let a notification insertion failure cause provider content to be incorrectly interpreted as absent/deleted.

Concurrency/idempotency conflict handling must be bounded and local.

## Existing Notification API semantics

Do not add a new API route in C2B.

Existing:
- GET /notifications
- GET /notifications/{id}
- POST /notifications/{id}/read
- accept/ignore/resolve

must continue to work.

For `transport_event` proposal types:
- `accept` may use existing generic non-task behavior and simply mark accepted;
- must never create a task/object/edge automatically;
- read/ignore/resolve continue normally.

Do not change AI-generated notification behavior.

## User/content privacy

Notification payload/title/body may contain the same human-visible message content already stored in the user's own Object.

But never include:
- provider reference JSON;
- session;
- access_hash;
- api_hash;
- credential material;
- Telegram phone/code/password/auth state.

Sanitized IDs account_id/peer_id/message_id are allowed internal routing metadata.

## Tests

Add focused tests at minimum.

### Idempotency
- same created event invoked twice -> exactly one Notification row;
- concurrent-equivalent insert conflict path returns same deterministic notification;
- same edit revision twice -> one row;
- later edited_at revision -> second edit notification;
- same delete event twice -> one row.

### Initial/backfill anti-spam
- initial peer sync with many historical inbound messages -> zero notifications;
- bounded backfill -> zero notifications;
- re-running same initial/history page -> zero notifications.

### New inbound
- established latest cursor + one newer inbound message -> one message_created notification;
- two new inbound messages -> two deterministic rows;
- outgoing new message -> zero;
- service message -> zero;
- inactive-scope peer -> zero;
- duplicate forward sync -> no duplicate;
- notification source_object_id points to canonical Object;
- payload has no credential/reference fields.

### Edit
- remote inbound semantic edit + provider edited_at -> one message_edited;
- same reconciliation again -> no duplicate;
- later edit with later edited_at -> another event;
- metadata-only update -> zero;
- missing edited_at -> zero event but Object still converges;
- outgoing edit -> zero;
- AI=false still creates deterministic notification but zero AI jobs.

### Delete
- confirmed inbound exact absence -> tombstone + one delete event;
- repeated absence/tombstone -> no duplicate;
- outgoing deletion -> zero event;
- transient lookup error -> no event;
- mismatched result -> no event.

### Notification API
- deterministic Telegram transport event appears in existing GET /notifications;
- mark-read works;
- accept on transport_event does not create a task/edge;
- Secretary/AI notification tests remain unchanged.

### Regression
- C2A reconciliation remains green;
- C1A/C1B remain green;
- Q1 AI quarantine remains green;
- legacy Bot/Business Telegram unchanged;
- Alembic head remains `0046`.

Run:
- focused C2B tests;
- notifications tests;
- Telegram A1-A4.4/Q1/C1A/C1B/C2A regressions;
- source-sync recurring tests;
- Ruff changed Python files;
- `git diff --check`.

## Explicitly out of scope C2B

Do NOT implement:
- websocket/SSE push;
- desktop/mobile OS notifications;
- Android notification channels;
- Linux D-Bus notifications;
- client UI changes;
- client unread badge behavior;
- realtime Telethon listener;
- production deploy/ref move;
- production DB/env mutation;
- migration `0047`;
- Bot API retirement.

Those belong to C3 or later.

## Branch / deliverable

Start from latest `origin/main`.

Create/use:
`review/telegram-mtproto-c2b-notifications`

Return:
- `STARTING_SHA`;
- `C2B_SHA`;
- changed files;
- deterministic Notification ID/event-key design;
- initial/backfill anti-spam rule;
- new/edit/delete integration points;
- transaction/idempotency behavior;
- focused/regression test results;
- Ruff;
- git diff --check;
- Alembic head `0046`;
- production untouched.

Final marker:
`TELEGRAM_MTPROTO_C2B_NOTIFICATIONS_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
