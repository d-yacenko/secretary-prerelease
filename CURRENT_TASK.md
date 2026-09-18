# Current task — Telegram MTProto C2AR: reconciliation fairness + provider backoff corrective

## Review status

C2A implementation:
`ec44c406907b52eec95a879f0f05ccd404689859`

Independent review result: **REJECTED pending C2AR corrective**.

Accepted C2A parts:
- Telegram default recurring cadence 300 -> 60 seconds;
- existing env override retained;
- A3 materializer reused for remote edits;
- confirmed exact absence is the intended delete/tombstone signal;
- canonical MTProto presentation-title helper is shared by history/send/edit;
- Q1 AI quarantine remains intact.

Production remains untouched:
- production runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- production Alembic `0041`;
- M3 not authorized.

## Blocker 1 — current global Object cursor can starve eligible messages

Current C2A reconciliation selects up to 100 rows using only:
- user_id;
- provider=telegram;
- kind=chat_message;
- deleted_at is null;
- Object.id ordering.

It then filters transport/account/peer/scope in Python.

Problems:

1. A window containing legacy Bot Telegram, another MTProto account, inactive-scope rows, or malformed rows can be repeatedly rescanned because the reconciliation cursor only advances for a row that reaches an exact provider lookup.
2. After a peer reaches the 5-lookups-per-peer budget, later rows for that peer are skipped. The loop may then inspect another peer and advance the global cursor beyond those skipped rows. On wrap, the same first five rows of the busy peer can be selected again, so some messages can be permanently starved.
3. Ordering by UUID Object.id is not a recent-message policy and does not satisfy C2A's near-realtime intent.

### Required design

Redesign candidate scheduling so all of these are simultaneously true:

- only canonical MTProto objects for the current account and active A4.3 scope are reconciliation candidates;
- non-tombstoned only;
- malformed metadata fails closed but cannot permanently pin progress;
- recent objects are preferred;
- max 20 provider lookups/account/run;
- max 5 provider lookups/peer/run;
- no eligible candidate is permanently skipped because another peer is busy;
- repeated runs converge/fairly revisit candidates;
- scope deactivation excludes a peer immediately;
- no new DB table/migration/job/daemon.

Preferred approach:

- drive reconciliation by the already-active durable selections/peers;
- maintain non-secret reconciliation progress in the existing recurring job payload, with per-peer cursors (or an equivalent provably fair structure);
- for each peer, query only that account+peer's canonical active non-tombstoned MTProto objects;
- order recent-first using a stable tuple such as `occurred_at DESC, id DESC` (or another stable recent-first order);
- inspect up to 5 per peer and rotate through active peers until the account total reaches 20;
- a peer cursor wraps safely after reaching the end;
- removed/inactive peers have stale cursor state ignored/pruned;
- do not advance a peer past provider-uninspected candidates.

An alternative implementation is acceptable only if focused tests prove no starvation with multiple busy peers and mixed non-candidates.

Do not use unsafe JSON integer casts. Reuse accepted string/text-safe metadata filtering patterns where appropriate.

## Blocker 2 — FloodWait/provider-wide transient failures are swallowed

Current `TelethonMtprotoTransport.fetch_message()` has no explicit FloodWait path.
FloodWait and many lookup transport failures become `TelegramMtprotoWriteUncertainError`.

`reconcile_recent_messages()` catches that and continues with more provider lookups.

This violates the accepted Telegram recurring backoff contract.

### Required error semantics

Exact-message reconciliation is a read, not an external write.

For lookup:
- FloodWait -> `TelegramMtprotoProviderUnavailableError` with sanitized `retry_after_seconds`;
- Telegram/server/network/provider-wide transient failure -> provider-unavailable/transient error appropriate for existing recurring sync classification;
- auth/session invalid -> existing non-retryable authentication failure semantics;
- malformed local durable reference / exact peer mismatch -> peer-local failure, no mutation;
- trustworthy exact absence -> normal `None`/absence signal, not an exception.

At reconciliation layer:
- provider-wide transient/auth/config failures MUST propagate out of the account recurring run so the existing worker/finalizer applies the Telegram retry/failure policy;
- do not continue issuing the remaining lookup budget after FloodWait/provider outage;
- peer/message-local malformed/mismatch errors may be isolated and continue.

Do not misuse `TelegramMtprotoWriteUncertainError` for read-only lookup backoff.

### Tests

Prove:
- FloodWait on first reconciliation lookup aborts further lookups;
- recurring failure classification is transient/retryable and preserves retry_after;
- ServerError/provider-wide transient similarly does not cause mass tombstone or continued hammering;
- exact absence still tombstones;
- peer-local mismatch does not abort unrelated peers.

## Blocker 3 — missing focused acceptance coverage

Add tests that were required by C2A but are not present in the current 8-test focused file:

### Candidate isolation
- legacy Telegram Bot object before eligible MTProto rows cannot pin/starve reconciliation;
- MTProto object for another account cannot pin/starve current account;
- inactive-scope peer is not fetched;
- malformed candidate does not permanently pin progress.

### Multi-peer fairness
Construct at least:
- one busy peer with >10 eligible objects;
- a second peer with eligible objects;
- optionally a third peer.

Across repeated runs prove:
- <=5 lookups/peer/run;
- <=20 lookups/account/run;
- second peer is serviced even when first peer is busy;
- every eligible object in the bounded test set is eventually inspected;
- cursor/progress state never advances past an object that is silently lost forever.

### Recent-first behavior
Prove newly/recently occurred objects are considered before materially older objects for a peer, while repeated runs still eventually revisit older eligible rows.

### Scope changes
- deactivate a peer between runs;
- next run performs zero exact-message lookups for that peer;
- stale payload progress for it does not block remaining active peers.

### Existing behavior
- recurring A3 new-message import still works;
- remote edit same object/external_id;
- AI=false zero AI jobs;
- AI=true normal signature-aware enqueue;
- confirmed absence tombstones exact object;
- transient provider failure never tombstones;
- canonical long-title send/edit/history normalization remains identical;
- C1A/C1B/Q1 regressions remain green;
- Alembic head remains 0046.

## Preserve accepted C2A work

Keep:
- 60-second Telegram default cadence;
- environment override;
- no daemon/listener/new worker;
- A3 history for new messages;
- canonical title helper;
- Q1 AI quarantine;
- exact-message reconciliation concept;
- confirmed absence -> tombstone;
- no migration.

## Scope

Continue branch:
`review/telegram-mtproto-c2a-reconciliation`

Start from exact:
`C2A_BASE_SHA=ec44c406907b52eec95a879f0f05ccd404689859`

Create one corrective commit on top.
Do not rewrite/squash C2A.

Do NOT implement:
- C2B notification/event surface;
- websocket/client push;
- OS/mobile notifications;
- client UI;
- long-lived Telethon listener;
- production deploy/ref move;
- migration 0047;
- Bot API retirement.

## Required checks

Run:
- focused C2A/C2AR tests;
- Telegram A1-A4.4/Q1/C1A/C1B regressions;
- recurring scheduler/queue/worker Telegram failure tests;
- action-plan/external-action regressions as relevant;
- Ruff changed Python files;
- git diff --check;
- Alembic head 0046.

## Deliverable

Return:
- `C2A_BASE_SHA=ec44c406907b52eec95a879f0f05ccd404689859`
- `C2AR_SHA=<exact sha>`
- changed files
- exact fairness/cursor design
- recent-first ordering rule
- exact provider-transient/FloodWait rule
- proof <=20/account and <=5/peer
- convergence/starvation test results
- focused/regression tests
- Ruff
- git diff --check
- Alembic head 0046
- production untouched

Final marker:
`TELEGRAM_MTPROTO_C2AR_RECONCILIATION_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
