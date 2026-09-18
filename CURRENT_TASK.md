# Current task — Telegram MTProto C2AR4: recent-head window cursor correctness

## Review status

C2A:
`ec44c406907b52eec95a879f0f05ccd404689859`

C2AR:
`c1044a22b81f132afdc97c711b1051dc3389c64c`

C2AR2:
`2cbec106effe6cb1b9f693d21fb981377518a6e2`

C2AR3:
`c87fb53d31827fb92e074fbf27628442f2a95ca4`

Independent review result: **C2AR3 REJECTED pending one narrow C2AR4 correction**.

The following C2AR3 work is accepted in code:
- recent-head state and historical sweep state are structurally separated;
- HEAD service does not update the sweep cursor;
- SWEEP service advances only the sweep cursor;
- per-peer HEAD/SWEEP modes alternate;
- account rotation advances to the peer after the last actually serviced peer rather than +1;
- >20-peer round-robin behavior is materially improved;
- inactive peer head/sweep/mode state is pruned;
- <=5/peer and <=20/account provider-call bounds remain intact;
- all C2AR2 read-error/backoff/malformed-candidate fixes remain accepted.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- Alembic `0041`;
- M3 not authorized.

## Remaining blocker — HEAD window stores the wrong "newest" marker

C2AR3 chooses a `head_candidate` from the top-5 recent window.

But after inspecting a HEAD candidate it stores:

`heads[peer]["newest"] = candidates[peer][0][0]`

In HEAD mode `candidates[peer]` contains only the current `head_candidate`.

Therefore after sampling the second-newest object, the persisted "newest" marker becomes the second-newest object instead of the actual newest object.

On the next HEAD service:
- actual newest != stored "newest";
- scheduler treats this as if a new message arrived;
- it jumps back to the newest object.

The resulting cycle can be:

`newest -> second -> newest -> second -> ...`

The third/fourth/fifth recent objects may never be revisited by HEAD sampling.

This defeats the intended bounded recent-window reconciliation.

The current focused test does not catch this because its target third-recent message was already fetched by the initial SWEEP run before HEAD sampling was evaluated.

## Required correction

Persist the **actual current head-window newest marker**, independently from the selected candidate.

For each peer during candidate construction:
- compute the actual `head_window[0]` cursor once;
- keep that actual-newest cursor alongside the chosen HEAD candidate;
- when the HEAD candidate is inspected, persist:
  - `cursor` = inspected HEAD candidate;
  - `newest` = actual current `head_window[0]`, NOT the inspected candidate unless it actually is newest.

Do not derive the newest marker from the one-element HEAD candidate list.

Expected behavior with stable top-5 window:

`newest -> second -> third -> fourth -> fifth -> newest -> ...`

When a genuinely new newest object arrives:
- actual newest differs from stored newest;
- next HEAD sample immediately selects the new newest;
- persisted newest becomes the real new newest;
- subsequent HEAD samples continue through the rest of the current top-5 window.

If the previous head cursor fell out of the top-5 window:
- fail safely back to current newest;
- then continue rotating.

## Preserve SWEEP/account fairness

Do not change the accepted C2AR3 invariants unless required by the direct fix:
- HEAD must never update sweep cursor;
- SWEEP must never use head cursor;
- modes alternate per peer;
- account rotation is after actual serviced peer/window;
- stale peer state pruned;
- <=5 provider calls/peer/run;
- <=20 provider calls/account/run.

## Required focused tests

Replace/strengthen the current recent-window test so it cannot pass via SWEEP accidentally.

### A. Pure HEAD-window rotation

Set up one peer with at least 5 recent objects.

Arrange state so:
- historical sweep cursor is already outside/below the recent head window;
- mode starts at HEAD;
- the target second/third/fourth/fifth objects cannot be fetched by SWEEP during the assertion interval.

Across HEAD service cycles prove exact order includes:

`newest, second, third, fourth, fifth`

before wrapping back to newest.

Directly assert after each HEAD call:
- `heads[peer].cursor` = inspected head object;
- `heads[peer].newest` remains equal to the actual newest object while the window is unchanged;
- sweep cursor remains byte-for-byte unchanged.

### B. Third-recent remote edit

After the third-recent object has already been checked once:
- mutate provider-side text for that same third-recent message;
- keep sweep cursor away from the head region;
- run bounded HEAD/SWEEP cycles;
- prove the third-recent object is rediscovered by HEAD rotation before sweep wrap;
- same local Object/external_id updated.

The test must prove the provider call that discovers the edit is a HEAD call, not incidental SWEEP.

### C. New newest insertion

After HEAD cursor has progressed to second/third:
- insert a new most-recent canonical object;
- next HEAD service must select the new newest;
- stored `newest` becomes this actual new object;
- following HEAD services continue into the rest of the current top-5 instead of bouncing only between two entries.

### D. Regression

Keep all prior focused guarantees green:
- exactly-20 peers: sweep progresses despite alternating head mode;
- >20 peers: next run starts at first unserved peer, not +1;
- scope-deactivation state pruning;
- malformed message_id zero provider call;
- read reject isolation;
- auth classification;
- real FloodWait retry_after;
- exact absence tombstone;
- mismatch no mutation;
- AI=false zero AI work;
- AI=true semantic enqueue;
- cadence 60/env override;
- A3/C1A/C1B/Q1;
- Alembic head 0046.

## Scope

Continue branch:
`review/telegram-mtproto-c2a-reconciliation`

Start from exact:
`C2AR3_BASE_SHA=c87fb53d31827fb92e074fbf27628442f2a95ca4`

Create exactly one corrective commit.
Do not rewrite/squash prior C2 commits.

Do NOT implement:
- C2B notifications;
- websocket/client push;
- UI;
- long-lived Telegram listener;
- production deploy/ref move;
- migration 0047;
- Bot API retirement.

## Checks

Run:
- focused C2A/C2AR/C2AR2/C2AR3/C2AR4;
- Telegram A1-A4.4/Q1/C1A/C1B;
- Telegram recurring queue/worker/backoff;
- Ruff changed Python files;
- git diff --check;
- Alembic head 0046.

## Deliverable

Return:
- `C2AR3_BASE_SHA=c87fb53d31827fb92e074fbf27628442f2a95ca4`
- `C2AR4_SHA=<exact sha>`
- changed files
- exact actual-newest persistence rule
- observed HEAD rotation sequence in test
- proof third-recent edit is found by HEAD rather than SWEEP
- new-newest insertion behavior
- focused/regression tests
- Ruff
- git diff --check
- Alembic 0046
- production untouched

Final marker:
`TELEGRAM_MTPROTO_C2AR4_RECONCILIATION_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
