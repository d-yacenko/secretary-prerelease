# Current task — Client Toolchain Probe: Flutter 3.47 / Dart 3.13 compatibility

Visual Task Map V2 is blocked only because the candidate pure-Dart `elk` package requires Dart 3.12+, while the current checkout uses Flutter 3.38.5 / Dart 3.10.4.

Do not resume Visual Task Map V2 yet.

Perform only an isolated compatibility probe of the existing Flutter client against current stable Flutter 3.47 / Dart 3.13.

This task is infrastructure validation, not a product phase.

## Goal

Determine whether the existing Android + Linux Flutter client and its dependency set can move to current stable Flutter/Dart cleanly enough to make ELK evaluation reasonable.

Do not commit a toolchain upgrade unless this task explicitly says to do so. It does not.

## 1. Isolation

Do not alter the user's existing working Flutter installation in place.

Use an isolated temporary Flutter 3.47 stable SDK / temporary environment.

Do not change committed repository files merely to make the probe pass.

If a dependency resolution requires a temporary pubspec edit, do it only in a disposable copy/worktree and report the exact required delta.

Do not push probe-only generated files.

## 2. Establish baseline

Record:

- current checkout Flutter version;
- current checkout Dart version;
- temporary probe Flutter version;
- temporary probe Dart version;
- host platform;
- current `client/pubspec.yaml` SDK constraint.

## 3. Existing client on new toolchain

Using the existing committed client dependency declarations first, run in the isolated probe:

- `flutter pub get`;
- `flutter analyze`;
- the focused graph/task-map test suite;
- a broad client test run if practical;
- `flutter build linux --debug`;
- `flutter build apk --debug`.

Do not opportunistically fix unrelated test failures.

Classify failures as:
- source/API incompatibility;
- dependency-resolution incompatibility;
- native/platform toolchain issue;
- known pre-existing test failure;
- probe-environment limitation.

## 4. Existing dependency constraints

Identify any direct dependency whose currently committed pin/range blocks Flutter 3.47 / Dart 3.13.

Pay special attention to the repository's deliberate Android compatibility pins:
- `shared_preferences_android`;
- `url_launcher_android`;
- `flutter_plugin_android_lifecycle`.

Do not relax them automatically.

If newer Flutter requires changing one of those pins, report:
- exact package;
- current constraint;
- minimum compatible replacement;
- whether the replacement changes Android minSdk requirements.

## 5. ELK resolution only

In a disposable copy after the existing client probe, add exactly:

`elk: 0.2.0`

Run `flutter pub get`.

If it resolves, record its transitive dependency delta.

Do not implement V2 geometry in this task.

Do not add another graph engine.

## 6. Source/build compatibility with ELK present

If `elk: 0.2.0` resolves without changing unrelated committed constraints, rerun at minimum:

- `flutter analyze`;
- focused graph/task-map tests;
- Linux debug build;
- Android debug APK build.

This proves only that the package can coexist with the client. Do not write ELK adapter/product code.

## 7. No repository migration yet

Do NOT commit:
- SDK constraint changes;
- dependency upgrades;
- Android Gradle changes;
- generated platform changes;
- ELK dependency;
- source fixes;
- lockfile changes.

The only repository changes authorized are task/status documentation at completion.

If a tiny source compatibility fix is absolutely necessary to prove the toolchain and is clearly mechanical, STOP and report it rather than applying it; Architect will decide whether an upgrade task is warranted.

## 8. Decision output

Conclude with exactly one of these evidence-based outcomes:

### A. Upgrade looks low-risk
Use when existing app + ELK resolve/analyze/tests/builds pass with no or very small clearly identified repository migration.

### B. Upgrade is viable but requires bounded migration
Use when a finite set of dependency/source/platform changes is required and can be enumerated.

### C. Upgrade is disproportionate for the visualization spike
Use when the migration affects broad app/platform behavior, minSdk policy, multiple plugins, or creates substantial regression risk.

Do not decide the next graph engine yourself.

## Required checks/results to record

At minimum record:

- current/probe Flutter + Dart versions;
- `flutter pub get` result on unchanged client;
- `flutter analyze` result;
- focused graph/task-map tests;
- Linux debug build;
- Android debug APK build;
- ELK 0.2.0 resolve result;
- any required dependency/source deltas;
- Android minSdk impact if any.

## Completion

When finished:

- append factual probe results to `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- push documentation-only result to `origin/main`;
- STOP.

Do not upgrade the repository toolchain and do not resume Visual Task Map V2 automatically.
