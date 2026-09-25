# Current task — Client Baseline Migration: Flutter 3.47 / Dart 3.13 compatibility

The isolated compatibility probe is architect-accepted as Outcome B: the migration is viable but requires a bounded client dependency refresh.

Implement only the repository migration needed to make the existing Flutter client compatible with Flutter 3.47.5 / Dart 3.13.4.

Do not resume Visual Task Map V2 in this task.
Do not add `elk`.
Do not change Task/product semantics.
Do not fix `dart_duckdb` Android packaging in this task.

## Goal

After this task, the committed client should:

- resolve and analyze on Flutter 3.47.5 / Dart 3.13.4;
- build Linux debug successfully;
- preserve current behavior and existing product tests;
- preserve Android minSdk 23;
- preserve the three deliberate Android compatibility pins unless the exact existing constraints resolve unchanged;
- remain otherwise functionally unchanged.

Android debug APK proof may stop only on the already reproduced upstream `dart_duckdb` 1.4.4 native zip HTTP 404. Any different Android failure is a blocker for this migration.

## 1. SDK constraint

Raise the Dart SDK lower bound only as far as needed for the new client baseline.

Target a constraint compatible with Dart 3.13 while not unnecessarily excluding later Dart 3.x versions.

Do not add FVM, Melos, or another toolchain manager unless the repository already uses one. It currently does not.

Do not commit a local absolute Flutter SDK path.

## 2. Dependency refresh

Refresh the lockfile under Flutter 3.47.5 / Dart 3.13.4.

The known required source-compatibility change is the PDF stack:

- move `pdfrx` from locked 2.2.24 to the Dart-3.13-compatible line observed in the probe;
- `pdfrx 2.6.5` / `pdfrx_engine 0.6.1` is the proven compatible result.

Prefer staying within the existing declared `pdfrx: ^2.2.24` constraint if ordinary resolution produces the proven compatible versions.

Do not broaden unrelated direct dependency ranges just to obtain newer packages.

SDK-transitive lockfile changes caused by Flutter 3.47 are allowed when they are a normal consequence of `flutter pub get`.

## 3. Preserve Android compatibility invariants

Do not change:

- application minSdk 23;
- `shared_preferences_android: >=2.4.0 <2.4.18`;
- `url_launcher_android: >=6.3.0 <6.3.21`;
- `flutter_plugin_android_lifecycle: >=2.0.0 <2.0.34`.

The probe showed all three still resolve on Flutter 3.47.

Warnings that Flutter may require newer Gradle/AGP/Kotlin/minSdk in a future release are not authorization to upgrade them now.

Do not regenerate the Android project wholesale.

## 4. Analysis configuration

If Flutter 3.47 automatically or materially requires excluding generated/build/platform trees from analysis, make only the smallest repository-level `analysis_options.yaml` change justified by the probe.

Do not hide real `lib/` or `test/` warnings/errors with broad exclusions.

Document any analysis config delta precisely.

## 5. Source compatibility

First attempt the migration with no application source changes.

If existing Secretary source under `client/lib` requires a small mechanical compatibility change for Dart 3.13, make only the minimum safe fix and add/update focused tests where appropriate.

Do not redesign APIs or clean up unrelated warnings.

If a broad source migration becomes necessary, STOP and report instead of expanding scope.

## 6. Linux proof is required

On Flutter 3.47.5 / Dart 3.13.4 run:

- `flutter pub get`;
- `flutter analyze`;
- focused Graph / Task Map / Task Profile tests;
- a broad `flutter test` run, with exact timeout/pre-existing failures recorded;
- `flutter build linux --debug`.

Linux debug build must succeed.

If it does not, this migration is not complete.

## 7. Android proof and known DuckDB blocker

Run:

- `flutter build apk --debug`.

Expected allowed stop condition:

- build reaches `dart_duckdb` 1.4.4 `downloadAndExtractDuckDB`;
- the exact upstream URL for `libduckdb-android_arm64-v8a.zip` (or the corresponding configured ABI asset) returns HTTP 404;
- no earlier Secretary/toolchain/dependency incompatibility occurs.

If Android fails before that point for a new reason, migration is NOT accepted.

Do not:
- vendor a DuckDB binary;
- fork `dart_duckdb`;
- patch pub cache/plugin files;
- change minSdk;
- swap database libraries;
- disable Android ABI builds.

Record the exact 404 as a separate known platform blocker.

## 8. Do not add ELK yet

Even though `elk: 0.2.0` resolves on Dart 3.13, do not add it in this migration.

Visual Task Map V2 resumes only after this client baseline is architect-reviewed.

## 9. Existing V1 graph experiment

Do not change or remove:
- current Graph renderer;
- V1 GraphView dependency or experiment;
- graph behavior;
- Task Map presentation.

This task is infrastructure compatibility only.

## Focused proof

At minimum prove:

1. Committed SDK constraint accepts Dart 3.13.
2. `flutter pub get` succeeds on Flutter 3.47.5.
3. `pdfrx` / `pdfrx_engine` resolve to a Dart-3.13-compatible combination.
4. Existing Android compatibility pins remain unchanged.
5. minSdk remains 23.
6. `flutter analyze` has 0 errors.
7. Existing graph/task-map focused tests compile and run.
8. Linux debug build succeeds.
9. Broad test run has no new compilation failure attributable to Dart 3.13 migration.
10. Android build reaches only the known `dart_duckdb` upstream 404 blocker, with no earlier migration regression.
11. No `elk` dependency is committed.
12. No backend/ontology/product/deploy changes.

## Completion

When complete:

- commit the bounded client migration;
- record implementation SHA and exact dependency/version deltas in `PROJECT_STATE.md`;
- record exact analyze/test/Linux/Android results;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Do not fix DuckDB and do not resume Visual Task Map V2 automatically.
