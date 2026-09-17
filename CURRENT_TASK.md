# Current task — Telegram Depth A4.2U remaining acceptance gaps

## Status

Telegram Depth A4.1 — ACCEPTED through `43944ca47b407889f87eb891b898a1c55097f7f0`.

Telegram Depth A4.2 implementation `e4202d1171f9a6552d2b276093cd39d6692d6e05`, A4.2R correction `28ca11160ce2b0ffcca651bfc2058b9344c379b1`, and A4.2T test hardening `88207034c5dbd0921b4eab30a419042eda36d9f1` — CODE DIRECTION VALID / ACCEPTANCE STILL PENDING A SMALL SET OF EXPLICIT REGRESSIONS.

A4.2T is test-only and materially improves coverage: DB-backed private scoped sync, all cursor fields across re-entry, incomplete-scope preservation, muted deactivation, inactive scoped gate, complete-empty scope, and zero-ID boundary are now exercised. The required suite reports `98 passed`.

A4.2 is NOT yet accepted because several requirements from the A4.2T contract are still not represented by explicit tests in the pushed file.

Do NOT begin the next Telegram phase.

## Fixed branch and baseline

- Repository: `d-yacenko/secretary-prerelease`
- Work only in existing branch/worktree `review/telegram-depth-a4-folder-scope`.
- Fetch and fast-forward only to current `origin/review/telegram-depth-a4-folder-scope`, including Architect bookkeeping commits.
- Required implementation/test baseline includes `88207034c5dbd0921b4eab30a419042eda36d9f1` plus Architect bookkeeping.
- Keep exact A3 SHA `4777c32deb055f5024f3dbced125b4dd6db97e85` in ancestry.
- Do not rebase or rewrite prior commits.
- Alembic head remains `0046`.
- Production code is FROZEN unless one of the remaining tests exposes a real defect. If that happens, apply only the smallest same-phase fix and report it.

## Authorized work

Primarily modify only `backend/tests/test_telegram_mtproto_a4_2.py`. Narrow updates to A2/A3 tests are allowed only when they are the clearer location for the legacy-compatibility case.

Add explicit regression coverage for the remaining gaps below. Do not duplicate already-passing A3/A4 mechanics unnecessarily.

### 1. Durable rows for all supported peer kinds + encryption

One DB-backed test must reconcile three descriptors at once and inspect all three resulting rows:

- private peer;
- basic group;
- supergroup.

Assert for every row:

- `manual_selected is False`;
- `scope_active is True`;
- exact `peer_kind`;
- stored `provider_peer_reference_encrypted` is not the plaintext provider reference;
- decrypting it with the test credential key yields the original provider reference.

Use provider-shape-correct references:

- private -> `user` + `access_hash`;
- basic group -> `chat`;
- supergroup -> `channel` + `access_hash`.

The existing unsupported-kind test may remain as the defensive negative case.

### 2. Manual deselect/reselect preserves durable state

Seed a real row with:

- `manual_selected=True`;
- `scope_active=True`;
- non-empty values for all five A3 history state fields.

Exercise legacy deselect/reselect semantics and prove:

- deselect changes only `manual_selected` to false;
- row ID remains the same;
- `list_selections()` omits it while deselected;
- `scope_active` and all five cursor/history fields are unchanged;
- reselect restores `manual_selected=True` on the same row;
- `scope_active` and cursor/history fields still remain unchanged.

Prefer exercising the existing store/service path rather than mutating flags directly.

### 3. Legacy `sync_group()` gate on a retained row

Create a row that exists and has `scope_active=True` but `manual_selected=False`.

Call `TelegramMtprotoHistoryService.sync_group()` and assert:

- `TelegramMtprotoGroupNotSelectedError`;
- fake history transport receives zero calls.

This is distinct from the old A3 test where no selection row exists.

### 4. Missing configured folder ID fails closed with persisted state unchanged

Seed a real `scope_active=True` row with cursor/history state and a persisted configured folder ID that is absent from live discovery.

Run `TelegramMtprotoScopeService.reconcile_scope()` and assert:

- `TelegramMtprotoScopeUnavailableError`;
- row remains `scope_active=True`;
- row ID and all cursor/history state remain unchanged;
- no `fetch_history` call occurs.

The existing A4.2T truncation test already covers discovery-truncated and universe-truncated; do not duplicate those unless needed for test clarity.

### 5. Scoped group/supergroup uses the shared A3 history engine

Add at least one DB-backed `sync_scope_peer()` test for a group or supergroup. Supergroup is preferred because it exercises channel provider reference reconstruction.

Use a correct encrypted provider reference (`channel` + `access_hash` for supergroup), fake history transport, and assert:

- provider reference reaching history transport is the expected decrypted reference;
- shared bounded A3 page limit is used;
- message materializes through the existing Telegram materializer;
- the same durable row's A3 cursor advances;
- generic peer metadata remains correct;
- legacy group metadata fields remain present/compatible where currently emitted.

Do not create a separate history implementation.

### 6. Scoped API signed-ID routing boundaries

Through the FastAPI test client for:

`POST /telegram/mtproto/sync-scope/peers/{peer_id}/sync`

prove:

- `0` stays sanitized `422` with zero service calls (existing direct-function test may remain, but add actual HTTP boundary coverage if it does not already exist);
- a valid positive private peer ID reaches `sync_scope_peer()` with exactly that ID;
- a valid negative group/supergroup peer ID reaches `sync_scope_peer()` with exactly that ID;
- below `-(2**63)` and above `2**63-1` return sanitized `422` without calling the history service.

No raw invalid peer value should be echoed in a provider error detail.

### 7. Remaining scoped API error mappings

Using the scoped endpoint, explicitly test:

- `TelegramMtprotoProviderReferenceInvalidError` -> sanitized `409` with generic `Telegram peer is no longer available`;
- `TelegramMtprotoAuthorizationInvalidError` -> controlled `409` using the existing sanitized domain message;
- `TelegramMtprotoProviderUnavailableError` -> existing sanitized provider response;
- a provider-unavailable error carrying retry-after/FloodWait metadata preserves the existing bounded Retry-After behavior used by the shared helper.

The already-passing `TelegramMtprotoGroupUnavailableError -> 409` regression does not need duplication.

## Acceptance note

The following A4.2T requirements are already adequately covered and should not be rewritten just to increase test count:

- full five-field cursor preservation across scope deactivate/re-entry;
- unsupported descriptor does not persist;
- inactive scoped peer rejected before history;
- discovery/universe truncation fail closed against real persisted state;
- muted active peer deactivates without row deletion;
- private `sync_scope_peer()` materialization/cursors/metadata/external ID/idempotency;
- explicit complete empty scope deactivation;
- reconciliation does not fetch history;
- migration head `0046`;
- scoped unavailable-peer sanitized 409.

## Required verification

Use only local development PostgreSQL:

`docker compose -f infra/compose.yaml -f infra/compose.dev.yaml up -d db`

Wait for healthy.

From `backend`:

`alembic upgrade head`

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py`

`alembic heads`

`ruff check app/api/telegram_mtproto.py app/connectors/telegram/mtproto_account_store.py app/connectors/telegram/mtproto_errors.py app/connectors/telegram/mtproto_transport.py app/db/models.py app/services/telegram_mtproto_history_service.py app/services/telegram_mtproto_scope_service.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py`

`git diff --check`

If a new test exposes a production-code defect, apply only the minimal correction, then rerun all commands above.

## Completion report

Commit and push only to `review/telegram-depth-a4-folder-scope`. Do not merge to `main`.

Return:

- starting branch HEAD after Architect bookkeeping fast-forward;
- A4.2U commit SHA(s);
- final pushed branch HEAD;
- changed files;
- Alembic head;
- exact DB startup/alembic/pytest/ruff/diff-check results;
- mapping of cases 1–7 above to concrete test names;
- production-code defect found? If yes, exact minimal fix; otherwise `none`;
- confirmation no scheduler/bulk/retrieval/UI/production/next-phase work was started;
- `git status --short`;
- final marker exactly: `TELEGRAM_A4_2_REMAINING_TESTS_READY`.

Then STOP.

## Production boundary

No production deployment, production migration, rollback, SSH, production Compose, runtime probing, credential changes, or provider-side mutation is authorized.
