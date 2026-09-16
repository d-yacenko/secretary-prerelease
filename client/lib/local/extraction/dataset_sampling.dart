import 'dart:convert';

import '../client_content_revision.dart';
import 'extraction_constants.dart';
import 'representation_builder.dart';

class IndexedRow {
  const IndexedRow({
    required this.index,
    required this.values,
    this.sheetName,
    this.sourceRowNumber,
  });

  /// Global deterministic sampling identity (0-based).
  final int index;
  final Map<String, String> values;
  final String? sheetName;
  /// 1-based source row number within [sheetName] when applicable.
  final int? sourceRowNumber;
}

String searchableRowLabel(IndexedRow pair) {
  final rowNumber = pair.sourceRowNumber ?? (pair.index + 1);
  if (pair.sheetName != null) {
    return '[sheet=${pair.sheetName} row=$rowNumber]';
  }
  return '[row=$rowNumber]';
}

List<int> selectDistributedRowIndices(int totalRows, int targetCount) {
  if (totalRows <= 0 || targetCount <= 0) {
    return [];
  }
  if (targetCount >= totalRows) {
    return List.generate(totalRows, (i) => i);
  }
  if (targetCount == 1) {
    return [totalRows ~/ 2];
  }
  final indices = <int>{};
  for (var i = 0; i < targetCount; i++) {
    indices.add(((i * (totalRows - 1)) / (targetCount - 1)).round());
  }
  return indices.toList()..sort();
}

List<int> compactPreviewIndices(int totalRows) {
  if (totalRows <= 0) {
    return [];
  }
  if (totalRows <= kCompactSampleMaxRows) {
    return List.generate(totalRows, (i) => i);
  }
  return List.generate(kCompactSampleMaxRows, (i) => i);
}

int estimateRowBytes(List<String> fieldnames, Map<String, String> sampleRow) {
  if (fieldnames.isEmpty) {
    return 1;
  }
  final line = fieldnames.map((name) => sampleRow[name] ?? '').join(',');
  return utf8ByteLength(line) + 1;
}

String formatDatasetRowLine(
  Map<String, String> row,
  List<String> fieldnames,
) {
  return fieldnames.map((name) => row[name] ?? '').join(',');
}

int estimateSearchableRowBytes(
  List<String> fieldnames,
  Map<String, String> sampleRow,
  int rowIndex,
) {
  final rowLine = formatDatasetRowLine(sampleRow, fieldnames);
  final block = '${searchableRowLabel(IndexedRow(index: rowIndex, values: sampleRow))}\n$rowLine';
  return utf8ByteLength(block) + 1;
}

int estimateRowsForBudget(
  List<String> fieldnames,
  Map<String, String> sampleRow,
  int byteBudget, {
  bool searchable = false,
  int rowIndex = 0,
}) {
  if (fieldnames.isEmpty || byteBudget <= 0) {
    return 0;
  }
  final rowBytes = searchable
      ? estimateSearchableRowBytes(fieldnames, sampleRow, rowIndex)
      : estimateRowBytes(fieldnames, sampleRow);
  if (searchable) {
    return rowBytes <= 0 ? 0 : byteBudget ~/ rowBytes;
  }
  final headerBytes =
      utf8ByteLength('sample\n${fieldnames.join(',')}') + 1;
  final available = byteBudget - headerBytes;
  if (available <= 0) {
    return 0;
  }
  return rowBytes <= 0 ? 0 : available ~/ rowBytes;
}

int estimateStructuralBytes(
  List<String> fieldnames,
  Map<String, String> columnTypes,
  List<String> statsLines,
) {
  return utf8ByteLength(formatSchemaText(fieldnames, columnTypes)) +
      utf8ByteLength(statsLines.join('\n'));
}

(FitCompactResult, String, bool) fitCompactSamplePairs(
  List<IndexedRow> pairs,
  List<String> fieldnames,
) {
  var current = List<IndexedRow>.from(pairs);
  while (current.isNotEmpty) {
    final sampleText = formatSampleText(
      current.map((row) => row.values).toList(),
      fieldnames,
    );
    if (utf8ByteLength(sampleText) <= kMaxExtractorPartBytes) {
      return (FitCompactResult(current), sampleText, false);
    }
    if (current.length <= 1) {
      final clipped = capStructuralText(sampleText);
      return (FitCompactResult(current.take(1).toList()), clipped.$1, true);
    }
    current = current.take(current.length ~/ 2).toList();
  }
  return (const FitCompactResult([]), 'sample\n(empty)', true);
}

class FitCompactResult {
  const FitCompactResult(this.pairs);
  final List<IndexedRow> pairs;
}

(PlannedSearchable, String, bool) planSearchableIndices({
  required int totalRows,
  required List<String> fieldnames,
  required Map<String, String> estimateRow,
  required int structuralBytes,
  required int compactSampleBytes,
}) {
  final remainingBytes = (kMaxExtractorTotalBytes -
          structuralBytes -
          compactSampleBytes)
      .clamp(0, kMaxExtractorTotalBytes);
  final remainingParts =
      (kMaxExtractorParts - kDatasetStructuralParts).clamp(0, kMaxExtractorParts);
  final byteBudget = remainingBytes < remainingParts * kMaxExtractorPartBytes
      ? remainingBytes
      : remainingParts * kMaxExtractorPartBytes;
  final maxRows = estimateRowsForBudget(
    fieldnames,
    estimateRow,
    byteBudget,
    searchable: true,
    rowIndex: totalRows > 0 ? totalRows ~/ 2 : 0,
  );
  if (totalRows <= maxRows) {
    return (
      PlannedSearchable(List.generate(totalRows, (i) => i)),
      'full',
      false,
    );
  }
  final indices = selectDistributedRowIndices(totalRows, maxRows);
  return (
    PlannedSearchable(indices),
    'distributed',
    indices.length < totalRows,
  );
}

class PlannedSearchable {
  const PlannedSearchable(this.indices);
  final List<int> indices;
}

int searchableRowBlockBytes(IndexedRow pair, List<String> fieldnames) {
  final rowLine = formatDatasetRowLine(pair.values, fieldnames);
  final block = '${searchableRowLabel(pair)}\n$rowLine';
  return utf8ByteLength(block);
}

String formatSearchableDatasetRows(
  List<IndexedRow> pairs,
  List<String> fieldnames,
) {
  final lines = <String>[];
  for (final pair in pairs) {
    lines.add(searchableRowLabel(pair));
    lines.add(formatDatasetRowLine(pair.values, fieldnames));
  }
  return lines.join('\n');
}

List<Map<String, dynamic>> buildSearchableRowRepresentations(
  List<IndexedRow> pairs,
  List<String> fieldnames,
  int maxParts,
) {
  if (pairs.isEmpty || maxParts <= 0) {
    return [];
  }
  final blocks = <String>[];
  for (final pair in pairs) {
    final rowLine = formatDatasetRowLine(pair.values, fieldnames);
    blocks.add('${searchableRowLabel(pair)}\n$rowLine');
  }

  final parts = <String>[];
  var current = StringBuffer();
  for (final block in blocks) {
    final separator = current.isEmpty ? '' : '\n';
    final candidate = '${current.toString()}$separator$block';
    if (utf8ByteLength(candidate) > kMaxExtractorPartBytes && current.isNotEmpty) {
      parts.add(current.toString());
      current = StringBuffer(block);
      if (parts.length >= maxParts) {
        break;
      }
      continue;
    }
    if (utf8ByteLength(block) > kMaxExtractorPartBytes) {
      parts.add(truncateToUtf8Bytes(block, kMaxExtractorPartBytes));
      if (parts.length >= maxParts) {
        break;
      }
      current = StringBuffer();
      continue;
    }
    current.write(separator);
    current.write(block);
  }
  if (current.isNotEmpty && parts.length < maxParts) {
    parts.add(current.toString());
  }

  final reps = <Map<String, dynamic>>[
    for (var i = 0; i < parts.length; i++)
      {
        'kind': parts.length == 1 ? 'full' : 'chunk',
        'text': parts[i],
        if (parts.length > 1) 'part_index': i,
      },
  ];
  return boundedRepresentations(reps);
}

List<IndexedRow> fitSearchablePairsToBudget(
  List<IndexedRow> pairs,
  List<String> fieldnames,
  int byteBudget,
  int maxParts,
) {
  if (pairs.isEmpty || byteBudget <= 0 || maxParts <= 0) {
    return [];
  }
  final eligible = pairs
      .where(
        (pair) =>
            searchableRowBlockBytes(pair, fieldnames) <= kMaxExtractorPartBytes,
      )
      .toList();
  if (eligible.isEmpty) {
    return [];
  }
  final partBudget = byteBudget < maxParts * kMaxExtractorPartBytes
      ? byteBudget
      : maxParts * kMaxExtractorPartBytes;
  var low = 1;
  var high = eligible.length;
  var best = <IndexedRow>[];
  while (low <= high) {
    final mid = (low + high) ~/ 2;
    final positions = selectDistributedRowIndices(eligible.length, mid);
    final trialPairs = [for (final position in positions) eligible[position]];
    final text = formatSearchableDatasetRows(trialPairs, fieldnames);
    if (utf8ByteLength(text) <= partBudget) {
      best = trialPairs;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return best;
}

Set<int> persistedGlobalRowIndices(Iterable<IndexedRow> rows) {
  return {for (final row in rows) row.index};
}

Map<String, dynamic> buildDatasetSampleMetadata({
  required int totalRows,
  required int representedRows,
  required String samplingMode,
  required bool samplingTruncated,
  required List<int> sampledIndices,
}) {
  final meta = <String, dynamic>{
    'dataset_row_count': totalRows,
    'dataset_rows_represented': representedRows,
    'dataset_sampling_mode': samplingMode,
    'dataset_sampling_truncated': samplingTruncated,
  };
  if (sampledIndices.isNotEmpty &&
      sampledIndices.length <= kMaxSampledIndexList) {
    meta['sampled_row_indices'] = sampledIndices;
  }
  return meta;
}

List<Map<String, dynamic>> buildIndexedDatasetRepresentations({
  required List<String> fieldnames,
  required Map<String, String> columnTypes,
  required Map<String, dynamic> statsMeta,
  required List<String> statsLines,
  required int totalRows,
  required List<IndexedRow> indexedRows,
  required List<int> compactIndices,
  required List<int> searchableIndices,
}) {
  final rowsByIndex = {for (final row in indexedRows) row.index: row};
  final compactPairs = [
    for (final index in compactIndices)
      if (rowsByIndex.containsKey(index)) rowsByIndex[index]!,
  ];
  final searchablePairs = [
    for (final index in searchableIndices)
      if (rowsByIndex.containsKey(index)) rowsByIndex[index]!,
  ]..sort((a, b) => a.index.compareTo(b.index));

  final compactFit = fitCompactSamplePairs(compactPairs, fieldnames);
  final compactPairsFinal = compactFit.$1.pairs;
  final compactText = compactFit.$2;
  final compactTruncated = compactFit.$3;

  final structuralBytes = estimateStructuralBytes(
    fieldnames,
    columnTypes,
    statsLines,
  );
  final compactBytes = utf8ByteLength(compactText);
  final remainingBytes = (kMaxExtractorTotalBytes -
          structuralBytes -
          compactBytes)
      .clamp(0, kMaxExtractorTotalBytes);
  final remainingParts =
      (kMaxExtractorParts - kDatasetStructuralParts).clamp(0, kMaxExtractorParts);
  final searchableByteBudget = remainingBytes <
          remainingParts * kMaxExtractorPartBytes
      ? remainingBytes
      : remainingParts * kMaxExtractorPartBytes;
  final fittedSearchable = fitSearchablePairsToBudget(
    searchablePairs,
    fieldnames,
    searchableByteBudget,
    remainingParts,
  );
  final searchableReps = buildSearchableRowRepresentations(
    fittedSearchable,
    fieldnames,
    remainingParts,
  );

  final compactPersistedIndices = {for (final row in compactPairsFinal) row.index};

  final schemaCapped = capStructuralText(
    formatSchemaText(fieldnames, columnTypes),
  );
  final statsCapped = capStructuralText(statsLines.join('\n'));

  final structuralReps = <Map<String, dynamic>>[
    {
      'kind': 'schema',
      'text': schemaCapped.$1,
    },
    {
      'kind': 'sample',
      'text': compactText,
      'metadata': {
        'row_count_in_sample': compactPairsFinal.length,
        'compact_preview': true,
      },
    },
    {
      'kind': 'statistics',
      'text': statsCapped.$1,
      'metadata': {
        for (final entry in statsMeta.entries)
          if (entry.key != 'columns') entry.key: entry.value,
      },
    },
  ];

  final searchablePersistedIndices =
      persistedGlobalRowIndices(fittedSearchable);
  final representedIndices = [
    ...{...compactPersistedIndices, ...searchablePersistedIndices},
  ]..sort();
  final representedCount = representedIndices.length;
  final finalSamplingMode =
      representedCount == totalRows ? 'full' : 'distributed';
  final finalTruncated = representedCount < totalRows ||
      compactTruncated ||
      schemaCapped.$2 ||
      statsCapped.$2;

  final datasetMeta = buildDatasetSampleMetadata(
    totalRows: totalRows,
    representedRows: representedCount,
    samplingMode: finalSamplingMode,
    samplingTruncated: finalTruncated,
    sampledIndices: representedIndices,
  );

  final enrichedSearchable = [
    for (final rep in searchableReps)
      {
        ...rep,
        'metadata': {
          ...datasetMeta,
          ...(rep['metadata'] as Map<String, dynamic>? ?? {}),
        },
      },
  ];

  return boundedRepresentations([...structuralReps, ...enrichedSearchable]);
}
