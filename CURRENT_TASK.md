# Current task — Telegram MTProto C3A: Flutter account connection and sync-scope UX

## Status

Telegram MTProto C2B/C2BR/C2BR2 deterministic notification/event surface is **ACCEPTED and integrated to main**.

Accepted implementation tip:
`2653de562f72ddb0b81063fb816a02b330022a4b`

Integration merge:
`0cdcbaa0498f8e4c1ef3033c5c7d544bb8590319`

C3 is split. This task authorizes only **C3A — client account/auth/sync-scope UX**.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- production Alembic `0041`;
- repository Alembic head must remain `0046`;
- M3 NOT authorized;
- Bot API retirement NOT authorized.

Canonical AI flag remains:
`TELEGRAM_MTPROTO_AI_ENABLED=false` by default.

## Goal

Expose the already-existing Telegram MTProto account and scope-management backend capabilities in the Flutter client without changing backend semantics.

Use the existing backend contract in `backend/app/api/telegram_mtproto.py`. Do not create replacement endpoints.

## Required client API/model support

Add typed client models and `SecretaryApiClient` methods for the existing endpoints needed by this UX:

Auth/status:
- `GET /telegram/mtproto/status`
- `POST /telegram/mtproto/auth/start`
- `POST /telegram/mtproto/auth/code`
- `POST /telegram/mtproto/auth/password`

Scope/folders:
- `GET /telegram/mtproto/folders`
- `GET /telegram/mtproto/sync-folders`
- `PUT /telegram/mtproto/sync-folders`
- `GET /telegram/mtproto/sync-scope/preview`
- `POST /telegram/mtproto/sync-scope/reconcile`
- `POST /telegram/mtproto/sync-scope/peers/{peer_id}/sync`

Manual groups:
- `GET /telegram/mtproto/groups`
- `PATCH /telegram/mtproto/groups/{peer_id}`
- `POST /telegram/mtproto/groups/{peer_id}/sync`

Preserve backend field names and meaning exactly.

Do not expose or persist Telegram session strings, provider references, access hashes, API hash, credentials, or passwords beyond the transient form submission needed for the existing auth endpoint.

## Account screen UX

Integrate MTProto into the existing account/settings experience, following current client patterns rather than building a separate navigation system.

Required states:
1. MTProto backend not configured;
2. configured but not connected;
3. auth code challenge active;
4. 2FA password required;
5. connected account;
6. provider temporarily unavailable/error;
7. authorization invalid/reconnect-required style state where applicable.

### Login flow

When not connected:
- phone input;
- start auth;
- code input;
- if backend returns `password_required`, show password input;
- on authorization success refresh MTProto status and connected account display;
- never log password/code/session values;
- prevent duplicate submits while request is in flight;
- show backend-safe error detail using existing client error patterns.

Display connected identity using backend `display_name`, username, and Telegram user id where available.

Do not add disconnect/delete semantics unless an existing authorized backend endpoint already exists. C3A must not invent destructive account removal.

## Sync-folder UX

For a connected account:
- load available Telegram folders;
- load currently configured sync folders;
- allow selecting zero or more folder names;
- allow configuring `ignore_muted`;
- save through existing `PUT /telegram/mtproto/sync-folders`;
- preview resulting active scope via existing preview endpoint;
- reconcile scope explicitly after save or through a clearly labelled user action;
- surface preview counts/truncation/skipped counts without exposing provider references.

Zero selected folders is a valid backend-supported state; do not silently substitute defaults.

## Manual group UX

For connected account:
- list groups from existing groups endpoint;
- show title/username/kind/forum/available/selected;
- allow manual selected toggle through existing PATCH endpoint;
- unavailable groups must not look actionable;
- allow explicit manual sync of a selected group;
- show bounded sync result summary (scanned/materialized/created/updated/unchanged/skipped/history_complete).

Do not add infinite scrolling/provider-specific references unless required by the existing contract.

## Scope peer sync

For dialogs returned by sync-scope preview/reconcile:
- allow explicit per-peer sync using the existing scope peer sync endpoint;
- support private/group/supergroup peer kinds returned by the backend;
- show sync result summary consistently with manual group sync.

## Source preference interaction

Do not duplicate generic source preference settings already present in the account UI.
If Telegram MTProto already appears through the generic source preference list, preserve that behavior and keep C3A controls focused on MTProto authorization and scope selection.

## UX / safety invariants

- no secrets in UI state serialization, logs, snackbars, debug prints, test golden text, or analytics;
- password field obscured;
- auth code/password cleared after successful authorization and when abandoning/restarting challenge;
- stale challenge state must not survive app restart unless the current client already has an explicit secure pattern for that exact kind of sensitive ephemeral state;
- no WebSocket/SSE/realtime listener;
- no client-side Telegram SDK;
- no direct Telegram network calls from Flutter;
- no background daemon;
- no backend semantic changes merely to simplify UI.

## Testing

Add focused Flutter tests covering at minimum:
- MTProto status parsing: not configured / disconnected / connected;
- auth start -> code authorized;
- auth start -> code password_required -> password authorized;
- duplicate-submit protection;
- sensitive code/password is not rendered after success;
- folder load/current-selection/save;
- zero-folder selection remains zero;
- ignore-muted round trip;
- scope preview rendering including truncated/skipped counts;
- scope reconcile action;
- group selected toggle;
- unavailable group not actionable;
- group sync summary;
- scope peer sync summary;
- API error presentation for 400/409/410/503 paths using existing client error conventions.

Also run relevant existing account/API/inbox Flutter tests.

Required checks:
- `dart format --output=none --set-exit-if-changed` on changed Dart files;
- `flutter analyze`;
- focused Flutter tests;
- relevant existing client regression tests;
- backend tests only if backend files are changed (backend changes are not expected);
- `git diff --check`;
- repository Alembic head remains `0046`.

## Explicitly out of scope

Do NOT implement:
- C3B Telegram-specific inbox/notification presentation;
- OS-level desktop/mobile notifications;
- websocket/SSE/realtime Telethon listener;
- backend auth/scope redesign;
- new backend endpoint unless a hard blocker is proven and reported before implementation;
- migration `0047`;
- production deploy/ref move;
- production DB/env mutation;
- Bot API retirement.

## Branch / deliverable

Create branch:
`review/telegram-mtproto-c3a-client-account`

Start from exact:
`C3A_BASE_SHA=0cdcbaa0498f8e4c1ef3033c5c7d544bb8590319`

If `main` has moved only because Architect updated `CURRENT_TASK.md`, `PROJECT_STATE.md`, or encrypted recovery context after this authorization, do NOT rebase merely for those documentation commits. The reviewed code base remains the exact SHA above unless Architect explicitly changes it.

Return:
- `C3A_BASE_SHA`;
- `C3A_SHA`;
- changed files;
- API/model additions;
- implemented UX states;
- focused test list/results;
- existing client regression results;
- `flutter analyze`;
- Dart format check;
- `git diff --check`;
- Alembic head `0046`;
- clean worktree;
- remote branch SHA;
- production untouched.

Final marker:
`TELEGRAM_MTPROTO_C3A_CLIENT_ACCOUNT_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
