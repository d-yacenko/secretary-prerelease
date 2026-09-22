# Current task — Executor client acceptance: Android x2 + Linux

## Status

Telegram Bot retirement Stage C is COMPLETE / PRODUCTION ACCEPTED.

The next task is local client execution/installation only.

## Goal

Using the current canonical `main` checkout on the workstation:

1. diagnose the interrupted/garbled Linux build output if necessary;
2. build and launch the Linux Flutter client locally;
3. detect the Android devices currently connected and authorized to this workstation;
4. build one debug APK;
5. install/upgrade it on exactly the two connected Android devices without uninstalling existing app data;
6. launch the app on both Android devices;
7. report the resulting client readiness for the human Telegram Inbox acceptance.

Do not perform backend or production work.

## Repository/workstation bootstrap

Use the existing checkout:

`~/work/secretary-prerelease`

Start with:
- verify canonical origin;
- `git switch main`;
- `git pull --ff-only`;
- require clean tracked worktree before any build;
- inspect `client/README.md`.

Do not alter Git refs.

## Authorized local actions

AUTHORIZED:
- `flutter doctor -v`;
- `flutter devices`;
- `adb devices -l`;
- local package/toolchain inspection;
- `flutter pub get`;
- `flutter analyze`;
- focused/client tests if useful;
- `flutter clean` if needed to clear corrupted/interrupted local build artifacts;
- `flutter build linux --debug`;
- launch the built Linux bundle locally;
- `flutter build apk --debug`;
- install/upgrade APK with `adb -s <serial> install -r ...` on exactly two connected, authorized Android devices;
- launch the installed app on those two devices through adb/Flutter tooling;
- read sanitized build/device diagnostics.

The two Android installs must preserve existing app data. Do NOT uninstall the application or clear package data.

## Device rules

- Operate only on Android devices already connected and authorized to this workstation.
- Require exactly two intended Android devices before installation.
- If more than two Android devices/emulators are visible and intent is ambiguous, STOP and report sanitized device model/serial summaries rather than choosing arbitrarily.
- Do not enable wireless debugging, pair new devices, alter device security settings, or factory-reset anything.

## Linux build handling

The previous human attempt produced garbled binary-looking terminal output and was interrupted during:

`Building Linux application...`

Do not assume product-code corruption from that output.

First verify the local Flutter/Linux toolchain and build cleanly.

If Linux build fails:
- capture the first meaningful textual compiler/linker error;
- do not dump binary garbage;
- do not patch application code in this task;
- report whether the blocker is toolchain/dependency, build cache, or not yet classified;
- STOP only if the local build cannot be completed safely.

If the build succeeds, launch:

`client/build/linux/x64/debug/bundle/personal_secretary`

(or the exact bundle path produced by the current Flutter toolchain).

## Android install handling

From `client/`:

- build one debug APK;
- identify its exact produced path;
- install the same APK on both intended connected Android devices using upgrade semantics;
- do not use uninstall/reinstall;
- launch the application on each device after successful install.

If one device rejects installation:
- do not clear data or uninstall;
- report the sanitized adb/install error and continue only with safe read-only diagnosis.

## Acceptance boundary

Executor may establish:
- Linux BUILD PASS/FAIL;
- Linux LAUNCH PASS/FAIL;
- Android device 1 INSTALL PASS/FAIL and LAUNCH PASS/FAIL;
- Android device 2 INSTALL PASS/FAIL and LAUNCH PASS/FAIL.

Human remains responsible for visual/product acceptance:
- confirm production connection/authentication;
- Telegram MTProto connected;
- folder selection/save/apply;
- send a fresh inbound Telegram message;
- verify it appears in ordinary Inbox.

Do not automate Telegram/provider message sending in this task.

## Folder UX reminder for the human

Deterministic flow:

1. tick folder checkbox;
2. keep `Исключать заглушенные чаты` enabled;
3. press `Сохранить папки`;
4. optional `Предпросмотр области`;
5. press `Применить область`.

Recurring MTProto sync also reconciles the saved folder configuration automatically, but Apply gives immediate deterministic reconciliation.

## Hard prohibitions

NOT AUTHORIZED:
- production SSH;
- backend deploy/rollback;
- DB/env writes outside normal client API use;
- schema/data cleanup;
- provider credential changes;
- Bot API restoration;
- Telegram provider calls by executor;
- MTProto AI enablement;
- application source-code changes;
- Git ref movement;
- Android uninstall / clear-data.

## Required report

Return:
- canonical main SHA used;
- Flutter version / doctor summary only if relevant;
- Linux build PASS/FAIL;
- Linux launch PASS/FAIL;
- Android devices detected (sanitized model + serial suffix is enough);
- APK path;
- Android 1 install PASS/FAIL;
- Android 1 launch PASS/FAIL;
- Android 2 install PASS/FAIL;
- Android 2 launch PASS/FAIL;
- whether existing app data was preserved (must be yes / no uninstall);
- any sanitized blocker.

Then STOP.

Final marker:

`CLIENT_ACCEPTANCE_BUILDS_INSTALLED_READY`

`CURRENT_TASK.md` is the source of active authorization.
