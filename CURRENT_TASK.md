# Current task — Telegram Depth A4.2R scoped-history correction + acceptance completion

## Status

Telegram Depth A4.1 — ACCEPTED through `43944ca47b407889f87eb891b898a1c55097f7f0`.

Telegram Depth A4.2 implementation `e4202d1171f9a6552d2b276093cd39d6692d6e05` — REVIEWED / CHANGES REQUIRED / NOT ACCEPTED.

The A4.2 architectural direction remains valid: durable `manual_selected` + `scope_active`, migration `0046`, dynamic-scope reconciliation, and shared A3 history engine are retained. This correction is limited to a scoped-history error-mapping defect, missing acceptance coverage, and completing the required DB-backed test run.

Do NOT begin the next Telegram phase.

## Fixed branch and baseline

- Repository: `d-yacenko/secretary-prerelease`
- Work only in existing branch/worktree `review/telegram-depth-a4-folder-scope`.
- Start by `git fetch origin`, verify a clean worktree, and fast-forward only to current `origin/review/telegram-depth-a4-folder-scope`, including Architect bookkeeping commits.
- Keep exact A3 SHA `4777c32deb055f5024f3dbced125b4dd6db97e85` in ancestry.
- Do not rebase or rewrite accepted/prior implementation commits.
- Alembic head remains `0046`; no new migration is expected unless a real migration defect is discovered by the required tests.

## Review findings that must be corrected

### 1. Scoped per-peer API misses a history-provider unavailable-peer error

`TelethonMtprotoTransport.fetch_history()` maps `ChannelInvalidError`, `ChannelPrivateError`, `ChatIdInvalidError`, and `PeerIdInvalidError` to `TelegramMtprotoGroupUnavailableError`.

The new endpoint:

`POST /telegram/mtproto/sync-scope/peers/{peer_id}/sync`

currently does not catch `TelegramMtprotoGroupUnavailableError`. That can escape as an internal 500 instead of a sanitized client-visible unavailable-peer response.

Correction:

- handle `TelegramMtprotoGroupUnavailableError` in the scoped endpoint;
- map it to a sanitized `409 CONFLICT` with generic peer wording such as `Telegram peer is no longer available`;
- do not expose provider/raw exception text;
- preserve legacy A3 group endpoint behavior unless a focused compatibility test proves an existing issue.

If a more generic peer-unavailable domain error is introduced, keep the change minimal and preserve A3 compatibility.

### 2. A4.2 acceptance coverage is materially incomplete

`backend/tests/test_telegram_mtproto_a4_2.py` currently contains only four focused tests. The original A4.2 task required substantially broader regression coverage. Add explicit tests for all missing behaviors below.

## Required acceptance tests

Use `backend/tests/test_telegram_mtproto_a4_2.py` plus narrowly targeted A2/A3/API tests where appropriate. Do not delete or weaken existing coverage.

At minimum prove:

1. **Migration/model contract**
   - Alembic single head is `0046`;
   - peer-kind check allows exactly `private`, `group`, `supergroup`;
   - existing legacy rows are backfilled/represented as `manual_selected = true`, `scope_active = false` under `0046` semantics;
   - cursor columns remain untouched by the migration semantics.

2. **Scope-row creation**
   - folder-scope reconciliation can create private, basic-group and supergroup rows;
   - new folder-created rows are `manual_selected = false`, `scope_active = true`;
   - provider reference is stored encrypted, not plaintext;
   - unsupported/bot/broadcast peers never create durable scope rows.

3. **Deactivate/re-entry durability**
   - peer leaving configured scope becomes `scope_active = false` without row deletion;
   - muted peer becomes inactive on a complete reconciliation;
   - encrypted provider reference and all A3 cursor fields survive deactivation;
   - re-entry reactivates the same durable row and preserves existing cursors;
   - a row that is both manually selected and scope-active retains `manual_selected = true` when it leaves dynamic scope.

4. **Legacy manual compatibility**
   - legacy manual deselect makes the peer disappear from `list_selections()` but retains the durable row/cursors;
   - reselect restores `manual_selected = true` without resetting `scope_active` or history cursors;
   - legacy A3 `sync_group()` rejects a row whose `manual_selected` is false, even if the row exists or is `scope_active`.

5. **Fail-closed reconciliation**
   - explicit complete empty configured scope deactivates every previously scope-active row without deleting rows/cursors;
   - truncated folder discovery fails before durable reconciliation and leaves the previous active set unchanged;
   - truncated dialog-universe result fails before durable reconciliation and leaves the previous active set unchanged;
   - missing configured folder ID fails closed and leaves active flags unchanged;
   - reconciliation itself never calls `fetch_history`.

6. **Scoped history gate**
   - inactive/not-in-scope peer is rejected before any provider `fetch_history` call;
   - zero peer ID is rejected at API boundary;
   - positive private marked ID and negative group/supergroup marked IDs are accepted by path validation within signed 64-bit bounds;
   - exactly one requested peer is synced; no bulk active-peer loop is introduced.

7. **Private history through real A3 transport contract**
   - private dialog provider reference generated by A4.1 (`{"entity_type":"user","id":...,"access_hash":...}`) is accepted by `_input_peer_from_reference` / `fetch_history` and becomes `InputPeerUser`;
   - `sync_scope_peer()` for an active private row uses the same bounded A3 history path, materializer and cursor fields;
   - generic metadata contains `peer_id`, `peer_kind`, `peer_title`, `peer_username`;
   - existing group metadata/external-ID compatibility remains intact;
   - repeated scoped sync remains idempotent under the existing external ID scheme.

8. **Group/supergroup compatibility**
   - active group/supergroup scoped sync still uses the shared A3 engine and cursor progression;
   - legacy `sync_group()` behavior stays compatible for manually selected groups.

9. **Error mapping / sanitization**
   - scoped endpoint maps `TelegramMtprotoGroupUnavailableError` to sanitized `409` peer-unavailable response;
   - provider-reference-invalid remains sanitized;
   - auth-invalid remains sanitized;
   - provider-unavailable/FloodWait mapping remains unchanged and no raw provider text leaks.

10. **Boundary checks**
   - no scheduler/recurring job integration;
   - no sync-all loop;
   - no assistant/retrieval filtering work;
   - no UI or production work;
   - scope reconciliation itself does not materialize Telegram message history.

## Required PostgreSQL-backed verification

The prior report could not run the required suite because PostgreSQL on `localhost:5432` was unavailable. The repository already contains a local-dev overlay specifically for host pytest: `infra/compose.dev.yaml` publishes PostgreSQL on `5432`.

Use only the local development environment, never production.

From repository root, use the repo-standard local DB setup:

`docker compose -f infra/compose.yaml -f infra/compose.dev.yaml up -d db`

Wait for the local `db` service to become healthy. Then from `backend` run:

`alembic upgrade head`

and the required suite:

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py`

The A4.2 correction is NOT acceptance-ready if this DB-backed suite cannot be executed successfully. If Docker/local DB cannot be started, STOP and report the exact infrastructure error rather than claiming readiness.

Also run:

`alembic heads`

`ruff check` over every Python file changed by A4.2/A4.2R that is relevant to this correction, at minimum:

`ruff check app/api/telegram_mtproto.py app/connectors/telegram/mtproto_account_store.py app/connectors/telegram/mtproto_errors.py app/connectors/telegram/mtproto_transport.py app/db/models.py app/services/telegram_mtproto_history_service.py app/services/telegram_mtproto_scope_service.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py`

and:

`git diff --check`

You may stop/remove the local development DB after verification if desired. Do not use production SSH/Compose or production environment files.

## Preserve accepted A4.2 implementation unless tests expose a defect

Keep the existing `0046` schema, durable flags, reconciliation approach, shared `_sync_selection()` path, generic peer metadata, and explicit reconcile/per-peer API shape unless a required regression test demonstrates a defect.

Do not redesign the phase or add unrelated abstractions.

## Completion report

Commit and push only to `review/telegram-depth-a4-folder-scope`. Do not merge to `main`.

Return:

- starting branch HEAD after Architect bookkeeping fast-forward;
- A4.2R correction commit SHA(s);
- final pushed branch HEAD;
- changed files;
- confirmation Alembic remains `0046`;
- exact local PostgreSQL startup command/result;
- exact `alembic upgrade head` result;
- exact pytest command and pass/fail count;
- exact ruff command/result;
- `git diff --check` result;
- explicit list of newly added A4.2 acceptance cases;
- explanation of scoped `TelegramMtprotoGroupUnavailableError` mapping;
- confirmation private history is tested with a real user provider reference and shared A3 engine;
- confirmation deactivation/re-entry and manual deselect preserve cursor rows;
- confirmation no scheduler/bulk/retrieval/UI/production work was started;
- `git status --short` for review worktree;
- final marker exactly: `TELEGRAM_A4_2_CORRECTION_READY`.

Then STOP. Do not begin the next Telegram phase.

## Production boundary

No production deployment, production migration application, rollback, SSH, production Compose, runtime probing, credential changes, or provider-side mutation is authorized.
