# Current task — Client acceptance: Android x2 + Linux + Telegram Inbox

## Status

Telegram Bot retirement Stage C is COMPLETE / PRODUCTION ACCEPTED.

This task is manual client acceptance only.

## Goal

Build the current Flutter client from canonical `main`, install/upgrade it on two Android devices, run the Linux desktop app locally, and verify ordinary Inbox visibility of a fresh inbound Telegram MTProto message from at least one configured Telegram folder.

## Authorized actions

AUTHORIZED:
- local `git pull --ff-only`;
- `flutter pub get`;
- local Flutter analyze/test/build if desired;
- build Android debug APK;
- install/upgrade that APK on two personally controlled Android devices;
- build/run Linux client locally;
- configure the clients with the existing Secretary production server URL and an existing valid bearer token;
- ordinary client read/use operations;
- send one ordinary test Telegram message to the connected Telegram account from another account/device;
- folder selection/save/preview/apply through the existing client UI;
- ordinary Inbox refresh/navigation;
- optional manual per-peer `Синхронизировать` if needed to distinguish recurring-sync delay from client visibility.

NOT AUTHORIZED:
- backend deploy/rollback;
- production SSH;
- direct DB/env modification;
- schema/data cleanup;
- provider credential changes;
- Bot API restoration;
- MTProto AI enablement;
- destructive Telegram actions.

## Folder UX for acceptance

For a configured folder:
1. tick the folder checkbox;
2. leave `Исключать заглушенные чаты` enabled;
3. press `Сохранить папки`;
4. optionally press `Предпросмотр области`;
5. press `Применить область` for immediate deterministic scope reconciliation.

Recurring MTProto sync also calls scope reconciliation on each run, so step 5 is not required for eventual reconciliation after a successful save; it is recommended for immediate/manual acceptance.

The per-peer `Синхронизировать` button is optional and forces an immediate history fetch for that active peer.

## Manual PASS criteria

- Android device 1: app installs/upgrades and launches.
- Android device 2: app installs/upgrades and launches.
- Linux: app builds/runs locally.
- Clients can authenticate/connect to the production Secretary backend.
- Telegram MTProto account shows connected.
- At least one configured folder is active.
- A fresh inbound Telegram message is sent into a chat belonging to that folder.
- The message becomes visible in the ordinary Secretary Inbox on at least one Android device.
- Preferably confirm the same Inbox state on the second Android device and Linux client as a cross-client sanity check.
- No AI enablement or Bot API behavior is involved.

## Failure reporting

If the message is not visible:
- do not change production directly;
- record whether folder Save/Apply succeeded;
- record whether Preview shows the expected peer;
- record whether manual per-peer Sync succeeds;
- record whether the message is visible after manual Sync;
- report only sanitized UI/error text, never bearer tokens or Telegram credentials.

## Required human report

Return:
- Android 1 install/launch PASS/FAIL;
- Android 2 install/launch PASS/FAIL;
- Linux launch PASS/FAIL;
- selected folder name may be described generically if preferred;
- folder Save PASS/FAIL;
- Apply scope PASS/FAIL;
- fresh inbound message visible in Inbox PASS/FAIL;
- whether it appeared automatically or only after manual Sync;
- any sanitized UI error text.

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
