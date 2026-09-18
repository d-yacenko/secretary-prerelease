# Current task — Telegram MTProto C2AR2: recurring recent-head + sweep correctness

## Review status

C2A:
`ec44c406907b52eec95a879f0f05ccd404689859`

C2AR:
`c1044a22b81f132afdc97c711b1051dc3389c64c`

Independent review result: **C2AR REJECTED pending narrow C2AR2 corrective**.

Accepted C2AR work:
- per-peer progress replaced the unsafe global Object cursor;
- active selections drive peer scheduling;
- candidate query is current-user/current-account/canonical MTProto and non-tombstoned;
- stable `occurred_at DESC, id DESC` ordering;
- <=5 lookups/peer/run and <=20/account/run structure;
- peer rotation;
- FloodWait/server generic read failures now use provider-unavailable semantics rather than write-uncertain;
- provider-wide unavailable errors propagate out of reconciliation.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- Alembic `0041`;
- M3 not authorized.

## Blocker 1 — per-peer sweep never wraps/revisits the recent head

Current per-peer cursor query only selects rows older than the stored
`(occurred_at, id)` cursor.

When it reaches the oldest eligible row:
- the next query is empty;
- the cursor remains at the old tail;
- there is no reset/wrap;
- that peer can stop being reconciled forever.

Additionally, a new recent object or a remote edit of a recently checked object can sit above the cursor and is not revisited promptly while the sweep moves through older history.

That does not satisfy near-realtime reconciliation.

### Required design

Keep a bounded per-peer sweep cursor, but combine it with **recurring recent-head sampling**.

The exact split is implementation-defined, but must prove both properties:

1. Recent head is revisited on a bounded cadence independent of sweep depth.
2. Older eligible objects still make progress and eventually get revisited.

Preferred simple design per serviced peer/run:
- reserve part of the <=5 provider-lookup budget for the newest eligible objects (head sample);
- reserve the remaining budget for the persistent older sweep cursor;
- dedupe objects selected by both portions in the same run;
- when the sweep reaches end, reset/wrap the sweep cursor safely to the head for the next sweep epoch;
- a newly inserted/recent object after cursor advancement must be eligible for a prompt head check, not wait for a full historical sweep.

An alternating head-run/sweep-run strategy is also acceptable if recent head latency remains bounded and tests prove older convergence.

Do not increase:
- 5 provider lookups/peer/run;
- 20 provider lookups/account/run.

No new DB state/table/job/daemon.

## Blocker 2 — local malformed candidates must fail closed without provider calls or cursor pinning

C2AR no longer validates `metadata.message_id` before calling `fetch_message`.

Required:
- message_id must be an actual int, bool excluded, >0;
- malformed local metadata => zero provider lookup for that row;
- it must not consume provider-lookup budget;
- local scan/sweep progress must advance past it so it cannot pin the peer forever;
- no unsafe JSON integer cast is required;
- no local mutation/tombstone based on malformed metadata.

If other canonical metadata required for reconciliation is malformed, apply the same fail-closed/progress rule.

Distinguish:
- bounded local rows inspected;
- actual provider lookups issued.

Hard provider limits are based on actual provider calls.

## Blocker 3 — lookup auth failures must use canonical authentication semantics

`fetch_message()` currently maps revoked/invalid auth/session conditions to
`TelegramMtprotoWriteDefiniteError`.

The recurring worker therefore classifies them as `unknown`, not the existing Telegram
`authentication` failure.

Required:
- revoked/invalid auth/session in read-only `fetch_message()` ->
  `TelegramMtprotoAuthorizationInvalidError`;
- recurring reconciliation propagates it;
- `classify_telegram_sync_failure()` returns authentication/non-retryable;
- peer-local lookup rejection is not mislabeled as account authentication.

For deterministic peer/message-local read rejection, use an existing suitable peer-local error or add a narrow read-only lookup-rejected error and isolate it at reconciliation level. Do not abort all other peers for a single malformed/inaccessible message unless the error is genuinely account/provider-wide.

## Blocker 4 — real backoff integration must be tested, not only a fake final exception

Current focused FloodWait test injects a prebuilt
`TelegramMtprotoProviderUnavailableError("busy", 23)`.

It does not prove the new Telethon branch works.

Add tests proving:

1. real/fake-Telethon `FloodWaitError` raised by `get_messages` is translated by
   `TelethonMtprotoTransport.fetch_message()` to
   `TelegramMtprotoProviderUnavailableError` with the same retry_after seconds;
2. reconciliation stops after that lookup;
3. `classify_telegram_sync_failure()` returns
   `("transient", True, retry_after)`;
4. recurring finalization/queue uses the retry_after delay for the Telegram job;
5. auth-invalid lookup classifies as `authentication, False`.

## Mandatory focused coverage

Add/strengthen tests for all of these.

### Head + sweep + wrap
- peer has > one sweep window;
- repeated runs advance older sweep;
- end-of-sweep wraps safely;
- after wrap, recent rows are revisited;
- insert a new most-recent eligible object after cursor already advanced: it is checked on bounded recent-head cadence;
- remote edit to a recent already-checked object is discovered without waiting for full sweep;
- every older bounded-test object is eventually inspected too.

### Multi-peer bounds
- busy peer + second/third peers;
- actual provider calls <=5/peer/run;
- actual provider calls <=20/account/run;
- rotation prevents peer starvation.

### Candidate sanitation
- malformed message_id => zero provider call for that row;
- malformed row does not pin progress;
- legacy Bot object ignored;
- other-account MTProto object ignored;
- inactive scope peer ignored;
- deactivated peer stale cursor is ignored/pruned from payload.

### Error isolation
- provider-wide FloodWait/server/auth aborts account run as appropriate;
- peer-local reference/message rejection does not block unrelated peers;
- mismatch result does not mutate/tombstone and unrelated peer continues;
- exact trustworthy absence still tombstones.

### Existing behavior
- default cadence remains 60;
- env override works;
- A3 new-message sync remains;
- remote edit uses same object/external_id;
- Q1 AI=false zero AI work;
- AI=true signature-aware semantic update;
- canonical title helper remains shared;
- C1A/C1B regressions remain green;
- Alembic head remains 0046.

## Preserve accepted design

Do NOT redesign:
- existing recurring Postgres queue;
- 60-second default cadence;
- A3 history/materializer new-message path;
- per-peer reconciliation state in recurring payload;
- exact-message reconciliation;
- confirmed exact absence -> tombstone;
- Q1 AI quarantine;
- canonical title helper.

Do NOT implement:
- C2B notifications;
- websocket/client push;
- client UI;
- long-lived Telegram listener;
- production deploy/ref move;
- migration 0047;
- Bot API retirement.

## Branch / deliverable

Continue:
`review/telegram-mtproto-c2a-reconciliation`

Start from exact:
`C2AR_BASE_SHA=c1044a22b81f132afdc97c711b1051dc3389c64c`

Create one corrective commit on top. Do not rewrite/squash C2A/C2AR.

Run:
- focused C2A/C2AR/C2AR2 tests;
- Telegram A1-A4.4/Q1/C1A/C1B;
- Telegram recurring scheduler/queue/worker failure/backoff tests;
- Ruff changed Python files;
- git diff --check;
- Alembic head 0046.

Return:
- `C2AR_BASE_SHA=c1044a22b81f132afdc97c711b1051dc3389c64c`
- `C2AR2_SHA=<exact sha>`
- changed files
- exact head-vs-sweep budget/cursor rule
- wrap rule
- malformed-candidate progress rule
- read-error taxonomy
- real FloodWait/backoff integration proof
- <=20/account and <=5/peer proof using actual provider call counts
- focused/regression results
- Ruff
- git diff --check
- Alembic 0046
- production untouched

Final marker:
`TELEGRAM_MTPROTO_C2AR2_RECONCILIATION_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
