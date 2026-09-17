# Current task — Telegram Depth A4.1R provider-semantics correction

## Status

Telegram Depth A4.1 implementation `814f75c330e9876ca9ee7f2da692c5d39d51ba40` — REVIEWED / CHANGES REQUIRED / NOT ACCEPTED.

The durable `0045` folder configuration model and the read-only A4.1 phase boundary remain valid. The correction is limited to the MTProto provider contract and tests that prove real Telegram/Telethon folder and mute semantics.

Do NOT begin A4.2.

## Why correction is required

The reviewed implementation conflates two different Telegram concepts:

1. Custom UI folders are `DialogFilter` / `DialogFilterChatlist` definitions returned by `messages.getDialogFilters`.
2. `messages.getDialogs(folder_id=...)` / Telethon `iter_dialogs(folder=...)` uses peer-folder IDs, primarily `0` for normal dialogs and `1` for Archive; it does not enumerate an arbitrary custom `DialogFilter` by that filter's ID.

Therefore passing a custom filter ID such as the persisted ID for `Работа` to `iter_dialogs(folder=folder_id)` is not a valid implementation of custom-folder membership.

A second provider-contract issue exists: current Telegram schema returns `messages.DialogFilters` containing a `.filters` vector, so folder discovery must handle the actual wrapper shape instead of assuming the RPC result itself is the vector.

A third issue exists in mute detection: Telethon v1 `Dialog` has no reliable `dialog.muted` convenience attribute. Current effective mute state must be derived from the raw dialog notification settings (`dialog.dialog.notify_settings.mute_until`) against the current UTC time. Do not interpret a missing `muted` attribute as unmuted.

## Fixed branch

- Repository: `d-yacenko/secretary-prerelease`
- Work only in existing review worktree/branch: `review/telegram-depth-a4-folder-scope`.
- Start by fetching and fast-forwarding only to current `origin/review/telegram-depth-a4-folder-scope`, including Architect bookkeeping commits.
- Keep exact A3 SHA `4777c32deb055f5024f3dbced125b4dd6db97e85` in ancestry.
- Do not rebase or rewrite prior commits.

## Preserve from A4.1

Unless a minimal correction is necessary, preserve:

- migration `0045` and `telegram_mtproto_sync_folders` schema;
- stable custom filter ID + last-known display name persistence;
- exact trimmed name resolution;
- fail-closed missing/ambiguous configuration replacement;
- explicit empty configuration meaning disabled scope;
- `ignore_muted=true` product policy;
- existing A4.1 API surfaces and sanitized error model;
- read-only preview boundary: no history import, materialization, queue or scheduler work.

No new migration is expected for this correction. Alembic head must remain `0045`.

## Required correction

### 1. Read real custom dialog filters

Correct folder discovery around `messages.getDialogFilters`:

- consume the current `messages.DialogFilters.filters` vector (a compatibility fallback for a legacy bare vector is acceptable, but current shape must be explicitly covered by tests);
- expose only configurable named custom filters with stable positive IDs;
- support ordinary `DialogFilter` and `DialogFilterChatlist` where their semantics can be evaluated safely;
- do not present `DialogFilterDefault` as a configurable named folder;
- continue returning stable provider filter ID + current display name;
- keep the operation bounded and sanitized.

### 2. Stop using custom filter IDs as `iter_dialogs(folder=...)`

Remove the A4.1 path that calls Telethon `iter_dialogs(folder=<custom filter id>)`.

For custom folder scope resolution:

- fetch one bounded dialog universe with Telethon `iter_dialogs(limit=...)` and NO custom `folder` argument; unspecified `folder` is required so normal and archived dialogs can both participate in custom-filter evaluation;
- obtain the configured custom `DialogFilter` definitions by their stable IDs;
- evaluate custom filter membership locally from Telegram's returned filter definition plus live dialog facts;
- scan the dialog universe once per preview, then evaluate all configured filters over it; do not perform a full Telegram dialog scan independently for every configured filter;
- union eligible peers by stable marked peer ID.

This is an Architect correction to the prior assumption that Telegram exposed a direct custom-filter enumeration endpoint.

### 3. Membership semantics

For an ordinary `DialogFilter`, implement deterministic Telegram-compatible membership from these fields:

- `exclude_peers` blacklist;
- `pinned_peers` and `include_peers` explicit whitelist;
- category flags `contacts`, `non_contacts`, `groups`, `broadcasts`, `bots`;
- exclusion flags `exclude_muted`, `exclude_read`, `exclude_archived`.

Required precedence for this project:

1. explicit `exclude_peers` => not a member;
2. explicit `pinned_peers` or `include_peers` => member before category/exclusion flags;
3. otherwise at least one enabled category must match;
4. then apply `exclude_muted`, `exclude_read`, and `exclude_archived`.

For `DialogFilterChatlist`, membership is explicit pinned/include peers only; there are no category/exclusion flags to invent.

Normalize peer identity through Telegram/Telethon peer IDs; do not compare TL objects by Python object identity.

After folder membership is established, apply the independent product rule:

`eligible = member_of_any_configured_filter AND currently_not_muted`

Thus even an explicitly pinned/included peer is excluded from Secretary scope when it is currently muted.

### 4. Live dialog facts

Derive facts from the live Telethon dialog/entity shape:

- private contact: `User` with contact flag and not bot;
- private non-contact: `User` not contact and not bot;
- bot: `User.bot`;
- group: basic `Chat`;
- supergroup: `Channel.megagroup` and not broadcast;
- broadcast: broadcast `Channel`;
- archived: raw Telegram dialog `folder_id == 1` (or an equivalent Telethon property demonstrably backed by that raw field);
- read for `exclude_read`: treat the dialog as unread when `unread_count > 0` OR raw `unread_mark` is true; otherwise read;
- current muted: raw `notify_settings.mute_until` is a future Unix timestamp relative to current UTC time. Missing/zero/past `mute_until` is not currently muted. Do not use a nonexistent `dialog.muted` attribute and do not equate `silent` with this product mute rule.

Use dependency-injected/current-time helper where useful so tests are deterministic.

### 5. Supported Secretary peers

After Telegram filter membership is evaluated:

- Secretary eligible kinds remain private non-bot users, groups and supergroups;
- bots, broadcasts and other unsupported kinds must never become eligible;
- maintain sanitized aggregate skip counts/status;
- a peer present in multiple configured filters appears once.

### 6. Preserve A3/A4 boundary

Still forbidden in A4.1R:

- any `fetch_history` call from scope preview;
- A3 history sync invocation;
- writes to `telegram_mtproto_chat_selections` from dynamic scope;
- message/object materialization;
- job enqueueing or Telegram recurring scheduling;
- A2/A3 endpoint redesign;
- UI work;
- production deploy/migration/SSH/Compose/provider mutation.

## Required tests

Keep the existing A1/A2/A3/A4 tests, but strengthen A4 tests so the provider contract cannot be faked incorrectly.

At minimum cover:

- `messages.getDialogFilters` response wrapper with `.filters` is handled;
- `DialogFilterDefault` is ignored as configurable custom folder;
- ordinary named `DialogFilter` and `DialogFilterChatlist` are parsed with stable IDs/names;
- custom filter ID greater than `1` is NEVER passed as Telethon `iter_dialogs(folder=...)`;
- one bounded all-dialog scan is reused for multiple configured filters;
- explicit exclude wins;
- explicit include/pinned membership works independent of category flags;
- contacts and non-contacts categories;
- groups category includes basic groups and supergroups;
- `exclude_muted`, `exclude_read`, `exclude_archived` semantics;
- raw `notify_settings.mute_until`: future => muted; past/zero/missing => not muted;
- raw `unread_mark` prevents a manually-unread chat from being treated as read for `exclude_read`;
- final Secretary mute rule excludes even an explicitly included/pinned peer;
- bot/broadcast/unsupported are never eligible and are sanitized in counts;
- duplicate peer across filters is de-duplicated;
- renamed filter with stable ID still works;
- missing persisted filter ID still fails closed;
- empty configured list performs no Telegram dialog-universe scan;
- no history/materialization/queue/scheduler path is touched;
- provider/auth/FloodWait errors remain sanitized and retry-after behavior is preserved.

Prefer tests that construct/imitate the actual Telethon v1 raw/custom object shape rather than only testing a high-level fake `fetch_folder_dialogs` abstraction.

Run from `backend` at minimum:

`pytest -q tests/test_telegram_mtproto_a1.py tests/test_telegram_mtproto_a2.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py`

`alembic heads`

Also run `ruff check` on every Python file changed by the correction, or the repository-equivalent lint command if already established.

## Completion report

Commit and push only to `review/telegram-depth-a4-folder-scope`. Do not merge to `main`.

Return:

- starting branch HEAD after Architect bookkeeping fast-forward;
- correction commit SHA(s);
- final pushed branch HEAD;
- changed files;
- confirmation Alembic remains `0045`;
- exact test/lint commands and results;
- short explanation of custom `DialogFilter` membership evaluation;
- confirmation no custom filter ID is sent to `iter_dialogs(folder=...)`;
- short explanation of raw mute/read/archive derivation;
- confirmation A3 history/materialization/queue/scheduler paths remain untouched;
- `git status --short` for review worktree;
- final marker exactly: `TELEGRAM_A4_1_PROVIDER_FIX_READY`.

Then STOP. Do not begin A4.2.

## Production boundary

No production deployment, migration application, rollback, SSH, Compose, runtime probing, credential changes, or provider-side mutations are authorized.
