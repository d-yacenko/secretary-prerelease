# Current task — Telegram MTProto C2BR2: close persistence boundary and acceptance coverage

## Status

Telegram MTProto C2A reconciliation is ACCEPTED / INTEGRATED TO MAIN.

C2B implementation:
`4e01f16d2bea39e2bccef05bcfb8205269d47805`

C2BR corrective:
`148c668a75222fdd9c75e97000ae646ca36e7766`

C2BR improved the design and several pieces are accepted:
- local Notification persistence errors are represented by `TelegramMtprotoNotificationPersistenceError`;
- edit/delete notification failure is no longer silently accepted in the ordinary insert/select paths;
- deterministic PK-conflict recovery now has a real IntegrityError-path regression;
- existing Notification API generic transport-event lifecycle is covered;
- production and Alembic remain untouched.

C2B/C2BR is still REJECTED pending this narrow C2BR2 corrective.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- production Alembic `0041`;
- repository Alembic head must remain `0046`;
- M3 NOT authorized;
- Bot API retirement NOT authorized.

Canonical AI flag:
`TELEGRAM_MTPROTO_AI_ENABLED=false` by default.

## Blocking issue 1 — begin_nested persistence failure is still outside the typed boundary

In `telegram_mtproto_notification_service.py` at C2BR SHA `148c668a75222fdd9c75e97000ae646ca36e7766`, the notification insert path still does:

`nested = self._session.begin_nested()`

before entering the `try` that translates unexpected local persistence failures into `TelegramMtprotoNotificationPersistenceError`.

Therefore a SAVEPOINT/open/pre-flush failure from `begin_nested()` can still escape as a generic exception. In reconciliation that generic exception can be consumed by the pre-existing broad candidate isolation `except Exception: continue`, recreating the exact class of silent local-persistence failure C2BR was intended to eliminate.

Correct this narrowly.

Required invariant:
- the complete deterministic Notification persistence operation, including SAVEPOINT creation/opening, insert flush, savepoint commit, and conflict recovery lookup, must either:
  1. succeed;
  2. recover a deterministic PK conflict and return the existing row; or
  3. raise `TelegramMtprotoNotificationPersistenceError`.
- no unexpected local persistence failure from that operation may escape as a generic exception into reconciliation candidate isolation;
- provider/read/normalization candidate isolation semantics from accepted C2A must remain unchanged;
- do not broadly reclassify provider exceptions as notification persistence failures.

Add a focused regression that forces the notification service SAVEPOINT/`begin_nested()` path itself to fail and proves:
- the caller receives `TelegramMtprotoNotificationPersistenceError`;
- edit/delete reconciliation does not silently succeed;
- no committed semantic edit/tombstone can remain without its deterministic event after rollback.

## Blocking issue 2 — acceptance coverage is still incomplete

The focused C2B file at C2BR contains 10 tests. The original C2B/C2BR acceptance matrix still lacks explicit evidence for several required semantics.

Do not add redundant tests where an existing repository test already proves the exact invariant. You may satisfy a row either by:
- adding a focused C2B/C2BR regression, OR
- citing an existing exact test name/file that already proves that exact behavior against the C2B/C2BR code path.

For integration-specific notification behavior, add focused tests where no exact existing test exists.

Provide explicit test evidence for every item below.

### Initial/backfill anti-spam
- bounded historical backfill creates zero notifications;
- replay/re-run of initial/history data creates zero notifications.

### New inbound
- two newer inbound messages create two deterministic rows;
- service message creates zero event;
- inactive-scope peer creates zero event;
- payload/proposal contains no credential/session/provider-reference/access_hash/api_hash material.

### Edit
- metadata-only update creates zero event;
- body/content update with missing `edited_at` converges Object but creates zero event;
- with `TELEGRAM_MTPROTO_AI_ENABLED=false`, deterministic event is created while zero AI jobs are enqueued.

### Delete
- outgoing confirmed deletion creates zero event;
- transient/provider lookup error creates zero tombstone and zero event;
- mismatched provider result creates zero tombstone and zero event.

Existing already-demonstrated items may be cited rather than duplicated:
- initial 100-message import anti-spam;
- one established-cursor inbound event;
- outgoing forward zero event;
- same/later edit revision idempotency;
- inbound confirmed delete idempotency;
- outgoing edit zero event;
- deterministic PK conflict recovery;
- edit/delete notification failure propagation;
- Notification API read/accept/ignore/resolve lifecycle.

## Test / verification requirements

Run:
- focused C2B/C2BR/C2BR2 tests;
- existing notification suite on isolated/disposable PostgreSQL;
- Telegram A1-A4.4/Q1/C1A/C1B/C2A regressions;
- source-sync/worker recurring suites;
- Ruff on changed Python files;
- `git diff --check`;
- Alembic head exactly `0046`.

Return an acceptance matrix mapping each required C2B/C2BR/C2BR2 invariant to the exact test name and file that proves it.

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

Continue existing branch:
`review/telegram-mtproto-c2b-notifications`

Continue from exact:
`C2BR2_BASE_SHA=148c668a75222fdd9c75e97000ae646ca36e7766`

Create exactly one corrective commit on top.
Do not rewrite/squash C2B or C2BR.

Return:
- `C2BR2_BASE_SHA`;
- `C2BR2_SHA`;
- changed files;
- exact persistence-boundary correction;
- SAVEPOINT failure regression;
- acceptance matrix mapping invariants -> exact tests;
- focused/regression results;
- isolated notification-suite result;
- Ruff;
- `git diff --check`;
- Alembic head `0046`;
- clean worktree;
- remote branch SHA;
- production untouched.

Final marker:
`TELEGRAM_MTPROTO_C2BR2_NOTIFICATIONS_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
