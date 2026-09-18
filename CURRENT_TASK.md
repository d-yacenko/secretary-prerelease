# Current task — Telegram MTProto C1BR2: edit pipeline + delete preflight semantics

## Review status

C1B:
`4d61ebeb2d96e5bfb6393ef3e39d214cd814fc51`

C1BR:
`a7c36d8d7053ad62371207773a7aa142a9fe3407`

Independent review result: **C1BR REJECTED pending one narrow C1BR2 corrective**.

The following C1BR areas are accepted in code:
- deterministic Telethon BadRequest/Forbidden/NotFound/auth rejection mapping is now separated from server/timeout ambiguity;
- delete has provider-side exact-message preflight before destructive delete;
- durable SUCCEEDED metadata exists for replay-safe local convergence;
- edit/delete replay can repair local state without provider resend;
- first successful mark-read now reports a real mutation;
- execution-effect wording no longer classifies these mutations as created objects.

Production remains untouched:
- production runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- production Alembic `0041`;
- M3 NOT authorized.

## C1BR2 blocker 1 — edit local convergence bypasses the accepted semantic pipeline

C1BR changed edit convergence from `TelegramObjectMaterializer` to direct mutation of
`Object.body/title/metadata_`.

That is replay-safe, but it bypasses semantic-update enqueue behavior.

Consequences:
- with `TELEGRAM_MTPROTO_AI_ENABLED=false`, zero AI work is correct;
- with `TELEGRAM_MTPROTO_AI_ENABLED=true`, an edited Telegram object keeps the old embedding unless another sync later happens to repair it.

This violates the Q1 future-activation contract and C1B semantic-update requirement.

### Required correction

Keep direct replay-safe convergence if desired, but after applying an actual semantic edit:
- call the existing centralized embedding enqueue path, preferably `enqueue_embed_object(session, obj.id, obj.user_id)`;
- rely on Q1 central AI eligibility gate:
  - AI=false => no job;
  - AI=true => enqueue current-signature embedding work when missing/stale;
- preserve existing signature dedupe;
- replay after rolled-back local convergence must also be able to recreate the missing current-signature job idempotently;
- do not enqueue if the object body/title is already identical and the current embedding provenance/job is already current.

Do not create a Telegram-specific embedding mechanism.

### Tests

Add focused tests proving:
1. AI=false edit changes local body/title but creates zero embed jobs.
2. AI=true edit creates exactly the required current-signature embed work.
3. replay repair with AI=true does not create duplicate equivalent pending/running jobs.
4. current embedding provenance / equivalent current-signature pending work is respected by existing dedupe.

## C1BR2 blocker 2 — preflight lookup failure occurs before delete and must not be recorded as an ambiguous destructive write

Current `delete()` performs:
- `fetch_message` preflight;
- then destructive `delete_message`;

but both are inside the same exception block.

If `fetch_message` raises `TelegramMtprotoWriteUncertainError` because of timeout/server/network failure, the whole delete attempt is persisted as `ATTEMPT_UNCERTAIN`.

That is incorrect write semantics:
- no destructive delete request has yet been issued;
- we know this approved operation did not perform the delete;
- it must not be represented as an ambiguous post-write outcome.

### Required correction

Split delete preflight from destructive write classification.

Preflight phase:
- provider-reference validation;
- exact message lookup;
- exact peer/message verification;
- no destructive call yet.

Any failure during preflight must:
- result in zero delete calls;
- finish as a pre-write/definite failure under the existing attempt state model;
- use sanitized wording such as verification unavailable/failed;
- require a new approved plan for any later retry;
- never become `ATTEMPT_UNCERTAIN`.

Only once destructive `delete_message` has started may timeout/server/network ambiguity become `ATTEMPT_UNCERTAIN`.

### Tests

Add:
- fetch/preflight timeout -> `failed_definite`, zero delete calls;
- fetch/preflight ServerError -> `failed_definite`, zero delete calls;
- exact preflight success + delete timeout -> `uncertain`, one delete attempt;
- replay of each state makes zero additional provider calls.

## Mandatory regression coverage still missing from C1BR focused tests

The C1BR task explicitly required these but they are not present in the published focused test file.

Add them now.

### Edit A3 convergence

Test the actual A3 normalization/materialization path:
1. C1B/C1BR edit succeeds;
2. same provider message is later imported as an edited A3 `TelegramMtprotoHistoryEntry`;
3. same object/external_id remains;
4. body/title/edited_at converge;
5. no duplicate object is created;
6. direction remains outbound.

### Delete passive-sync non-resurrection

Test:
1. confirmed C1B delete tombstones the object;
2. same provider message appears in a later passive A3 history page;
3. materializer with normal passive `skip_hidden` semantics does not clear tombstone/resurrect active visibility;
4. DB row remains retained.

### Real provider rejection through attempt state

Existing C1BR tests prove representative Telethon errors map to
`TelegramMtprotoWriteDefiniteError` at transport level and custom definite errors map to
`failed_definite` at service level.

Add at least one end-to-end focused test that injects a representative real Telethon deterministic rejection through the real transport boundary and proves the resulting
`ExternalActionAttempt.state == failed_definite`.

## Preserve accepted C1BR design

Do NOT redesign:
- tool registry;
- approval/pending-action architecture;
- frozen schemas;
- C1AR route integrity;
- exact-message delete preflight concept;
- durable SUCCEEDED convergence metadata;
- replay no-resend behavior;
- mark-read changed=true / replay changed=false semantics;
- error taxonomy already corrected for post-write mutation paths.

No migration.
No UI.
No realtime.
No production.

## Branch / deliverable

Continue:
`review/telegram-mtproto-c1b-mutations`

Start from exact:
`C1BR_BASE_SHA=a7c36d8d7053ad62371207773a7aa142a9fe3407`

Create exactly one corrective commit. Do not rewrite/squash C1B/C1BR.

Run:
- focused C1B/C1BR/C1BR2;
- C1A/C1AR;
- Telegram A1-A4.4/Q1;
- MTProto history;
- tool/action-plan/execution gateway;
- relevant external-action suites;
- Ruff changed Python files;
- `git diff --check`;
- Alembic head `0046`.

Return:
- `C1BR_BASE_SHA=a7c36d8d7053ad62371207773a7aa142a9fe3407`
- `C1BR2_SHA=<exact sha>`
- changed files
- edit semantic enqueue rule
- delete preflight failure classification rule
- A3 edit convergence proof
- tombstone non-resurrection proof
- focused/regression test results
- Ruff
- git diff --check
- Alembic head `0046`
- production untouched

Final marker:
`TELEGRAM_MTPROTO_C1BR2_MUTATIONS_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
