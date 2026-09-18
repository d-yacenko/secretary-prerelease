# Current task — Telegram MTProto C2AR3: separate head/sweep progress + account peer fairness

## Review status

C2A:
`ec44c406907b52eec95a879f0f05ccd404689859`

C2AR:
`c1044a22b81f132afdc97c711b1051dc3389c64c`

C2AR2:
`2cbec106effe6cb1b9f693d21fb981377518a6e2`

Independent review result: **C2AR2 REJECTED pending one narrow C2AR3 corrective**.

The following C2AR2 areas are ACCEPTED in code:
- malformed message_id is skipped locally without provider call/budget consumption;
- read-only auth/session invalid now maps to `TelegramMtprotoAuthorizationInvalidError`;
- peer/message-local deterministic read rejection has a separate `TelegramMtprotoReadRejectedError`;
- FloodWait/server/network read failures map to provider-unavailable/transient semantics;
- real Telethon FloodWait translation preserves retry_after;
- existing recurring finalizer already proves Telegram retry_after is honored;
- sweep wrap concept is present;
- provider bounds remain <=5/peer and <=20/account.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- Alembic `0041`;
- M3 not authorized.

## Remaining blocker 1 — head sampling corrupts the sweep cursor

C2AR2 prepends the newest head object to each peer's candidate list, but then writes
that head object's `(occurred_at, id)` into the same
`telegram_reconcile_peer_cursors` state used for historical sweep progress.

This is incorrect because head sampling and historical sweep are two independent traversals.

Concrete failure:
- with 20 active peers and account limit 20, the first pass spends one provider call on each peer's head;
- account budget is then exhausted;
- every peer's sweep cursor has been overwritten to the head;
- no peer advances its historical sweep;
- the same pattern can repeat indefinitely.

With >20 active peers the problem combines with account rotation and can leave old rows effectively unreconciled for very long periods.

### Required correction

Separate **recent-head progress** from **historical sweep progress**.

Use the existing recurring payload only. No schema/migration.

Preferred payload shape:
- `telegram_reconcile_peer_cursors` = historical sweep cursor only;
- `telegram_reconcile_peer_heads` = recent-head sampling state per peer;
- account-level peer rotation/cursor = next peer to service.

A head lookup MUST NEVER overwrite or move the sweep cursor.

A sweep cursor MUST only advance when a sweep row is actually inspected.

When sweep reaches end:
- wrap/reset sweep state safely;
- do not depend on head state for wrap.

## Remaining blocker 2 — recent head must be a rotating window, not only the single newest object

C2AR2 always checks exactly the newest object as the head sample.

That catches:
- a newly inserted newest object;
- an edit to the current newest object.

But it does not catch an edit to the second/third recent already-checked object until the full historical sweep eventually wraps.

C2AR2 acceptance explicitly required a recent already-checked edit to be detected without waiting for a full sweep.

### Required correction

Implement a small bounded recent-head window, independent from the historical sweep.

Preferred:
- newest 3 to 5 eligible objects per peer;
- maintain a per-peer head position/cursor in `telegram_reconcile_peer_heads`;
- each head service advances within that recent window and wraps independently;
- if the recent window changes because a new message arrives, sampling must naturally include it promptly;
- head sampling must never mutate sweep state.

Equivalent design is acceptable if it proves bounded revisit latency for more than only the single newest object.

## Remaining blocker 3 — account-level peer rotation must advance by actual service, not +1

C2AR/C2AR2 currently sets:

`rotation = (rotation + 1) % len(peer_ids)`

independent of how many peers were actually serviced.

With many active peers and a 20-call account cap, this creates a sliding window that introduces only about one new peer per run.

Example:
- 100 active peers;
- run 1 can service peers 1..20;
- run 2 starts at peer 2 and mostly services peers 2..21;
- the tail can wait many minutes despite available round-robin semantics.

### Required correction

Account-level rotation/cursor must point to the **next peer after the last peer actually serviced/attempted under the account budget**.

Requirements:
- with N peers and one provider slot allocated per peer, peers outside the first account window must enter on the next run, not one-by-one;
- no active peer is starved by earlier peers;
- stale state for deactivated peers is ignored and pruned;
- deterministic ordering across runs.

Do not infer fairness only from sorted peer IDs.

## Scheduling rule

Use any simple deterministic scheduler that proves both head and sweep make progress.

A recommended design is per-peer alternating service mode:

- peer state records whether its next reconciliation service is `head` or `sweep`;
- when a peer receives one provider lookup:
  - HEAD mode uses independent recent-head state;
  - SWEEP mode uses independent historical sweep state;
- then toggle the peer's next mode;
- if budget remains after all active peers have one service slot, a peer may receive additional slots, up to 5 total in the run;
- account cursor advances after actual peer service.

This gives progress even when active peer count >=20.

An equivalent design is acceptable if tests prove:
- head cannot starve sweep;
- sweep cannot starve head;
- >=20 active peers still make sweep progress across repeated runs.

## Candidate / budget invariants

Preserve:
- canonical MTProto only;
- current account only;
- active scope only;
- non-tombstoned;
- stable recent ordering;
- malformed metadata fail closed locally;
- <=5 actual provider calls per peer/run;
- <=20 actual provider calls account/run.

Local malformed rows:
- may advance the relevant local traversal cursor;
- consume zero provider-call budget;
- cannot pin head or sweep forever.

Provider errors:
- accepted C2AR2 taxonomy remains unchanged.

## Payload hygiene

At each run:
- prune head/sweep state for peers no longer active;
- do not retain unbounded stale peer keys;
- payload must remain non-secret.

## Required focused tests

Add tests proving the actual bug is closed.

### Separate head vs sweep

1. Create exactly 20 active peers, each with:
   - a recent head object;
   - at least one older sweep object.

2. Run reconciliation once:
   - <=20 provider calls;
   - each serviced peer may consume the account window with head work.

3. Run repeatedly:
   - every peer's historical sweep eventually advances;
   - head sampling does not reset the sweep cursor;
   - old objects are actually provider-fetched.

Also assert directly:
- after a head-only service for a peer, its sweep cursor is unchanged.

### Recent-head window

For one peer with at least 5 recent objects plus older history:
- advance sweep away from the head;
- edit the second or third newest already-checked object provider-side;
- prove reconciliation rediscovers that edit through head-window sampling before historical sweep wraps;
- insert a new newest object and prove it enters head sampling promptly;
- older sweep still progresses.

### >20 peer account fairness

Create >20 active peers, e.g. 25 or 40.

Across repeated runs:
- actual calls <=20/account/run;
- <=5/peer/run;
- the next run starts from the first unserved peer after the previous account window;
- all peers receive service within the expected round-robin number of runs;
- no one-new-peer-per-run sliding-window behavior.

### Scope churn / payload prune

- service a peer so head/sweep state exists;
- deactivate it;
- next run performs zero calls for it;
- its head/sweep payload keys are removed/ignored;
- remaining peers continue.

### Existing C2AR2 behavior

Keep tests for:
- malformed message_id zero provider call;
- peer-local read reject isolation;
- auth-invalid -> authentication/non-retryable;
- real Telethon FloodWait -> provider unavailable + same retry_after;
- recurring retry_after finalization;
- exact absence -> tombstone;
- mismatch -> no mutation;
- AI=false zero AI work;
- AI=true semantic enqueue;
- cadence 60/env override;
- A3/C1A/C1B/Q1 regressions;
- Alembic head 0046.

## Preserve accepted architecture

Do NOT redesign:
- Postgres recurring queue;
- 60-second Telegram default cadence;
- A3 history/materializer;
- exact-message reconciliation;
- confirmed absence tombstone;
- C2AR2 read-error taxonomy;
- Q1 AI quarantine;
- canonical title helper.

Do NOT implement:
- C2B notifications;
- websocket/client push;
- UI;
- long-lived Telegram listener;
- production deploy/ref move;
- migration 0047;
- Bot API retirement.

## Branch / deliverable

Continue:
`review/telegram-mtproto-c2a-reconciliation`

Start from exact:
`C2AR2_BASE_SHA=2cbec106effe6cb1b9f693d21fb981377518a6e2`

Create one corrective commit on top. Do not rewrite/squash prior C2 commits.

Run:
- focused C2A/C2AR/C2AR2/C2AR3;
- Telegram A1-A4.4/Q1/C1A/C1B;
- recurring Telegram queue/worker/backoff tests;
- Ruff changed Python files;
- git diff --check;
- Alembic head 0046.

Return:
- `C2AR2_BASE_SHA=2cbec106effe6cb1b9f693d21fb981377518a6e2`
- `C2AR3_SHA=<exact sha>`
- changed files
- separate head-state vs sweep-state design
- recent-head window rule
- account peer rotation rule
- payload-pruning rule
- proof historical sweep advances with >=20 active peers
- proof >20 peers rotate by service window, not +1
- focused/regression test results
- Ruff
- git diff --check
- Alembic 0046
- production untouched

Final marker:
`TELEGRAM_MTPROTO_C2AR3_RECONCILIATION_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
