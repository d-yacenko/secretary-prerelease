# Current task — HOLD

Client toolchain probe is recorded. Do not upgrade the repository toolchain and do not resume Visual Task Map V2.

- Outcome: B. Upgrade is viable but requires a bounded migration.
- Probe SDK: temporary Flutter 3.47.5 / Dart 3.13.4. Checkout remains Flutter 3.38.5 / Dart 3.10.4.
- `elk: 0.2.0` resolves. Linux compile on the unchanged lock still fails in `pdfrx_engine` 0.3.9. A disposable lock move to `pdfrx` 2.6.5, inside the existing constraint, makes the Linux debug build and the focused graph tests match the known baseline.
- Debug APK does not finish: `dart_duckdb` 1.4.4 Android zip returns HTTP 404. minSdk stays 23, with a Flutter 3.47 warning that 24 will soon be required. The three Android compatibility pins were not relaxed.
- Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.
