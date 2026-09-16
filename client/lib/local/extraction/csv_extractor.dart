import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:csv/csv.dart';

import '../client_content_revision.dart';
import 'dataset_sampling.dart';
import 'extraction_constants.dart';
import 'representation_builder.dart';
import 'spreadsheet_columns.dart';

const _csvConverter = CsvToListConverter(shouldParseNumbers: false, eol: '\n');

Stream<List<dynamic>> _streamCsvRows(File file) {
  return file.openRead().transform(utf8.decoder).transform(_csvConverter);
}

Future<List<Map<String, dynamic>>> extractCsvFile(File file) async {
  final size = await file.length();
  if (size <= kMaxExtractorTotalBytes) {
    return _extractSmallCsv(file);
  }
  return _extractLargeCsv(file);
}

Future<List<Map<String, dynamic>>> _extractSmallCsv(File file) async {
  final text = await file.readAsString();
  final rows = const CsvToListConverter(shouldParseNumbers: false).convert(
    text,
    eol: '\n',
  );
  if (rows.isEmpty) {
    return boundedRepresentations([
      {'kind': 'schema', 'text': 'columns: (empty)'},
    ]);
  }
  final rawHeader = rows.first.map((cell) => cell?.toString() ?? '').toList();
  final schema = resolvePositionalSchema(
    rawHeader: rawHeader,
    observedRowWidths: [
      for (var i = 1; i < rows.length; i++) rows[i].length,
    ],
    maxColumns: kMaxCsvColumns,
  );
  final fieldnames = schema.columnKeys;
  final displayHeaders = schema.displayHeaders;
  final dataRows = <Map<String, String>>[];
  for (var i = 1; i < rows.length; i++) {
    final parsed = rows[i];
    dataRows.add({
      for (var col = 0; col < fieldnames.length; col++)
        fieldnames[col]:
            col < parsed.length ? parsed[col]?.toString() ?? '' : '',
    });
  }
  return _withSourceTruncation(
    _buildCsvRepresentations(fieldnames, displayHeaders, dataRows),
    schema.truncated,
  );
}

Future<List<Map<String, dynamic>>> _extractLargeCsv(File file) async {
  final schema = await _resolveCsvPositionalSchema(file);
  final fieldnames = schema.columnKeys;
  final displayHeaders = schema.displayHeaders;
  if (fieldnames.isEmpty) {
    return boundedRepresentations([
      {'kind': 'schema', 'text': 'columns: (empty)'},
    ]);
  }

  final stats = await _streamCsvStats(file, fieldnames, displayHeaders);
  final statsMeta = stats.$1;
  final statsLines = stats.$2;
  final columnTypes = stats.$3;
  final totalRows = statsMeta['row_count'] as int? ?? await _countCsvRows(file);

  final estimateRows = await _readCsvIndexedRows(file, fieldnames, [0]);
  final estimateRow = estimateRows.isNotEmpty
      ? estimateRows.first.values
      : {for (final name in fieldnames) name: ''};

  final structuralBytes = estimateStructuralBytes(
    fieldnames,
    columnTypes,
    statsLines,
  );
  final compactIndices = compactPreviewIndices(totalRows);
  final compactEstimate = formatSampleText([estimateRow], fieldnames);
  final planned = planSearchableIndices(
    totalRows: totalRows,
    fieldnames: fieldnames,
    estimateRow: estimateRow,
    structuralBytes: structuralBytes,
    compactSampleBytes: utf8ByteLength(compactEstimate),
  );
  final allIndices = {...compactIndices, ...planned.$1.indices}.toList()..sort();
  final indexedRows = await _readCsvIndexedRows(file, fieldnames, allIndices);
  return _withSourceTruncation(
    buildIndexedDatasetRepresentations(
      fieldnames: fieldnames,
      columnTypes: columnTypes,
      statsMeta: statsMeta,
      statsLines: statsLines,
      totalRows: totalRows,
      indexedRows: indexedRows,
      compactIndices: compactIndices,
      searchableIndices: planned.$1.indices,
    ),
    schema.truncated,
  );
}

List<Map<String, dynamic>> _buildCsvRepresentations(
  List<String> fieldnames,
  List<String> displayHeaders,
  List<Map<String, String>> dataRows,
) {
  final columnTypes = {for (final name in fieldnames) name: 'string'};
  final statsMeta = <String, dynamic>{
    'row_count': dataRows.length,
    'rows_sampled': dataRows.length,
    'column_count': fieldnames.length,
    'stats_truncated': false,
    'columns': <String, dynamic>{},
  };
  final statsLines = <String>[
    formatPositionalSchemaLine(fieldnames, displayHeaders),
    'rows: ${dataRows.length}',
    'columns: ${fieldnames.length}',
  ];
  final indexedRows = [
    for (var i = 0; i < dataRows.length; i++)
      IndexedRow(index: i, values: dataRows[i]),
  ];
  final compactIndices = compactPreviewIndices(dataRows.length);
  final estimateRow = dataRows.isNotEmpty
      ? dataRows.first
      : {for (final name in fieldnames) name: ''};
  final structuralBytes = estimateStructuralBytes(
    fieldnames,
    columnTypes,
    statsLines,
  );
  final planned = planSearchableIndices(
    totalRows: dataRows.length,
    fieldnames: fieldnames,
    estimateRow: estimateRow,
    structuralBytes: structuralBytes,
    compactSampleBytes: utf8ByteLength(
      formatSampleText([estimateRow], fieldnames),
    ),
  );
  return buildIndexedDatasetRepresentations(
    fieldnames: fieldnames,
    columnTypes: columnTypes,
    statsMeta: statsMeta,
    statsLines: statsLines,
    totalRows: dataRows.length,
    indexedRows: indexedRows,
    compactIndices: compactIndices,
    searchableIndices: planned.$1.indices,
  );
}

Future<PositionalSchema> _resolveCsvPositionalSchema(File file) async {
  var isHeader = true;
  List<String> rawHeader = [];
  var maxObservedWidth = 0;
  var widthOverflow = false;

  void consider(int width) {
    if (width > kMaxCsvColumns) {
      widthOverflow = true;
      if (kMaxCsvColumns > maxObservedWidth) {
        maxObservedWidth = kMaxCsvColumns;
      }
    } else if (width > maxObservedWidth) {
      maxObservedWidth = width;
    }
  }

  await for (final row in _streamCsvRows(file)) {
    if (isHeader) {
      rawHeader = row.map((cell) => cell?.toString() ?? '').toList();
      consider(rawHeader.length);
      isHeader = false;
      continue;
    }
    if (!row.any((cell) => cell?.toString().trim().isNotEmpty ?? false)) {
      continue;
    }
    consider(row.length);
  }
  final schema = resolvePositionalSchema(
    rawHeader: rawHeader,
    observedRowWidths:
        maxObservedWidth == 0 ? const <int>[] : [maxObservedWidth],
    maxColumns: kMaxCsvColumns,
  );
  if (!widthOverflow) {
    return schema;
  }
  return PositionalSchema(
    columnKeys: schema.columnKeys,
    displayHeaders: schema.displayHeaders,
    truncated: true,
  );
}

List<Map<String, dynamic>> _withSourceTruncation(
  List<Map<String, dynamic>> reps,
  bool truncated,
) {
  if (!truncated) {
    return reps;
  }
  final meta = truncationMetadata(truncated);
  return [
    for (final rep in reps)
      {
        ...rep,
        'metadata': {
          ...(rep['metadata'] as Map<String, dynamic>? ?? {}),
          ...meta,
        },
      },
  ];
}

Future<(List<String>, List<String>)> _readCsvHeaderPositional(File file) async {
  final schema = await _resolveCsvPositionalSchema(file);
  return (schema.columnKeys, schema.displayHeaders);
}

Future<List<String>> _readCsvHeader(File file) async {
  final header = await _readCsvHeaderPositional(file);
  return header.$1;
}

Future<int> _countCsvRows(File file) async {
  var count = 0;
  var isHeader = true;
  await for (final row in _streamCsvRows(file)) {
    if (isHeader) {
      isHeader = false;
      continue;
    }
    if (row.any((cell) => cell?.toString().trim().isNotEmpty ?? false)) {
      count += 1;
    }
  }
  return count;
}

Future<(
  Map<String, dynamic>,
  List<String>,
  Map<String, String>,
)> _streamCsvStats(
  File file,
  List<String> fieldnames,
  List<String> displayHeaders,
) async {
  final columnTypes = {for (final name in fieldnames) name: 'string'};
  final numericValues = {for (final name in fieldnames) name: <double>[]};
  var rowsSeen = 0;
  var truncated = false;
  var isHeader = true;

  await for (final parsed in _streamCsvRows(file)) {
    if (isHeader) {
      isHeader = false;
      continue;
    }
    if (!parsed.any((cell) => cell?.toString().trim().isNotEmpty ?? false)) {
      continue;
    }
    rowsSeen += 1;
    if (rowsSeen > kMaxCsvStatsRows) {
      truncated = true;
      break;
    }
    for (var i = 0; i < fieldnames.length && i < parsed.length; i++) {
      final value = parsed[i]?.toString() ?? '';
      if (value.isEmpty) {
        continue;
      }
      final name = fieldnames[i];
      if (_looksInt(value)) {
        columnTypes[name] =
            columnTypes[name] == 'string' ? 'integer' : columnTypes[name]!;
      } else if (_looksFloat(value) && columnTypes[name] != 'integer') {
        columnTypes[name] = 'float';
      }
      final number = double.tryParse(value);
      if (number != null) {
        numericValues[name]!.add(number);
      }
    }
  }

  final statsMeta = <String, dynamic>{
    'row_count': truncated ? null : rowsSeen,
    'rows_sampled': min(rowsSeen, kMaxCsvStatsRows),
    'column_count': fieldnames.length,
    'stats_truncated': truncated,
    'columns': <String, dynamic>{},
  };
  final lines = <String>[
    formatPositionalSchemaLine(fieldnames, displayHeaders),
    'rows: ${truncated ? 'unknown (sampled)' : rowsSeen}',
    'columns: ${fieldnames.length}',
  ];
  if (truncated) {
    lines.add('rows_sampled: $kMaxCsvStatsRows');
  }
  for (final name in fieldnames) {
    final numbers = numericValues[name]!;
    if (numbers.isEmpty) {
      continue;
    }
    final minValue = numbers.reduce((a, b) => a < b ? a : b);
    final maxValue = numbers.reduce((a, b) => a > b ? a : b);
    final mean = numbers.reduce((a, b) => a + b) / numbers.length;
    statsMeta['columns'][name] = {
      'min': minValue,
      'max': maxValue,
      'mean': mean,
      'sampled': truncated,
    };
    lines.add('$name: min=$minValue, max=$maxValue, mean=$mean');
  }
  return (statsMeta, lines, columnTypes);
}

Future<List<IndexedRow>> _readCsvIndexedRows(
  File file,
  List<String> fieldnames,
  List<int> indices,
) async {
  if (indices.isEmpty) {
    return [];
  }
  final wanted = indices.toSet();
  final rows = <int, Map<String, String>>{};
  var isHeader = true;
  var rowIndex = 0;
  await for (final parsed in _streamCsvRows(file)) {
    if (isHeader) {
      isHeader = false;
      continue;
    }
    if (!parsed.any((cell) => cell?.toString().trim().isNotEmpty ?? false)) {
      continue;
    }
    if (wanted.contains(rowIndex)) {
      rows[rowIndex] = {
        for (var i = 0; i < fieldnames.length; i++)
          fieldnames[i]: i < parsed.length ? parsed[i]?.toString() ?? '' : '',
      };
      if (rows.length == wanted.length) {
        break;
      }
    }
    rowIndex += 1;
  }
  return [
    for (final index in indices)
      if (rows.containsKey(index))
        IndexedRow(index: index, values: rows[index]!),
  ];
}

bool _looksInt(String value) => int.tryParse(value) != null;

bool _looksFloat(String value) => double.tryParse(value) != null;
