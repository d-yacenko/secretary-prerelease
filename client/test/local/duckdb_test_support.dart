import 'dart:io';

import 'package:dart_duckdb/dart_duckdb.dart';
import 'package:dart_duckdb/src/ffi/load_library.dart' as duckdb_loader;
import 'package:flutter_test/flutter_test.dart';

String? _duckDbLibraryPath() {
  if (!Platform.isLinux) {
    return null;
  }
  final candidates = <String>[
    '${Platform.environment['HOME']}/.pub-cache/hosted/pub.dev/dart_duckdb-1.4.4/linux/Libraries/release/libduckdb.so',
    '${Directory.current.path}/../duckdb/linux/Libraries/release/libduckdb.so',
    '${Directory.current.path}/build/linux/x64/debug/bundle/lib/libduckdb.so',
  ];
  for (final candidate in candidates) {
    if (File(candidate).existsSync()) {
      return candidate;
    }
  }
  return null;
}

void configureDuckDbForTests() {
  final path = _duckDbLibraryPath();
  if (path != null) {
    duckdb_loader.open.overrideFor(OperatingSystem.linux, path);
  }
}

bool get isDuckDbAvailable {
  final path = _duckDbLibraryPath();
  return path != null && File(path).existsSync();
}

void requireDuckDbForTests(bool available) {
  if (!available) {
    fail('BLOCKED: DuckDB is required but unavailable on this host');
  }
}
