# Current task — HOLD

Client baseline migration to Flutter 3.47.5 / Dart 3.13.4 is recorded. Implementation `d4555b34a17464498acd4b6683a4748a6da021cc`.

Do not resume Visual Task Map V2.
Do not add `elk`.
Do not fix `dart_duckdb`.

- SDK constraint is `>=3.13.0 <4.0.0`. Direct ranges are unchanged, including `pdfrx: ^2.2.24`. Lock refresh under Flutter 3.47.5 / Dart 3.13.4: `pdfrx` 2.2.24→2.6.5, `pdfrx_engine` 0.3.9→0.6.1, `pdfium_dart` 0.1.3→0.3.1, `pdfium_flutter` 0.1.9→0.3.1, `characters` 1.4.0→1.4.1, `intl` 0.20.2→0.20.3, `matcher` 0.12.17→0.12.20, `material_color_utilities` 0.11.1→0.13.0, `meta` 1.17.0→1.19.0, `test_api` 0.7.7→0.7.12, `vector_math` 2.2.0→2.4.3, plus new lock entries `cupertino_ui` 1.1.1 and `material_ui` 1.4.0.
- Unchanged pins: `shared_preferences_android` 2.4.17, `url_launcher_android` 6.3.20, `flutter_plugin_android_lifecycle` 2.0.33, `dart_duckdb` 1.4.4, `graphview` 1.5.1. minSdk remains 23. No `elk`.
- `flutter analyze --no-fatal-infos --no-fatal-warnings`: exit 0, 135 issues, 0 errors, 38 warnings, 97 infos. Focused Graph / Task Map / Task Profile tests: 86 passed, 3 failed (pre-existing detail-screen finders). Broad `flutter test`: 1165 passed, 43 failed, 0 compilation failures. Linux debug succeeded: `build/linux/x64/debug/bundle/personal_secretary`.
- Android debug APK stopped only at `dart_duckdb` 1.4.4 `downloadAndExtractDuckDB`. `https://github.com/TigerEyeLabs/duckdb-dart/releases/download/v1.4.4/libduckdb-android_arm64-v8a.zip` returns HTTP 404. Gradle 8.14.0, AGP 8.11.1, Kotlin 2.2.20, and minSdk 23 produced warnings and were not upgraded.
- Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.
