# Current task — Telegram MTProto M4AR: refresh stale Linux desktop client

## Status

Production backend/runtime is healthy and deployed at:
`8091736337689b68b4510126e74d9e409397f696`

Production Alembic:
`0046`

Telegram MTProto backend is configured and the human already completed MTProto authorization successfully through the existing application flow.

M4A is currently BLOCKED at the client presentation layer.

User evidence shows the Account screen contains:
- the legacy Telegram Bot connection block;
- then immediately the generic Sync section;
- NO `Telegram MTProto` section.

At exact production release SHA `8091736337689b68b4510126e74d9e409397f696`, `client/lib/account/account_screen.dart` unconditionally renders `TelegramMtprotoAccountSection` between Connections and Sync.

Therefore the currently running desktop client is stale relative to the deployed backend/release.

M3 only rebuilt/recreated backend `api` and `worker`; Flutter desktop client is not part of production Compose.

This task authorizes only **M4AR — build and launch a fresh Linux desktop client from the exact deployed release SHA so the human can continue M4A**.

No backend deploy, schema change, production ref move, or production env mutation is authorized.

## Exact client source

Build client from exact:

`CLIENT_RELEASE_SHA=8091736337689b68b4510126e74d9e409397f696`

Do not build from a newer moving `main`.

Use a separate clean checkout/worktree for this exact SHA if necessary.

## Safety

Do NOT:
- delete or overwrite the currently installed/running client before verification;
- delete SharedPreferences or secure storage;
- remove/reissue the Secretary bearer token;
- ask the human to paste bearer token, Telegram code, 2FA password, or session data into terminal/chat;
- inspect or print secure-storage contents;
- modify production backend/DB/.env/services;
- move Git refs;
- change client source code;
- create a new branch/commit.

If building the exact existing client requires a code change, STOP and report a blocker.

## Platform discovery

Non-destructively determine:
- whether the current user session is Linux desktop;
- currently running Secretary client process/binary path if discoverable without secrets;
- whether an older bundle is being launched.

Do not kill the old client until the fresh bundle is built and verified launchable.

If this is not Linux desktop, STOP and report the actual platform so Architect can authorize the correct client refresh path.

## Build

From exact `CLIENT_RELEASE_SHA`:

1. `cd client`
2. `flutter pub get`
3. run the relevant existing client tests for Account/MTProto presentation;
4. build Linux release bundle:
   `flutter build linux --release`

Expected bundle executable:
`client/build/linux/x64/release/bundle/personal_secretary`

Do not run `intermediates_do_not_run/personal_secretary`.

Verify:
- build PASS;
- bundle executable exists;
- bundle libraries/assets are present;
- RUNPATH fix completed as defined by current CMake/install rules;
- no source changes;
- exact source SHA remains `8091736337689b68b4510126e74d9e409397f696`.

## Launch verification

Launch the fresh release bundle directly from its bundle path.

Do not replace the existing launcher/install yet.

Preferred verification:
- human opens Account screen in the fresh bundle;
- `Telegram MTProto` section is visible between Connections and Sync;
- connected state is shown if existing local app credentials/preferences are reused;
- if Secretary client authentication is required, let the human use the existing UI; do not request or inspect bearer token;
- do not redo Telegram auth unless the UI truly reports disconnected.

If the MTProto section is visible, STOP before any sync and report success.

Do not choose folders/groups and do not run the first history sync in M4AR. That remains M4A after client refresh.

## If the fresh bundle still lacks MTProto section

STOP and report:
- exact source SHA;
- build result;
- binary path;
- screenshot/UI fact;
- whether the expected widget key/source is present in source;
- no code change attempted.

Marker:
`TELEGRAM_MTPROTO_M4AR_CLIENT_REFRESH_BLOCKED`

## Completion report

Return:
- platform;
- exact client source SHA;
- build command/result;
- relevant focused test result;
- fresh bundle path;
- whether fresh bundle launched;
- whether Account shows `Telegram MTProto`;
- whether connected status is visible;
- confirmation old installed client was not deleted/overwritten;
- confirmation secure storage/preferences were not cleared;
- confirmation no secrets were inspected/printed;
- confirmation production backend/schema/ref/env untouched;
- clean exact-SHA worktree.

Success marker:
`TELEGRAM_MTPROTO_M4AR_CLIENT_REFRESH_READY`

Then STOP for Architect/human verification.

`CURRENT_TASK.md` is the source of active authorization.
