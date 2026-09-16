import 'dart:convert';
import 'dart:io';

import 'dataset_sampling.dart';
import 'duckdb_session.dart';
import 'representation_builder.dart';

class _ParquetRowGroup {
  const _ParquetRowGroup({
    required this.id,
    required this.startRow,
    required this.endRow,
  });

  final int id;
  final int startRow;
  final int endRow;
}

Future<List<Map<String, dynamic>>> extractParquetFile(File file) async {
  return withDuckDb((session) async {
    final pathLiteral = parquetPathLiteral(file.path);
    final schemaRows = await session.queryRows(
      "DESCRIBE SELECT * FROM read_parquet($pathLiteral)",
    );
    final fieldnames = schemaRows.map((row) => row[0].toString()).toList();
    final columnTypes = {
      for (final row in schemaRows) row[0].toString(): row[1].toString(),
    };
    final countRows = await session.queryRows(
      'SELECT COUNT(*)::BIGINT FROM read_parquet($pathLiteral)',
    );
    final rowCount = (countRows.first.first as num).toInt();

    final stats = await _boundedParquetStats(
      session,
      pathLiteral,
      fieldnames,
      columnTypes,
      rowCount,
    );
    final statsMeta = stats.$1;
    final statsLines = stats.$2;

    final sampleRows = await _readParquetSampleRows(session, pathLiteral, 1);
    final estimateRow = sampleRows.isNotEmpty
        ? sampleRows.first
        : {for (final name in fieldnames) name: ''};

    final structuralBytes = estimateStructuralBytes(
      fieldnames,
      columnTypes,
      statsLines,
    );
    final compactIndices = compactPreviewIndices(rowCount);
    final compactEstimate = formatSampleText(
      [
        {
          for (final name in fieldnames)
            name: estimateRow[name]?.toString() ?? '',
        },
      ],
      fieldnames,
    );
    final planned = planSearchableIndices(
      totalRows: rowCount,
      fieldnames: fieldnames,
      estimateRow: {
        for (final name in fieldnames)
          name: estimateRow[name]?.toString() ?? '',
      },
      structuralBytes: structuralBytes,
      compactSampleBytes: utf8.encode(compactEstimate).length,
    );
    final allIndices = {...compactIndices, ...planned.$1.indices}.toList()
      ..sort();
    final indexedRows = await _readParquetIndexedRows(
      session,
      pathLiteral,
      fieldnames,
      allIndices,
    );
    return buildIndexedDatasetRepresentations(
      fieldnames: fieldnames,
      columnTypes: columnTypes,
      statsMeta: statsMeta,
      statsLines: statsLines,
      totalRows: rowCount,
      indexedRows: indexedRows,
      compactIndices: compactIndices,
      searchableIndices: planned.$1.indices,
    );
  });
}

Future<(Map<String, dynamic>, List<String>)> _boundedParquetStats(
  DuckDbSession session,
  String pathLiteral,
  List<String> fieldnames,
  Map<String, String> columnTypes,
  int rowCount,
) async {
  const maxRows = 5000;
  final truncated = rowCount > maxRows;
  final numericStats = <String, Map<String, dynamic>>{};
  final sampleLimit = rowCount < maxRows ? rowCount : maxRows;
  if (sampleLimit > 0) {
    final rows = await session.queryRows(
      'SELECT * FROM read_parquet($pathLiteral) LIMIT $sampleLimit',
    );
    for (final row in rows) {
      for (var i = 0; i < fieldnames.length; i++) {
        final name = fieldnames[i];
        final value = row[i];
        if (value == null) {
          continue;
        }
        final type = columnTypes[name] ?? '';
        if (!type.contains('INT') &&
            !type.contains('DOUBLE') &&
            !type.contains('FLOAT') &&
            !type.contains('DECIMAL')) {
          continue;
        }
        final number = (value as num).toDouble();
        final current = numericStats.putIfAbsent(
          name,
          () => {
            'min': number,
            'max': number,
            'sum': 0.0,
            'count': 0,
          },
        );
        current['min'] = (current['min'] as double) < number
            ? current['min']
            : number;
        current['max'] = (current['max'] as double) > number
            ? current['max']
            : number;
        current['sum'] = (current['sum'] as double) + number;
        current['count'] = (current['count'] as int) + 1;
      }
    }
  }

  final statsMeta = <String, dynamic>{
    'row_count': rowCount,
    'rows_sampled': sampleLimit,
    'column_count': fieldnames.length,
    'stats_truncated': truncated,
    'columns': <String, dynamic>{},
  };
  final lines = <String>[
    'rows: $rowCount',
    'columns: ${fieldnames.length}',
  ];
  if (truncated) {
    lines.add('rows_sampled: $maxRows');
  }
  for (final entry in numericStats.entries) {
    final count = entry.value['count'] as int;
    final mean = (entry.value['sum'] as double) / count;
    final colStats = {
      'min': entry.value['min'],
      'max': entry.value['max'],
      'mean': mean,
      'sampled': truncated,
    };
    statsMeta['columns'][entry.key] = colStats;
    lines.add(
      '${entry.key}: min=${colStats['min']}, max=${colStats['max']}, mean=$mean',
    );
  }
  return (statsMeta, lines);
}

Future<List<Map<String, dynamic>>> _readParquetSampleRows(
  DuckDbSession session,
  String pathLiteral,
  int limit,
) async {
  final rows = await session.queryRows(
    'SELECT * FROM read_parquet($pathLiteral) LIMIT $limit',
  );
  if (rows.isEmpty) {
    return [];
  }
  final fieldnames = await _parquetFieldnames(session, pathLiteral);
  return [
    for (final row in rows)
      {
        for (var i = 0; i < fieldnames.length; i++)
          fieldnames[i]: row[i]?.toString() ?? '',
      },
  ];
}

Future<List<String>> _parquetFieldnames(
  DuckDbSession session,
  String pathLiteral,
) async {
  final schemaRows = await session.queryRows(
    "DESCRIBE SELECT * FROM read_parquet($pathLiteral)",
  );
  return schemaRows.map((row) => row[0].toString()).toList();
}

Future<List<_ParquetRowGroup>> _parquetRowGroups(
  DuckDbSession session,
  String pathLiteral,
) async {
  final rows = await session.queryRows(
    'SELECT row_group_id, row_group_num_rows '
    'FROM parquet_metadata($pathLiteral) '
    'ORDER BY row_group_id',
  );
  var startRow = 0;
  return [
    for (final row in rows)
      () {
        final numRows = (row[1] as num).toInt();
        final group = _ParquetRowGroup(
          id: (row[0] as num).toInt(),
          startRow: startRow,
          endRow: startRow + numRows - 1,
        );
        startRow += numRows;
        return group;
      }(),
  ];
}

Future<List<IndexedRow>> _readParquetIndexedRows(
  DuckDbSession session,
  String pathLiteral,
  List<String> fieldnames,
  List<int> indices,
) async {
  if (indices.isEmpty) {
    return [];
  }
  final wanted = indices.toSet().toList()..sort();
  final groups = await _parquetRowGroups(session, pathLiteral);
  final columnList = fieldnames.map((name) => '"$name"').join(', ');
  final rowsByIndex = <int, Map<String, String>>{};

  for (final group in groups) {
    final groupIndices = wanted
        .where((index) => index >= group.startRow && index <= group.endRow)
        .toList();
    if (groupIndices.isEmpty) {
      continue;
    }
    final inList = groupIndices.join(', ');
    final rows = await session.queryRows(
      'SELECT file_row_number, $columnList '
      'FROM read_parquet($pathLiteral, file_row_number=true) '
      'WHERE file_row_number BETWEEN ${group.startRow} AND ${group.endRow} '
      'AND file_row_number IN ($inList) '
      'ORDER BY file_row_number',
    );
    for (final row in rows) {
      final index = (row.first as num).toInt();
      rowsByIndex[index] = {
        for (var i = 0; i < fieldnames.length; i++)
          fieldnames[i]: row[i + 1]?.toString() ?? '',
      };
    }
    if (rowsByIndex.length == wanted.length) {
      break;
    }
  }

  return [
    for (final index in indices)
      if (rowsByIndex.containsKey(index))
        IndexedRow(index: index, values: rowsByIndex[index]!),
  ];
}
