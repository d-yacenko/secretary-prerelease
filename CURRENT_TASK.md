# Current task — Telegram MTProto Q1R2: catch-up boundedness correction

## Review status

Q1 implementation:
`b306b6d1ad1a4e7ae0d2dd3260bd5b746d2f2595`

Q1R implementation:
`39e3f2f24ca1bcd695e27d070bfde229c131c7cb`

Q1R was independently reviewed.

The following Q1R areas are ACCEPTED in code:
- AI-vs-non-AI read boundary via explicit `ai_only` callers;
- ordinary A4.3 transport visibility preserved for non-AI Graph/ObjectQuery/Workspace/conversation reads;
- execution-time fail-closed guards for queued AI work;
- conversation-stack summary guard uses actual payload `object_ids`.

Q1R is **REJECTED pending one narrow Q1R2 correction** in embedding catch-up boundedness/dedupe accounting.

Production remains untouched:
- production runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- production Alembic `0041`;
- M3 not authorized.

## Remaining blocker

Current catch-up checks:

- whether *any* PENDING/RUNNING `embed_object` job exists for the object;
- then calls `enqueue_embed_object()`, which deduplicates using the **current embedding_input_signature**;
- then increments its local `queued` count only when that broad pre-check was empty.

This is incorrect.

If a pending/running embed job exists for the same object but with an old/different signature:
- it is not equivalent work;
- `enqueue_embed_object()` correctly creates a new current-signature job;
- but catch-up does not increment `queued`;
- therefore one run can create more than `TELEGRAM_MTPROTO_EMBED_CATCHUP_MAX_PER_RUN=10` new jobs.

The current focused test does not catch this because its synthetic pending jobs omit `embedding_input_signature` and it asserts the returned counter rather than the actual newly-enqueued current-signature jobs.

There is also a cursor precision issue: the cursor is currently moved to `objects[-1]` before the loop, even when the loop stops after reaching enqueue budget. This jumps over rows that were loaded but never inspected. Wrap-around may eventually revisit them, but the intended keyset contract is simpler and safer if the cursor represents the last row actually inspected.

## Q1R2 required correction

Start from exact:
`Q1R_BASE_SHA=39e3f2f24ca1bcd695e27d070bfde229c131c7cb`

Work on existing branch:
`review/telegram-mtproto-q1-ai-quarantine`

Create exactly one new correction commit. Do not rewrite/squash Q1/Q1R.

### 1. Equivalent-job dedupe

For each candidate object:
- compute the current `embedding_input_signature(obj)`;
- treat a pending/running embed job as equivalent only when BOTH:
  - `payload.object_id == obj.id`
  - `payload.embedding_input_signature == current_signature`
- an old-signature pending/running job must NOT suppress the current-signature catch-up job;
- an equivalent current-signature pending/running job must not be duplicated and must not consume enqueue budget.

The catch-up's enqueue counter must reflect **actual new current-signature jobs created by this catch-up run**.

Do not use a broad object-id-only pre-check for budget accounting.

A small reusable helper is acceptable if it makes the signature semantics explicit. Avoid unrelated refactors.

### 2. Hard enqueue bound

One invocation of catch-up must create at most:

`TELEGRAM_MTPROTO_EMBED_CATCHUP_MAX_PER_RUN = 10`

new embed jobs.

This must be proven by actual DB job count/signature assertions, not only by the method's return value.

### 3. Cursor semantics

Use the existing bounded keyset scan, but make the stored cursor represent the **last object actually inspected**.

Requirements:
- inspect at most `TELEGRAM_MTPROTO_EMBED_CATCHUP_SCAN_LIMIT` rows per invocation;
- stop when 10 new current-signature jobs have actually been created;
- advance cursor across current/equivalent-pending rows without consuming enqueue budget;
- do not advance cursor past rows that were never inspected;
- if end of keyspace is reached, next invocation may wrap safely to the start;
- repeated invocations must converge.

No new table/scheduler/daemon/migration.

### 4. Focused tests

Add/adjust tests proving:

A. Old-signature pending jobs:
- create >10 eligible MTProto objects;
- give the leading objects pending/running embed jobs with an intentionally different/old `embedding_input_signature`;
- run catch-up;
- assert no more than 10 **new current-signature** jobs were created;
- assert returned enqueue count equals actual new jobs;
- assert old-signature jobs did not falsely consume/destroy eligibility.

B. Equivalent current-signature jobs:
- pending/running current-signature work is not duplicated;
- it does not consume the 10-new-job budget;
- later missing/stale objects in the scan can still be enqueued.

C. Cursor/convergence:
- cursor equals the last actually inspected object, not blindly the end of the loaded window;
- a subsequent invocation continues after that point;
- repeated invocations eventually enqueue every eligible missing/stale object;
- no eligible object is permanently skipped.

D. Existing Q1/Q1R invariants remain:
- AI=false no-op catch-up;
- active/owned/account-matched only;
- inactive, wrong-account, malformed excluded;
- AI/non-AI boundary unchanged;
- queued-job true->false guards unchanged;
- Bot API/other providers unaffected;
- Alembic head remains `0046`.

## Scope

Do NOT alter already-accepted Q1R AI/non-AI service boundaries unless required to fix a direct regression.
Do NOT implement CRUD/send/reply yet.
Do NOT touch UI.
Do NOT update main.
Do NOT touch production.
Do NOT add migration `0047`.

## Deliverable

Return:
- `Q1R_BASE_SHA=39e3f2f24ca1bcd695e27d070bfde229c131c7cb`
- `Q1R2_SHA=<exact sha>`
- changed files;
- exact equivalent-job signature rule;
- exact cursor advancement rule;
- proof actual newly-created embed jobs <= 10/run;
- focused test results;
- Telegram/Q1 regression results;
- Ruff;
- git diff --check;
- Alembic head `0046`;
- production untouched.

Final marker:
`TELEGRAM_MTPROTO_Q1R2_AI_QUARANTINE_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
