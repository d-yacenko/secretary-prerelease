# Current task — Telegram MTProto Q1R: AI quarantine corrective

## Review status

Q1 implementation commit `b306b6d1ad1a4e7ae0d2dd3260bd5b746d2f2595` was independently reviewed and is **REJECTED pending correction**.

The architecture is retained:
- `TELEGRAM_MTPROTO_AI_ENABLED=false` by default;
- MTProto transport/storage/Inbox remain usable;
- canonical MTProto objects are excluded from ML/LLM while disabled;
- no schema migration;
- future true enables AI with bounded catch-up.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- Alembic `0041`;
- M3 not authorized.

## Q1R blockers to correct

### 1. Catch-up can starve forever

Current Q1 catch-up selects the first 10 active MTProto objects and only afterwards checks whether each already has a current embedding / pending job.

Therefore if those first 10 are already current or pending, later missing/stale objects are never reached.

Fix the catch-up so repeated recurring runs **provably converge**.

Preferred approach:
- maintain a bounded scan cursor in the existing recurring Telegram job payload, analogous to the existing peer cursor;
- scan a bounded ordered window each run;
- advance the cursor regardless of whether a scanned object was already current/pending;
- enqueue at most 10 missing/stale objects per run;
- wrap safely at end;
- preserve ownership, active scope, account match and canonical MTProto checks;
- remain idempotent and dedupe pending/running equivalent embed jobs;
- no new scheduler/daemon/table/migration.

An equivalent bounded design is acceptable only if it cannot be permanently blocked by already-current early rows.

### 2. AI capability must not become a global user-visibility gate

Q1 replaced accepted A4.3 transport visibility with the AI predicate inside shared deterministic read services.

This is incorrect where those services back ordinary user-facing APIs.

In particular `GraphService` is used directly by `backend/app/api/routes/graph.py` for ordinary object/neighbors/context endpoints. With AI disabled, active MTProto objects must not disappear merely because the graph API is non-AI.

Restore the separation:

- ordinary/non-AI reads use the accepted `telegram_mtproto_active_object_predicate`;
- assistant/LLM/retrieval/context paths use the new AI eligibility gate.

Audit at minimum:
- `GraphService`
- `GraphWorkspaceService`
- `ObjectQueryService`
- `conversation_member_read`
- their actual callers.

If a shared service has both AI and non-AI callers, introduce an explicit AI-only mode/caller boundary rather than globally changing its semantics.

The invariant is:
`TELEGRAM_MTPROTO_AI_ENABLED` controls AI/ML eligibility only, not ordinary transport visibility.

Inbox behavior from Q1 must remain unchanged: active MTProto visible, inactive hidden by A4.3.

### 3. Existing queued AI work must fail closed after true -> false

Do not rely only on enqueue-time filtering.

If the flag is changed from true to false while Telegram AI jobs are already PENDING/RUNNING, any handler that can consume a canonical MTProto object through AI/ML must re-check eligibility before doing the work.

Audit object-specific background handlers, including at minimum:
- embed;
- summarize;
- correlate;
- auto-label/classification;
- temporal/AI-derived processing where applicable;
- conversation/proactive processing paths if they can consume MTProto content.

Use the central eligibility policy. Do not duplicate ad-hoc provider checks.

A queued job created while enabled must become a safe no-op if the flag is disabled before execution.

### 4. Close the Q1 test gaps

Add focused tests proving all of the following, not just relying on old suites:

- active scope MTProto remains visible in `RecentSourceService` when AI=false;
- inactive scope MTProto remains hidden;
- ordinary graph API/service visibility remains based on A4.3 and does not disappear only because AI=false;
- assistant/retrieval/context path still excludes the same active object when AI=false;
- direct object context cannot bypass the gate;
- AI=true restores prior A4.3 assistant visibility;
- catch-up no-op when false;
- catch-up with >10 rows progresses past already-current/pending leading rows and reaches later stale/missing rows;
- repeated runs converge;
- inactive/foreign-account/malformed MTProto rows are never enqueued;
- pending/running equivalent embed jobs are not duplicated;
- a job queued while true is a no-op if false before handler execution;
- Bot API Telegram and other providers remain unaffected;
- Alembic head remains `0046`.

## Scope

Start from the published Q1 review commit:
`b306b6d1ad1a4e7ae0d2dd3260bd5b746d2f2595`

Create a new correction commit on:
`review/telegram-mtproto-q1-ai-quarantine`

Do not rewrite or squash the existing Q1 commit.

No production access/mutation.
No main update.
No migration.
No CRUD/send/reply work yet.
No UI work.

## Deliverable

Return:
- Q1_BASE_SHA=`b306b6d1ad1a4e7ae0d2dd3260bd5b746d2f2595`
- Q1R_SHA
- changed files
- concise explanation of:
  - convergence mechanism;
  - AI-vs-non-AI read boundary;
  - queued-job fail-closed guard;
- focused test commands/results;
- Telegram regression result;
- relevant graph/retrieval/context/background test results;
- Ruff;
- git diff --check;
- Alembic head `0046`;
- confirmation production untouched.

Final marker:
`TELEGRAM_MTPROTO_Q1R_AI_QUARANTINE_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
