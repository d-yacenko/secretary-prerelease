import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/local/extraction/duckdb_session.dart';

import 'duckdb_test_support.dart';
import 'format_parity_fixtures.dart';

void main() {
  setUpAll(configureDuckDbForTests);

  test('parquet row-group bounded read uses range predicate', () async {
    requireDuckDbForTests(isDuckDbAvailable);
    final tempDir = Directory.systemTemp.createTempSync('parquet-rg-');
    try {
      final file = File('${tempDir.path}/large.parquet');
      await writeLargeParquet(file, 10000, markerRow: 9999);
      final pathLiteral = parquetPathLiteral(file.path);

      await withDuckDb((session) async {
        final groups = await session.queryRows(
          'SELECT row_group_id, row_group_num_rows '
          'FROM parquet_metadata($pathLiteral) ORDER BY row_group_id',
        );
        expect(groups.length, greaterThan(3));

        var startRow = 0;
        final targetGlobalRows = [0, 5000, 9999];
        final touchedGroups = <int>{};
        for (final group in groups) {
          final numRows = (group[1] as num).toInt();
          final endRow = startRow + numRows - 1;
          final groupIndices = targetGlobalRows
              .where((index) => index >= startRow && index <= endRow)
              .toList();
          if (groupIndices.isEmpty) {
            startRow += numRows;
            continue;
          }
          touchedGroups.add((group[0] as num).toInt());
          final inList = groupIndices.join(', ');
          final explainRows = await session.queryRows(
            'EXPLAIN SELECT file_row_number '
            'FROM read_parquet($pathLiteral, file_row_number=true) '
            'WHERE file_row_number BETWEEN $startRow AND $endRow '
            'AND file_row_number IN ($inList)',
          );
          final plan = explainRows.map((row) => row.join(' ')).join('\n').toLowerCase();
          expect(plan, contains('parquet'));
          startRow += numRows;
        }
        expect(touchedGroups.length, greaterThanOrEqualTo(2));
        expect(touchedGroups.length, lessThan(groups.length));
      });
    } finally {
      if (tempDir.existsSync()) {
        tempDir.deleteSync(recursive: true);
      }
    }
  });
}
