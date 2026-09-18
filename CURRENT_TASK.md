# Current task — Telegram MTProto C2BR: deterministic notification corrective

## Status

Telegram MTProto C2A/C2AR/C2AR2/C2AR3/C2AR4 reconciliation is **ACCEPTED and integrated to main**.

Accepted C2A implementation tip:
`802d9aacb217bd2d3b3e012bdd2a644059d55ad4`

Integration merge:
`5823d1f557e7040b0396e895032ed3c3b16d4d0d`

C2B implementation under review:
`4e01f16d2bea39e2bccef05bcfb8205269d47805`

C2B is **REJECTED pending this narrow C2BR corrective**.

The basic C2B design is accepted in direction:
- deterministic UUIDv5 Notification IDs from `user_id + event_key`;
- canonical created/edited/deleted event keys;
- existing `notifications` table/API;
- initial/backfill anti-spam intent;
- deterministic non-AI transport events;
- no migration;
- Q1 AI quarantine preserved.

Do not redesign those accepted pieces unless needed for the corrective below.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- production Alembic `0041`;
- repository Alembic head must remain `0046`;
- M3 NOT authorized;
- Bot API retirement NOT authorized.

Canonical AI flag remains:
`TELEGRAM_MTPROTO_AI_ENABLED=false` by default.

## C2BR blocking issue 1 — notification persistence must not be swallowed

In C2B SHA `4e01f16d2bea39e2bccef05bcfb8205269d47805`, reconciliation wraps provider fetch, object convergence, and deterministic notification creation in a broad candidate-isolation `except Exception: continue`.

This creates a C2B-specific correctness risk:
- remote edit can be materialized/flushed;
- remote delete can be tombstoned/flushed;
- deterministic notification persistence can then fail unexpectedly;
- the broad catch can swallow that local persistence failure;
- the object mutation can later commit without the required event;
- future reconciliation can see the object as unchanged/tombstoned, so the event can be lost permanently.

Correct this narrowly.

Required invariant:
- provider/read/normalization failures retain the accepted C2A bounded isolation/classification semantics;
- deterministic notification idempotency conflicts remain locally recoverable;
- an unexpected local Notification persistence failure MUST NOT be swallowed as a peer/provider candidate failure;
- edit/delete object convergence and their deterministic event creation must be atomic in the source-sync transaction or in a candidate savepoint such that a failed event write cannot silently leave a committed mutation with the event permanently missing;
- if the local event write cannot be completed/recovered, fail the local transaction/job path so a later retry can converge and emit the event;
- do not reinterpret notification persistence failure as provider exact absence, mismatch, or provider unavailability.

Add focused failure-injection tests for BOTH:
1. semantic remote edit + forced local notification persistence failure;
2. confirmed remote delete + forced local notification persistence failure.

The tests must prove there is no silent success with a permanently mutated object and missing event. The failure must be observable/retryable, and after the appropriate transaction rollback the object/event state must remain consistent.

## C2BR blocking issue 2 — complete the required C2B test matrix

The original C2B task required focused coverage substantially broader than the six tests currently added.

Keep the existing useful tests and add the missing focused coverage at minimum.

### Idempotency / conflict path
- same created event invoked twice -> exactly one Notification row;
- concurrent-equivalent deterministic PK conflict path returns the same deterministic Notification;
- same edit revision twice -> one row;
- later provider `edited_at` revision -> second row;
- same delete event twice -> one row.

The PK-conflict test must exercise the actual recovery branch, not only the pre-insert query hit.

### Initial/backfill anti-spam
- initial peer sync with 100 historical inbound messages -> zero notifications;
- bounded historical backfill -> zero notifications;
- replay/re-run of the same initial/history data -> zero notifications.

### New inbound
- established latest cursor + one newer inbound -> one `message_created`;
- two newer inbound messages -> two deterministic rows;
- outgoing -> zero;
- service message -> zero;
- inactive-scope peer -> zero;
- duplicate forward sync -> no duplicate;
- `source_object_id` points to the canonical Object;
- payload contains no credential/session/provider-reference/access-hash/api-hash material.

### Edit
- inbound semantic edit + trustworthy `edited_at` -> one `message_edited`;
- same reconciliation/revision -> no duplicate;
- later `edited_at` -> another event;
- metadata-only update -> zero event;
- body/content change with missing `edited_at` -> Object converges but zero edit event;
- outgoing edit -> zero;
- `TELEGRAM_MTPROTO_AI_ENABLED=false` still creates deterministic event while zero AI jobs are enqueued.

### Delete
- confirmed inbound exact absence -> tombstone + one `message_deleted`;
- repeated confirmed absence -> no duplicate;
- outgoing deletion -> zero event;
- transient/provider lookup error -> zero tombstone and zero event;
- mismatched provider result -> zero tombstone and zero event.

### Existing Notification API
Add focused API/service tests proving a deterministic `transport_event`:
- appears in existing GET /notifications behavior;
- mark-read works;
- accept uses generic non-task behavior and creates NO task, object, edge, or embedding job;
- ignore/resolve remain normal.

Do not change existing AI-generated notification semantics.

## Required regression and test hygiene

Required:
- focused C2B/C2BR tests;
- existing notification tests;
- Telegram A1-A4.4/Q1/C1A/C1B/C2A regressions;
- source-sync recurring tests;
- Ruff on changed Python files;
- `git diff --check`;
- Alembic head exactly `0046`.

The previous report included one failing notification-suite test attributed to shared DB contamination / OpenAI daily limit. That is NOT sufficient acceptance evidence.

For C2BR:
- run the required notification suite against a clean/isolated test database/environment;
- do not modify unrelated product behavior merely to hide polluted shared state;
- if a failure is genuinely pre-existing and cannot be eliminated locally, report the exact test name/error and reproduce the same failure at the exact C2B base SHA under the same clean conditions.

## Explicitly out of scope

Do NOT implement:
- C3 client UX;
- websocket/SSE;
- desktop/mobile OS notifications;
- realtime Telethon listener;
- migration `0047`;
- production deploy/ref move;
- production DB/env mutation;
- Bot API retirement;
- unrelated notification redesign.

## Branch / deliverable

Continue the existing branch:
`review/telegram-mtproto-c2b-notifications`

Continue from exact:
`C2BR_BASE_SHA=4e01f16d2bea39e2bccef05bcfb8205269d47805`

Create exactly one corrective commit on top.
Do not rewrite/squash the reviewed C2B commit.

Return:
- `C2BR_BASE_SHA`;
- `C2BR_SHA`;
- changed files;
- exact transaction/error-propagation correction;
- proof the deterministic PK-conflict recovery branch is tested;
- complete focused C2B/C2BR test results;
- clean notification-suite result or exact demonstrated pre-existing baseline;
- regression results;
- Ruff;
- `git diff --check`;
- Alembic head `0046`;
- production untouched.

Final marker:
`TELEGRAM_MTPROTO_C2BR_NOTIFICATIONS_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
