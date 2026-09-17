# Current task — Telegram Depth A4.2T final acceptance coverage

## Status

Telegram Depth A4.1 — ACCEPTED through `43944ca47b407889f87eb891b898a1c55097f7f0`.

Telegram Depth A4.2 implementation `e4202d1171f9a6552d2b276093cd39d6692d6e05` plus A4.2R correction `28ca11160ce2b0ffcca651bfc2058b9344c379b1` — CODE REVIEW PASSED FOR THE KNOWN 409 DEFECT / ACCEPTANCE STILL PENDING REQUIRED COVERAGE.

A4.2R correctly adds sanitized handling for `TelegramMtprotoGroupUnavailableError`, successfully runs the PostgreSQL-backed suite, and keeps Alembic at `0046`. However the dedicated A4.2 coverage still contains only seven tests total, and several mandatory behaviors from the A4.2/A4.2R contracts remain unproved.

Do NOT begin the next Telegram phase.

## Fixed branch and baseline

- Repository: `d-yacenko/secretary-prerelease`
- Work only in `review/telegram-depth-a4-folder-scope`.
- Fetch and fast-forward only to current `origin/review/telegram-depth-a4-folder-scope`, including Architect bookkeeping commits.
- Keep A3 SHA `4777c32deb055f5024f3dbced125b4dd6db97e85` in ancestry.
- Do not rebase or rewrite prior commits.
- Alembic head remains `0046`.
- Production code is FROZEN for this task unless a required new test exposes a real defect. If so, make only the smallest correction and report it explicitly.

## Why acceptance is still pending

The required suite now reports `90 passed`, which is consistent with the prior accepted A1/A2/A3/A4 suite plus only seven A4.2 tests. Existing A3 tests prove the legacy `sync_group()` engine, but they do not prove that the new `sync_scope_peer()` gate and private/group/supergroup scoped paths actually reuse that engine correctly.

The following scenarios must be explicit regressions, not inferred from code inspection.

## Required new tests

Add focused DB-backed tests, primarily in `backend/tests/test_telegram_mtproto_a4_2.py`, with narrow A2/A3/API updates where that is the clearer home.

### 1. Durable scope-row creation

Prove in the database that one reconciliation containing a private peer, basic group, and supergroup creates three durable rows and for each row:

- `manual_selected is False`;
- `scope_active is True`;
- `peer_kind` is correct;
- provider reference is encrypted rather than stored as the supplied plaintext reference.

Also prove an unsupported descriptor kind passed defensively to the store does not create a row.

### 2. Full cursor preservation across deactivate/re-entry

The current test only checks `history_latest_message_id` and `history_complete`. Add coverage that deactivation and later re-entry preserve ALL A3 history state on the same row ID:

- `history_latest_message_id`;
- `history_backfill_before_message_id`;
- `history_cutoff_at`;
- `history_complete`;
- `history_last_synced_at`.

Also prove `manual_selected=True` survives scope deactivation.

### 3. Manual deselect/reselect durability

With a real DB row that already has `scope_active=True` and non-empty history cursors:

- legacy deselect makes `manual_selected=False`;
- row remains in DB;
- `list_selections()` no longer returns it;
- `scope_active` and every cursor field remain unchanged;
- legacy reselect sets `manual_selected=True` again without resetting `scope_active` or cursor state.

### 4. Legacy A3 manual gate on retained rows

Create a retained row with `manual_selected=False` (optionally `scope_active=True`) and assert:

- `TelegramMtprotoHistoryService.sync_group()` raises `TelegramMtprotoGroupNotSelectedError`;
- the fake history transport receives zero calls.

This must prove the new retained-row behavior, not only the old “row absent” case.

### 5. Complete empty scope reconciliation

Using `TelegramMtprotoScopeService.reconcile_scope()` with zero configured folders and at least one pre-existing `scope_active=True` DB row, prove:

- reconciliation is complete, not treated as truncation;
- all scope-active rows become inactive;
- rows and cursors remain present;
- no history fetch occurs.

### 6. Both truncation sources + missing folder fail closed

Add separate tests for:

- `discover_folders(...).truncated=True`;
- `fetch_dialog_universe(...).truncated=True`;
- configured stable folder ID missing from current discovery.

For each, seed a real `scope_active=True` row and prove its active flag and cursor state are unchanged after the failure. It is insufficient only to assert that a fake store reconciliation callback was not invoked.

### 7. Muted peer causes durable deactivation

Seed an active peer that is still a member of a configured Telegram filter but appears currently muted in the live dialog universe. Run real scope reconciliation and prove the durable row becomes `scope_active=False` without deletion/cursor loss.

### 8. Scoped inactive gate before provider history

Create an existing row with `scope_active=False` and call `sync_scope_peer()`.

Assert:

- `TelegramMtprotoPeerNotInActiveScopeError`;
- fake history transport receives zero calls.

### 9. Private scoped history uses the shared A3 engine

Create an active `private` durable row with a real A4.1-style encrypted provider reference:

`{"entity_type":"user","id":42,"access_hash":99}`

Call `sync_scope_peer()` with a fake history transport returning at least one message.

Prove:

- provider call uses the decrypted user reference;
- bounded A3 page limit is used;
- message is materialized through the existing Telegram materializer;
- cursor fields advance on the same durable row;
- object metadata contains `peer_id`, `peer_kind=private`, `peer_title`, `peer_username`;
- external ID remains the existing `mtproto|<account>|<peer>|<message>` scheme.

Then sync the same logical message again and prove idempotency (no duplicate Object; unchanged/no extra job behavior consistent with existing A3 semantics).

A parser-only `_input_peer_from_reference()` test is NOT sufficient for this requirement.

### 10. Scoped group/supergroup reuse the same engine

Add at least one scoped group or supergroup test showing `sync_scope_peer()` advances the same A3 cursor fields via the shared engine. Existing legacy `sync_group()` tests alone are not sufficient.

### 11. Scoped API peer-ID boundary

Through the FastAPI test client, prove for the new scoped endpoint:

- `0` => sanitized `422` without calling history service;
- a valid positive private peer ID reaches `sync_scope_peer()`;
- a valid negative group/supergroup marked ID reaches `sync_scope_peer()`;
- values outside signed 64-bit bounds => sanitized `422` without calling service.

### 12. Scoped API/domain error mappings

In addition to the already added unavailable-peer 409 test, explicitly verify the scoped endpoint maps:

- `TelegramMtprotoProviderReferenceInvalidError` => sanitized `409` generic peer unavailable;
- `TelegramMtprotoAuthorizationInvalidError` => controlled `409`;
- `TelegramMtprotoProviderUnavailableError` (including retry-after behavior where existing helper applies) => existing sanitized provider response.

No provider/raw exception text may leak.

## Existing coverage that may be reused

Do NOT duplicate already strong A3 tests for generic page bounds, cutoff/backfill mechanics, materializer rollback, or legacy `sync_group()` idempotency. The missing requirement is to connect the NEW scoped gate/path to those shared internals.

Likewise keep the existing A4.1 provider-filter tests unchanged.

## Required verification

Use the repository local development PostgreSQL only:

`docker compose -f infra/compose.yaml -f infra/compose.dev.yaml up -d db`

Wait for healthy.

From `backend`:

`alembic upgrade head`

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py`

`alembic heads`

`ruff check app/api/telegram_mtproto.py app/connectors/telegram/mtproto_account_store.py app/connectors/telegram/mtproto_errors.py app/connectors/telegram/mtproto_transport.py app/db/models.py app/services/telegram_mtproto_history_service.py app/services/telegram_mtproto_scope_service.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py`

`git diff --check`

If a new regression test exposes a product-code defect, apply only the minimal same-phase correction, rerun the full command set, and report it.

## Completion report

Commit and push only to `review/telegram-depth-a4-folder-scope`. Do not merge to `main`.

Return:

- starting branch HEAD after Architect bookkeeping fast-forward;
- A4.2T commit SHA(s);
- final pushed branch HEAD;
- changed files;
- Alembic head;
- exact DB startup/alembic/pytest/ruff/diff-check results;
- explicit mapping from each numbered acceptance case above to test name(s);
- any production-code defect found and exact minimal fix, or state `none`;
- confirmation scoped private sync was exercised through `sync_scope_peer()` and materialization/cursors, not parser-only;
- confirmation no scheduler/bulk/retrieval/UI/production/next-phase work was started;
- `git status --short`;
- final marker exactly: `TELEGRAM_A4_2_FINAL_TESTS_READY`.

Then STOP.

## Production boundary

No production deployment, production migration, rollback, SSH, production Compose, runtime probing, credential changes, or provider-side mutation is authorized.
