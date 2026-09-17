# Current task — Telegram Depth A4.1 folder configuration and eligibility resolver

## Status

Telegram Depth A4.1 — ACTIVE / IMPLEMENTATION AUTHORIZED.

The A4 integration baseline is accepted at `4f1a9012145faa66baf499ad4fc9c08b759e9a5f` on `review/telegram-depth-a4-folder-scope`. Exact accepted A3 SHA `4777c32deb055f5024f3dbced125b4dd6db97e85` is preserved in its ancestry.

This task implements folder configuration and a read-only dynamic Telegram sync-scope resolver. It MUST NOT start A3 history import, background scheduling, production deployment, or destructive data cleanup.

## Fixed branch and baseline

- Repository: `d-yacenko/secretary-prerelease`
- Work only in existing review worktree/branch: `review/telegram-depth-a4-folder-scope`
- Required starting remote branch HEAD: `4f1a9012145faa66baf499ad4fc9c08b759e9a5f` plus any Architect bookkeeping commits already pushed to that same review branch.
- Before implementation: fetch `origin`, verify the review worktree is clean, and fast-forward only to `origin/review/telegram-depth-a4-folder-scope`. Do not rebase or rewrite A3 history.
- Main and production are not implementation targets for this task.

## Canonical product rule

A Telegram dialog is eligible only when:

`eligible(dialog) = dialog belongs to at least one configured Telegram folder AND dialog is currently NOT muted`

Additional invariants:

- initial desired folder names such as `Работа` and `Личная` are user configuration, NOT backend constants;
- persist stable Telegram folder/filter IDs plus last-known display names;
- folder name resolution is exact after trimming surrounding whitespace; no fuzzy guessing;
- missing or ambiguous configured folder names fail closed and MUST NOT replace existing valid configuration;
- an explicit empty configured-folder list is allowed and means Telegram sync scope is disabled/empty;
- private one-to-one dialogs, groups, and supergroups are supported candidates;
- broadcast channels, bots, and other unsupported peer kinds are skipped safely and surfaced only through sanitized counts/status;
- leaving all configured folders or becoming muted will later remove a dialog from active future sync scope, but this task does not delete already imported history.

## Authorized implementation

### 1. MTProto transport: folders and folder-scoped dialogs

Add bounded, read-only transport operations that:

- discover Telegram dialog folders/filters and return stable provider folder ID + display name;
- enumerate current dialogs for a specific provider folder ID, letting Telegram/provider folder semantics determine membership rather than reimplementing folder include/exclude rules in application code;
- return supported dialog descriptors for private user, group, and supergroup peers;
- include current effective muted state for each supported descriptor;
- preserve enough provider peer reference data for a later history-sync phase, including private-user references where applicable;
- bound enumeration and report truncation rather than silently claiming completeness;
- map provider/auth/flood-wait failures through existing sanitized Telegram error patterns; do not expose session material, access hashes, raw provider exceptions, or credentials in API responses/log assertions.

Do not call `fetch_history` from the new folder/scope resolver.

### 2. Durable configured folders

Add the next Alembic migration after `0044` (expected `0045`) for durable Telegram sync-folder configuration.

Persist per MTProto account at minimum:

- stable Telegram folder/filter ID;
- last-known display name;
- uniqueness of `(account_id, folder_id)`;
- normal created/updated timestamps consistent with repository conventions.

Do not hard-code `Работа`, `Личная`, or any other folder names in the schema/service constants.

The current product policy is `ignore_muted = true`. API models may expose that field, but `false` is not authorized in this phase; reject it rather than changing the eligibility rule.

### 3. Configuration service/API

Provide backend endpoints/service behavior for:

- listing available Telegram folders for the connected account;
- reading current persisted sync-folder configuration;
- replacing configured folders from a caller-supplied list of folder names.

For configuration replacement:

- trim surrounding whitespace;
- reject blank/duplicate requested names;
- resolve every non-empty requested name against live provider folders;
- each requested name must resolve to exactly one folder;
- if any requested name is missing or ambiguous, fail closed and leave the previously persisted configuration unchanged;
- on success, atomically persist the resolved stable IDs and current display names;
- explicit empty list atomically clears configured folders and disables scope.

Keep responses sanitized and user-scoped.

### 4. Read-only dynamic eligibility resolver

Implement a service/API read path that evaluates current scope from persisted stable folder IDs:

- re-read current provider folders;
- if any persisted folder ID no longer exists, fail closed with a sanitized configuration/status error; do not silently ingest from the remaining subset;
- if a persisted folder was renamed but its stable ID still exists, treat it as the same folder and refresh/present the current display name safely;
- enumerate each configured folder, union dialogs by stable peer ID, and de-duplicate dialogs appearing in multiple configured folders;
- exclude every currently muted dialog regardless of the Telegram folder's own muted/include rules;
- include private users, groups, and supergroups as supported eligible kinds;
- skip unsupported peer kinds and surface only sanitized counts/status;
- if no folders are configured, return an empty eligible scope without scanning all Telegram dialogs;
- expose bounded/truncated status so callers do not mistake a partial provider scan for a complete one.

This resolver is preview/read-only with respect to Telegram history state.

### 5. Preserve A3 transition boundary

For this task, DO NOT:

- enqueue or run history imports;
- call A3 history sync automatically;
- schedule Telegram recurring jobs;
- materialize the dynamic scope into `telegram_mtproto_chat_selections` or delete existing selection/history rows;
- remove or redesign the existing A2/A3 manual group endpoints yet;
- purge previously imported objects/messages;
- build Flutter/UI changes;
- touch production deployment, SSH, Compose, credentials, or provider-side mutations.

A4.2 will separately decide how the accepted dynamic scope is materialized and connected to the A3 bounded history engine.

## Required tests

Add focused A4 tests (prefer a dedicated `backend/tests/test_telegram_mtproto_a4.py`) covering at minimum:

- migration chain has a single `0045` head;
- stable folder IDs + last-known names persist correctly;
- exact trimmed name resolution succeeds;
- missing name fails closed without modifying prior config;
- ambiguous duplicate provider names fail closed without modifying prior config;
- explicit empty folder list disables scope;
- folder rename with same stable ID remains valid;
- union of multiple folders de-duplicates the same peer;
- private user, group, and supergroup descriptors are eligible when in configured scope and unmuted;
- muted dialog is excluded even when Telegram reports it in the configured folder;
- unsupported broadcast/bot/other kinds are skipped safely and counted/statused without accidental ingestion;
- missing persisted provider folder ID fails closed;
- no configured folders yields empty scope and does not fall back to all dialogs;
- scope preview does not call history fetch/materialization/queue paths;
- auth/provider/FloodWait failures remain sanitized and existing retry-after semantics are preserved where applicable.

Run at minimum from `backend`:

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py`

and:

`alembic heads`

Also run any additional focused tests required by files you modify.

## Completion and push

- Commit the implementation on `review/telegram-depth-a4-folder-scope`.
- Push that branch.
- Do not merge to `main`.

Return exactly:

- starting branch HEAD after Architect bookkeeping fast-forward;
- implementation commit SHA(s);
- final pushed branch HEAD;
- changed files;
- migration head;
- exact test commands and pass/fail counts;
- concise explanation of folder-name -> stable-ID persistence and fail-closed behavior;
- concise explanation of how current mute status is determined;
- confirmation that private/group/supergroup are supported and unsupported peer kinds are skipped;
- confirmation that no history fetch/materialization/queue/scheduler path is invoked by A4.1;
- `git status --short` for the review worktree;
- final marker exactly: `TELEGRAM_A4_1_SCOPE_READY`.

Then STOP. Do not begin A4.2.

## Production boundary

No production deployment, migration application, rollback, SSH, Compose, runtime probing, credential change, or provider-side mutation is authorized.
