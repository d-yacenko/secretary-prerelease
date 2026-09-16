import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:xml/xml.dart';

import '../client_content_revision.dart';
import 'archive_xml_utils.dart';
import 'dataset_sampling.dart';
import 'extraction_constants.dart';
import 'representation_builder.dart';
import 'spreadsheet_columns.dart';

const _officeNs = 'urn:oasis:names:tc:opendocument:xmlns:office:1.0';
const _textNs = 'urn:oasis:names:tc:opendocument:xmlns:text:1.0';
const _tableNs = 'urn:oasis:names:tc:opendocument:xmlns:table:1.0';
const _drawNs = 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0';

class _OdsSheetData {
  const _OdsSheetData({
    required this.name,
    required this.columnKeys,
    required this.displayHeaders,
    required this.rows,
    required this.truncated,
  });

  final String name;
  final List<String> columnKeys;
  final List<String> displayHeaders;
  final List<IndexedRow> rows;
  final bool truncated;
}

class _ParsedOdsPhysicalRow {
  const _ParsedOdsPhysicalRow({
    required this.sourceRowNumber,
    required this.cells,
  });

  final int sourceRowNumber;
  final List<String> cells;
}

Future<List<Map<String, dynamic>>> extractOdtFile(File file) async {
  final root = await _readOdfContentXml(file);
  final body = _firstByLocal(root, 'body', 'office');
  if (body == null) {
    throw const FormatException('missing office:body');
  }
  final officeText = _firstChildByLocal(body, 'text', 'office');
  if (officeText == null) {
    throw const FormatException('missing office:text');
  }

  final lines = <String>[];
  var truncated = false;
  for (final child in officeText.childElements) {
    if (_isTag(child, 'h', 'text') || _isTag(child, 'p', 'text')) {
      final text = elementText(child);
      if (text.isNotEmpty) {
        lines.add(text);
      }
    } else if (_isTag(child, 'list', 'text')) {
      lines.addAll(_odtListItems(child));
    } else if (_isTag(child, 'table', 'table')) {
      final table = _odtTableRows(child);
      truncated = truncated || table.$2;
      lines.addAll(table.$1);
    }
  }

  final text = lines.join('\n');
  if (text.trim().isEmpty) {
    throw const FormatException('no_extractable_text');
  }
  return buildTextRepresentations(
    text,
    metadata: truncated ? {'truncated': true} : null,
  );
}

Future<List<Map<String, dynamic>>> extractOdpFile(File file) async {
  final root = await _readOdfContentXml(file);
  final body = _firstByLocal(root, 'body', 'office');
  if (body == null) {
    throw const FormatException('missing office:body');
  }
  final presentation = _firstChildByLocal(body, 'presentation', 'office');
  if (presentation == null) {
    throw const FormatException('missing office:presentation');
  }

  final pages = presentation.childElements
      .where((child) => _isTag(child, 'page', 'draw'))
      .toList();
  final totalSlides = pages.length;
  final sourceTruncated = totalSlides > kMaxOdpSlides;
  final selectedIndices =
      selectDistributedRowIndices(totalSlides, kMaxOdpSlides);
  var truncated = sourceTruncated;
  final lines = <String>[];
  for (final index in selectedIndices) {
    final slideNumber = index + 1;
    lines.add('[slide $slideNumber]');
    final pageText = _odpPageText(pages[index]);
    truncated = truncated || pageText.$2;
    lines.addAll(pageText.$1);
  }
  final text = lines.join('\n');
  if (text.trim().isEmpty) {
    throw const FormatException('no_extractable_text');
  }
  return buildTextRepresentations(
    text,
    metadata: {
      'slide_count': totalSlides,
      'truncated': truncated,
    },
  );
}

Future<List<Map<String, dynamic>>> extractOdsFile(File file) async {
  final root = await _readOdfContentXml(file);
  final body = _firstByLocal(root, 'body', 'office');
  if (body == null) {
    throw const FormatException('missing office:body');
  }
  final spreadsheet = _firstChildByLocal(body, 'spreadsheet', 'office');
  if (spreadsheet == null) {
    throw const FormatException('missing office:spreadsheet');
  }

  final tables = spreadsheet.childElements
      .where((child) => _isTag(child, 'table', 'table'))
      .toList();
  var truncated = tables.length > kMaxOdfSheets;
  final selectedTables = tables.take(kMaxOdfSheets).toList();

  final sheets = <_OdsSheetData>[];
  for (final table in selectedTables) {
    final sheetName = table.getAttribute('name', namespace: _tableNs) ?? 'Sheet';
    final parsed = _odsTableRows(table, sheetName);
    truncated = truncated || parsed.$2;
    sheets.add(
      _OdsSheetData(
        name: sheetName,
        columnKeys: parsed.$3,
        displayHeaders: parsed.$4,
        rows: parsed.$1,
        truncated: parsed.$2,
      ),
    );
  }

  final totalRows = sheets.fold<int>(0, (sum, sheet) => sum + sheet.rows.length);
  if (totalRows == 0) {
    throw const FormatException('no_extractable_text');
  }

  final schemaLines = <String>['schema'];
  final sampleLines = <String>['sample'];
  final statsLines = <String>['statistics'];
  for (final sheet in sheets) {
    if (sheet.columnKeys.isEmpty) {
      schemaLines.add('${sheet.name}: (empty)');
      statsLines.add('${sheet.name}: rows=0, columns=0');
      continue;
    }
    schemaLines.add(
      formatSheetPositionalSchema(
        sheet.name,
        sheet.columnKeys,
        sheet.displayHeaders,
      ),
    );
    if (sheet.rows.isNotEmpty) {
      sampleLines.add('[${sheet.name}]');
      for (var i = 0; i < sheet.rows.length && i < 5; i++) {
        sampleLines.add(
          _formatOdsRow(sheet.name, sheet.rows[i], sheet.columnKeys),
        );
      }
    }
    statsLines.add(
      '${sheet.name}: rows=${sheet.rows.length}, columns=${sheet.columnKeys.length}',
    );
  }

  final fieldnames = unionPositionalColumnKeys(
    sheets.map((sheet) => sheet.columnKeys),
  );
  final columnTypes = {for (final name in fieldnames) name: 'string'};
  final statsMeta = <String, dynamic>{
    'row_count': totalRows,
    'rows_sampled': totalRows,
    'column_count': fieldnames.length,
    'stats_truncated': truncated,
    'columns': <String, dynamic>{},
  };
  final sourceTruncationMeta = truncationMetadata(truncated);

  if (totalRows <= kCompactSampleMaxRows) {
    final searchableLines = <String>[];
    for (final sheet in sheets) {
      for (final row in sheet.rows) {
        searchableLines.add(
          '${searchableRowLabel(row)}\n${_formatOdsValues(row.values, sheet.columnKeys)}',
        );
      }
    }
    final schemaCapped = capStructuralText(schemaLines.join('\n'));
    final sampleCapped = capStructuralText(sampleLines.join('\n'));
    final statsCapped = capStructuralText(statsLines.join('\n'));
    final structuralTruncated =
        truncated || schemaCapped.$2 || sampleCapped.$2 || statsCapped.$2;
    final searchableReps = buildBoundedTextRepresentations(
      searchableLines.join('\n'),
      kMaxExtractorParts - kDatasetStructuralParts,
    );
    return boundedRepresentations([
      {
        'kind': 'schema',
        'text': schemaCapped.$1,
        'metadata': {
          ...statsMeta,
          ...truncationMetadata(structuralTruncated),
        },
      },
      {
        'kind': 'sample',
        'text': sampleCapped.$1,
        'metadata': truncationMetadata(structuralTruncated),
      },
      {
        'kind': 'statistics',
        'text': statsCapped.$1,
        'metadata': {
          ...statsMeta,
          ...truncationMetadata(structuralTruncated),
        },
      },
      ...searchableReps,
    ]);
  }

  final globalRows = <IndexedRow>[];
  var globalIndex = 0;
  for (final sheet in sheets) {
    for (final row in sheet.rows) {
      globalRows.add(
        IndexedRow(
          index: globalIndex,
          sheetName: sheet.name,
          sourceRowNumber: row.sourceRowNumber,
          values: {
            for (final key in fieldnames) key: row.values[key] ?? '',
          },
        ),
      );
      globalIndex += 1;
    }
  }

  final estimateRow = globalRows.first.values;
  final structuralBytes = estimateStructuralBytes(
    fieldnames,
    columnTypes,
    statsLines,
  );
  final compactIndices = compactPreviewIndices(totalRows);
  final planned = planSearchableIndices(
    totalRows: totalRows,
    fieldnames: fieldnames,
    estimateRow: estimateRow,
    structuralBytes: structuralBytes,
    compactSampleBytes: utf8ByteLength(
      formatSampleText([estimateRow], fieldnames),
    ),
  );
  final reps = buildIndexedDatasetRepresentations(
    fieldnames: fieldnames,
    columnTypes: columnTypes,
    statsMeta: statsMeta,
    statsLines: statsLines,
    totalRows: totalRows,
    indexedRows: globalRows,
    compactIndices: compactIndices,
    searchableIndices: planned.$1.indices,
  );
  if (sourceTruncationMeta.isEmpty) {
    return reps;
  }
  return [
    for (final rep in reps)
      {
        ...rep,
        'metadata': {
          ...(rep['metadata'] as Map<String, dynamic>? ?? {}),
          ...sourceTruncationMeta,
        },
      },
  ];
}

Future<XmlElement> _readOdfContentXml(File file) async {
  final archive = await readZipArchive(file);
  if (!archive.files.any((entry) => entry.name == 'content.xml')) {
    throw const FormatException('missing content.xml');
  }
  return parseSafeXml(readArchiveEntry(archive, 'content.xml')).rootElement;
}

(List<IndexedRow>, bool, List<String>, List<String>) _odsTableRows(
  XmlElement table,
  String sheetName,
) {
  final parsedRows = <_ParsedOdsPhysicalRow>[];
  var truncated = false;
  var logicalRowNumber = 0;
  for (final rowElem in _childrenByLocal(table, 'table-row', 'table')) {
    if (parsedRows.length >= kMaxOdfRowsPerSheet) {
      truncated = true;
      break;
    }
    final values = <String>[];
    for (final cell in _childrenByLocal(rowElem, 'table-cell', 'table')) {
      final cellRepeat = _boundedRepeat(
        cell.getAttribute('number-columns-repeated', namespace: _tableNs),
      );
      final cellText = odfStoredCellValue(cell, officeNs: _officeNs);
      for (var i = 0; i < cellRepeat.$1; i++) {
        if (values.length >= kMaxOdfColumns) {
          truncated = true;
          break;
        }
        values.add(cellText);
      }
      truncated = truncated || cellRepeat.$2;
      if (truncated && values.length >= kMaxOdfColumns) {
        break;
      }
    }
    final rowRepeat = _rowRepeatBounds(
      rowElem.getAttribute('number-rows-repeated', namespace: _tableNs),
    );
    truncated = truncated || rowRepeat.$3;
    final expansionStart = logicalRowNumber + 1;
    for (var i = 0; i < rowRepeat.$2; i++) {
      if (parsedRows.length >= kMaxOdfRowsPerSheet) {
        truncated = true;
        break;
      }
      parsedRows.add(
        _ParsedOdsPhysicalRow(
          sourceRowNumber: expansionStart + i,
          cells: List<String>.from(values),
        ),
      );
    }
    logicalRowNumber += rowRepeat.$1;
  }

  if (parsedRows.isEmpty) {
    return ([], truncated, [], []);
  }

  final headerRow = parsedRows.first;
  final schema = resolvePositionalSchema(
    rawHeader: headerRow.cells,
    observedRowWidths: parsedRows.map((row) => row.cells.length),
    maxColumns: kMaxOdfColumns,
  );
  truncated = truncated || schema.truncated;
  final columnKeys = schema.columnKeys;
  final displayHeaders = schema.displayHeaders;

  final rows = <IndexedRow>[];
  var dataRowIndex = 0;
  for (var rowOffset = 1; rowOffset < parsedRows.length; rowOffset++) {
    final physical = parsedRows[rowOffset];
    final values = <String, String>{};
    for (var col = 0; col < columnKeys.length; col++) {
      values[columnKeys[col]] =
          col < physical.cells.length ? physical.cells[col] : '';
    }
    if (values.values.any((value) => value.isNotEmpty)) {
      rows.add(
        IndexedRow(
          index: dataRowIndex,
          sheetName: sheetName,
          sourceRowNumber: physical.sourceRowNumber,
          values: values,
        ),
      );
      dataRowIndex += 1;
    }
  }
  return (rows, truncated, columnKeys, displayHeaders);
}

int _declaredRepeat(String? raw, {int defaultValue = 1}) {
  if (raw == null || raw.isEmpty) {
    return defaultValue;
  }
  final value = int.tryParse(raw) ?? defaultValue;
  if (value < 1) {
    return 1;
  }
  return value;
}

(int declared, int expansion, bool truncated) _rowRepeatBounds(String? raw) {
  final declared = _declaredRepeat(raw);
  if (declared > kMaxOdfRepeatExpansion) {
    return (declared, kMaxOdfRepeatExpansion, true);
  }
  return (declared, declared, false);
}

(int, bool) _boundedRepeat(String? raw, {int defaultValue = 1}) {
  final declared = _declaredRepeat(raw, defaultValue: defaultValue);
  if (declared > kMaxOdfRepeatExpansion) {
    return (kMaxOdfRepeatExpansion, true);
  }
  return (declared, false);
}

List<String> _odtListItems(XmlElement listElem) {
  final items = <String>[];
  for (final item in listElem.descendants.whereType<XmlElement>()) {
    if (_isTag(item, 'list-item', 'text')) {
      final text = elementText(item);
      if (text.isNotEmpty) {
        items.add('- $text');
      }
    }
  }
  return items;
}

(List<String>, bool) _odtTableRows(XmlElement table) {
  final lines = <String>[];
  var truncated = false;
  for (final rowElem in _childrenByLocal(table, 'table-row', 'table')) {
    final rowCells = <String>[];
    for (final cell in _childrenByLocal(rowElem, 'table-cell', 'table')) {
      final repeat = _boundedRepeat(
        cell.getAttribute('number-columns-repeated', namespace: _tableNs),
      );
      final cellText = odfStoredCellValue(cell, officeNs: _officeNs);
      truncated = truncated || repeat.$2;
      for (var i = 0; i < repeat.$1; i++) {
        if (rowCells.length >= kMaxOdfColumns) {
          truncated = true;
          break;
        }
        rowCells.add(cellText);
      }
    }
    final rowRepeat = _boundedRepeat(
      rowElem.getAttribute('number-rows-repeated', namespace: _tableNs),
    );
    truncated = truncated || rowRepeat.$2;
    for (var i = 0; i < rowRepeat.$1; i++) {
      if (rowCells.any((cell) => cell.isNotEmpty)) {
        lines.add('| ${rowCells.join(' | ')} |');
      }
    }
  }
  return (lines, truncated);
}

(List<String>, bool) _odpPageText(XmlElement page) {
  final lines = <String>[];
  var truncated = false;
  for (final element in page.descendants.whereType<XmlElement>()) {
    if (_isTag(element, 'p', 'text')) {
      final text = elementText(element);
      if (text.isNotEmpty) {
        lines.add(text);
      }
    } else if (_isTag(element, 'list', 'text')) {
      lines.addAll(_odtListItems(element));
    } else if (_isTag(element, 'table', 'table')) {
      final table = _odtTableRows(element);
      truncated = truncated || table.$2;
      lines.addAll(table.$1);
    }
  }
  return (lines, truncated);
}

String _formatOdsRow(
  String sheetName,
  IndexedRow row,
  List<String> columnKeys,
) {
  return '${searchableRowLabel(row)} '
      '${columnKeys.map((key) => '$key=${row.values[key] ?? ''}').join(' | ')}';
}

String _formatOdsValues(Map<String, String> values, List<String> columnKeys) {
  return columnKeys.map((key) => values[key] ?? '').join(',');
}

bool _isTag(XmlElement element, String local, String nsKey) {
  final namespace = switch (nsKey) {
    'office' => _officeNs,
    'text' => _textNs,
    'table' => _tableNs,
    'draw' => _drawNs,
    _ => '',
  };
  return element.name.local == local && element.name.namespaceUri == namespace;
}

XmlElement? _firstByLocal(XmlElement root, String local, String nsKey) {
  for (final element in root.descendants.whereType<XmlElement>()) {
    if (_isTag(element, local, nsKey)) {
      return element;
    }
  }
  return null;
}

XmlElement? _firstChildByLocal(XmlElement parent, String local, String nsKey) {
  for (final child in parent.childElements) {
    if (_isTag(child, local, nsKey)) {
      return child;
    }
  }
  return null;
}

Iterable<XmlElement> _childrenByLocal(
  XmlElement parent,
  String local,
  String nsKey,
) {
  return parent.childElements.where((child) => _isTag(child, local, nsKey));
}
