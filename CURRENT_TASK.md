# Current task — Telegram Depth A4.1T acceptance-test hardening

## Status

Telegram Depth A4.1R provider correction at `0a987bc02a16eaea5aadc859ad631510579b0743` — CODE REVIEW PASSED FOR PROVIDER SEMANTICS / ACCEPTANCE PENDING REQUIRED TEST COVERAGE.

The reviewed correction fixes the blocking implementation issue: custom `DialogFilter` IDs are no longer passed to `iter_dialogs(folder=...)`; current `messages.DialogFilters.filters` is consumed; one bounded all-dialog universe is scanned; custom filter membership is evaluated from Telegram definitions; mute/read/archive facts are derived from raw live dialog fields.

Do NOT begin A4.2. This task is intentionally test-first/test-only unless one of the missing acceptance tests exposes a real defect.

## Fixed branch

- Repository: `d-yacenko/secretary-prerelease`
- Work only in existing review worktree/branch: `review/telegram-depth-a4-folder-scope`.
- Fetch and fast-forward only to current `origin/review/telegram-depth-a4-folder-scope`, including Architect bookkeeping commits.
- Keep exact A3 SHA `4777c32deb055f5024f3dbced125b4dd6db97e85` in ancestry.
- Do not rebase or rewrite prior commits.
- Alembic head must remain `0045`; no migration change is authorized.

## Why this task exists

The A4.1R implementation is materially correct, but `backend/tests/test_telegram_mtproto_a4.py` does not yet explicitly cover several acceptance cases that were mandatory in A4.1R. These gaps must be closed before the phase is accepted because they protect the exact provider semantics that previously caused a blocking defect.

## Authorized work

Primarily modify `backend/tests/test_telegram_mtproto_a4.py` to add focused regression tests. Production-code changes are NOT authorized unless a newly added required test exposes a genuine defect in the current A4.1R implementation; if that happens, make only the smallest correction needed and report it explicitly.

Add explicit tests for all of the following:

1. `non_contacts` category:
   - non-contact, non-bot private user matches;
   - contact does not match `non_contacts` solely by that flag.

2. `pinned_peers` explicit membership:
   - pinned peer matches even when no category flag matches;
   - explicit `exclude_peers` still wins over pinned/include.

3. `DialogFilterChatlist` membership:
   - pinned/include peers match;
   - a non-explicit peer does not match;
   - no ordinary category or exclusion semantics are invented for chatlist filters.

4. `exclude_read`:
   - `unread_count == 0` and `unread_mark == False` is excluded;
   - `unread_count > 0` remains included;
   - `unread_mark == True` remains included even when count is zero.

5. `exclude_archived`:
   - archived dialog is excluded;
   - otherwise-equivalent non-archived dialog remains included.

6. Final Secretary mute override:
   - a currently muted peer that is explicitly included or pinned in a configured filter is still absent from `preview_scope` because final product eligibility is `filter_member AND not_muted`.

7. Real transport call shape:
   - exercise `TelethonMtprotoTransport.fetch_dialog_universe` with a fake/monkeypatched Telethon client and assert `iter_dialogs` is called without a custom `folder` argument;
   - use a custom filter ID greater than `1` in the surrounding setup so this test would catch regression to `iter_dialogs(folder=<custom filter id>)`.

8. Raw dialog classification at the transport boundary:
   - construct/imitate Telethon v1 raw/custom dialog shapes sufficiently to prove current `notify_settings.mute_until`, `unread_mark`, `folder_id`, contact/non-contact and supported peer classification are converted into the descriptor facts used by membership evaluation;
   - bot and broadcast examples are rejected from Secretary candidates and surfaced only through sanitized skip reasons/counts.

9. Provider error sanitization for the new A4.1 transport paths:
   - authorization-invalid remains sanitized;
   - generic provider failure remains sanitized;
   - FloodWait preserves the existing bounded retry-after behavior.

10. Read-only phase boundary:
   - add an explicit trap/assertion showing scope preview cannot invoke `fetch_history` on the supplied transport;
   - do not introduce materialization, queue, or scheduler dependencies into the scope service merely to test their absence. Code inspection plus absence of such dependencies remains the acceptance basis for those paths.

Preserve all existing A1/A2/A3/A4 tests. Do not weaken or delete current coverage to make the suite pass.

## Required checks

From `backend` run at minimum:

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py`

`alembic heads`

`ruff check app/connectors/telegram/mtproto_transport.py app/services/telegram_mtproto_scope_service.py tests/test_telegram_mtproto_a4.py`

If only the test file changes, ruff must still be run on the three files above so the accepted correction stays lint-clean.

## Completion report

Commit and push only to `review/telegram-depth-a4-folder-scope`. Do not merge to `main`.

Return:

- starting branch HEAD after Architect bookkeeping fast-forward;
- test-hardening commit SHA(s);
- final pushed branch HEAD;
- changed files;
- confirmation Alembic remains `0045`;
- exact test/lint commands and results;
- explicit list of the new regression cases added;
- whether any production-code defect was exposed; if yes, exact minimal fix;
- confirmation no A4.2/history/materialization/queue/scheduler work was started;
- `git status --short` for review worktree;
- final marker exactly: `TELEGRAM_A4_1_TESTS_READY`.

Then STOP. Do not begin A4.2.

## Production boundary

No production deployment, migration application, rollback, SSH, Compose, runtime probing, credential changes, or provider-side mutations are authorized.
