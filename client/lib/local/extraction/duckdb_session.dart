import 'dart:io';

import 'package:dart_duckdb/dart_duckdb.dart';

String escapeSqlString(String value) => value.replaceAll("'", "''");

class DuckDbSession {
  DuckDbSession._(this._db, this._conn);

  final Database _db;
  final Connection _conn;

  static Future<DuckDbSession> open() async {
    final db = await duckdb.open(':memory:');
    final conn = await duckdb.connect(db);
    return DuckDbSession._(db, conn);
  }

  Future<List<List<dynamic>>> queryRows(String sql) async {
    final result = await _conn.query(sql);
    return result.fetchAll();
  }

  Future<void> dispose() async {
    await _conn.dispose();
    await _db.dispose();
  }
}

Future<T> withDuckDb<T>(Future<T> Function(DuckDbSession session) action) async {
  final session = await DuckDbSession.open();
  try {
    return await action(session);
  } finally {
    await session.dispose();
  }
}

String parquetPathLiteral(String path) =>
    "'${escapeSqlString(File(path).absolute.path)}'";
