# Current task — Client C0: exact-release Linux refresh for human Direction visual gate

Production D2 is ACCEPTED.

Production backend/runtime and `origin/production` are exact:
`fd45df20ff53ad973f22e461ff84f3cb5c251b8a`

Production Alembic:
`0050`

The backend is ready for the previously deferred human S2/Direction visual gate.

This task authorizes only a local Linux client build/launch from the exact deployed release SHA so the human can perform that gate.

Do not start S3 or H2D.

## Goal

On the user's Linux workstation:

1. build the Flutter client from exact source SHA `fd45df20ff53ad973f22e461ff84f3cb5c251b8a`;
2. verify the expected S2 client code/tests at that exact SHA;
3. launch the built Linux bundle if the current Executor environment has access to the user's graphical desktop session;
4. hand control to the human for manual product/visual validation.

Executor must NOT perform the Direction/Task/Graph acceptance interactions itself.

## Repository/bootstrap

Follow `AGENTS.md` and `docs/executor_bootstrap.md`.

Canonical repository:
`https://github.com/d-yacenko/secretary-prerelease.git`

Client source SHA:
`fd45df20ff53ad973f22e461ff84f3cb5c251b8a`

Do not build moving `main` by name.

If the current checkout is wrong-origin, dirty, stale, or not safely usable, leave it untouched and use a fresh temporary canonical clone/worktree.

Verify the exact source SHA before running Flutter commands.

Do not move Git refs.

## Platform boundary

This task is Linux desktop only.

Non-destructively determine whether the Executor is operating in the user's Linux desktop/workstation environment.

If not Linux, STOP with:
`CLIENT_C0_BLOCKED=wrong_platform`

If Linux build is possible but graphical launch is unavailable from the Executor session, completing the verified build is still useful. Report:
`CLIENT_C0_BUILD_READY_HUMAN_LAUNCH_REQUIRED`

Do not classify missing GUI attachment as a product defect.

## Focused verification

From exact source SHA:

```bash
cd client
flutter pub get
flutter test test/capture_test.dart
flutter test test/secretary_api_client_test.dart
flutter build linux --debug
```

Also run:
`git diff --check`

The two historical unrelated Task-management delete tests are outside this task and are not a reason to modify code.

Do not change source to make checks pass.

If a focused test or build fails because of product code, STOP and report the first meaningful sanitized failure.

If a required local build dependency/toolchain is missing, report the missing dependency and STOP. Do not make unrelated workstation/package changes in this task.

## Bundle

Expected debug bundle executable:
`client/build/linux/x64/debug/bundle/personal_secretary`

Use the actual path emitted by the current Flutter toolchain if it differs.

Do not run an `intermediates_do_not_run` executable.

Verify:
- bundle executable exists;
- required bundle assets/libraries were produced;
- worktree remains clean;
- source remains exact `fd45df20ff53ad973f22e461ff84f3cb5c251b8a`.

## Local state / credential safety

Preserve the user's existing Secretary client state.

Do NOT:
- uninstall the current Secretary client;
- clear SharedPreferences/application preferences;
- clear secure storage;
- remove or reissue the bearer token;
- print or inspect bearer tokens or secure-storage contents;
- change the saved API URL;
- ask the human to paste secrets into terminal/chat;
- replace the existing installed launcher/bundle yet.

This task is a verified fresh-bundle launch, not permanent installation.

## Launch

If the Executor has access to the user's graphical desktop session, launch the fresh exact-release bundle directly from its bundle path.

Do not replace the existing installed client first.

Executor may verify only non-sensitive runtime facts such as:
- process starts;
- process remains alive long enough to establish that startup did not immediately crash;
- no immediate textual startup error is emitted.

Then STOP and hand control to the human.

Do not click through Capture, Task editing, Graph, People, Telegram, Account, or other product UI.

Do not create/update/delete any Secretary data.

## Human gate boundary

After Client C0, the HUMAN will perform the previously recorded Direction visual gate using real manual interactions, including as appropriate:

- create ongoing Directions through Capture;
- exercise finite <-> ongoing editing;
- compose finite Tasks under Directions and a Direction under another Direction via confirmed `part_of`;
- inspect Graph overview/rooted hierarchy readability;
- verify Direction circle vs finite Task card distinction;
- inspect spatial stability and whether multiple Directions remain understandable.

These actions are NOT authorized for Executor in C0.

## Forbidden

Do not:
- SSH to production;
- deploy/rollback backend;
- modify DB, schema, containers, volumes, or production `.env`;
- touch provider configuration or Telegram scope/login;
- create production test data;
- alter client/backend source code;
- commit dependency/toolchain churn;
- install/replace the permanent client;
- start S3;
- start H2D.

## Completion

No repository code change is expected.

Return:

1. platform;
2. exact source SHA;
3. `flutter pub get` result;
4. Capture focused test result;
5. API client focused test result;
6. Linux debug build result;
7. exact fresh bundle path;
8. whether bundle launch was attempted;
9. launch result / whether process stayed alive;
10. confirmation source/worktree remained exact and clean;
11. confirmation saved API URL/preferences/secure storage/token were untouched;
12. confirmation backend/production was untouched;
13. confirmation no human-gate UI/data actions were performed.

Final marker:

- if built and launched: `CLIENT_C0_READY_FOR_HUMAN_GATE`
- if built but Executor cannot access GUI session: `CLIENT_C0_BUILD_READY_HUMAN_LAUNCH_REQUIRED`
- if blocked before build/launch: `CLIENT_C0_BLOCKED=<sanitized_reason>`

Then STOP. Do not choose the next task yourself.
