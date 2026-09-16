import 'dart:io';

import 'package:archive/archive.dart';
import 'package:xml/xml.dart';

import 'archive_xml_utils.dart';
import 'extraction_constants.dart';
import 'representation_builder.dart';

const _mainNs = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main';
const _relNs =
    'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const _xlsxStructuralParts = 3;

class _ParsedSheet {
  const _ParsedSheet(this.rows, this.truncated, this.maxUsedCols);

  final List<(int, Map<String, String>)> rows;
  final bool truncated;
  final int maxUsedCols;
}

Future<List<Map<String, dynamic>>> extractXlsxFile(File file) async {
  final archive = await readZipArchive(file);
  final sharedStrings = _readXlsxSharedStrings(archive);
  final sheetNames = _readXlsxSheetNames(archive);
  var truncated = sheetNames.length > kMaxXlsxSheets;
  final selectedSheets = sheetNames.take(kMaxXlsxSheets).toList();

  final schemaLines = <String>['schema'];
  final sampleLines = <String>['sample'];
  final statsLines = <String>['statistics'];
  final searchableLines = <String>[];

  for (final sheetName in selectedSheets) {
    final parsed = _readXlsxSheetParsed(archive, sheetName, sharedStrings);
    truncated = truncated || parsed.truncated;
    final parsedRows = parsed.rows;
    final maxUsedCols = parsed.maxUsedCols;
    if (parsedRows.isEmpty) {
      schemaLines.add('$sheetName: (empty)');
      statsLines.add('$sheetName: rows=0, columns=0');
      continue;
    }

    final headerIndex = _xlsxHeaderRowIndex(parsedRows);
    final headerRow = parsedRows[headerIndex];
    final dataRows = parsedRows.sublist(headerIndex + 1);

    schemaLines.add(
      '$sheetName: ${_formatXlsxSparseColumns(headerRow.$2)}',
    );
    sampleLines.add('[$sheetName]');
    sampleLines.add(_formatXlsxSparseRow(headerRow.$1, headerRow.$2));
    for (final row in dataRows.take(5)) {
      sampleLines.add(_formatXlsxSparseRow(row.$1, row.$2));
    }
    statsLines.add(
      '$sheetName: rows=${dataRows.length}, columns=$maxUsedCols',
    );
    for (final row in parsedRows) {
      searchableLines.add(
        _formatXlsxSearchableRow(sheetName, row.$1, row.$2),
      );
    }
  }

  final schemaCapped = capStructuralText(schemaLines.join('\n'));
  final sampleCapped = capStructuralText(sampleLines.join('\n'));
  final statsCapped = capStructuralText(statsLines.join('\n'));
  truncated = truncated || schemaCapped.$2 || sampleCapped.$2 || statsCapped.$2;
  final truncationMeta = truncationMetadata(truncated);

  final structuralReps = <Map<String, dynamic>>[
    {
      'kind': 'schema',
      'text': schemaCapped.$1,
      'metadata': {
        'sheet_count': selectedSheets.length,
        ...truncationMeta,
      },
    },
    {
      'kind': 'sample',
      'text': sampleCapped.$1,
      'metadata': {
        'sheet_count': selectedSheets.length,
        ...truncationMeta,
      },
    },
    {
      'kind': 'statistics',
      'text': statsCapped.$1,
      'metadata': {
        'sheet_count': selectedSheets.length,
        ...truncationMeta,
      },
    },
  ];

  final remainingParts =
      (kMaxExtractorParts - _xlsxStructuralParts).clamp(0, kMaxExtractorParts);
  final searchableReps = buildBoundedTextRepresentations(
    searchableLines.join('\n'),
    remainingParts,
    metadata: {
      'sheet_count': selectedSheets.length,
      ...truncationMeta,
    },
  );

  return boundedRepresentations([...structuralReps, ...searchableReps]);
}

List<String> _readXlsxSharedStrings(Archive archive) {
  if (!archive.files.any((file) => file.name == 'xl/sharedStrings.xml')) {
    return [];
  }
  final root = parseSafeXml(readArchiveEntry(archive, 'xl/sharedStrings.xml'))
      .rootElement;
  return [
    for (final item in _elementsByLocal(root, 'si', _mainNs))
      item
          .findAllElements('t')
          .map((node) => node.innerText)
          .join(),
  ];
}

List<String> _readXlsxSheetNames(Archive archive) {
  final root =
      parseSafeXml(readArchiveEntry(archive, 'xl/workbook.xml')).rootElement;
  return [
    for (final sheet in _elementsByLocal(root, 'sheet', _mainNs))
      sheet.getAttribute('name') ?? '',
  ].where((name) => name.isNotEmpty).toList();
}

_ParsedSheet _readXlsxSheetParsed(
  Archive archive,
  String sheetName,
  List<String> sharedStrings,
) {
  final workbook =
      parseSafeXml(readArchiveEntry(archive, 'xl/workbook.xml')).rootElement;
  String? relId;
  for (final sheet in _elementsByLocal(workbook, 'sheet', _mainNs)) {
    if (sheet.getAttribute('name') == sheetName) {
      relId = sheet.getAttribute('id', namespace: _relNs) ??
          sheet.getAttribute('r:id');
      break;
    }
  }
  if (relId == null) {
    return const _ParsedSheet(<(int, Map<String, String>)>[], false, 0);
  }

  final relsRoot = parseSafeXml(
    readArchiveEntry(archive, 'xl/_rels/workbook.xml.rels'),
  ).rootElement;
  String? target;
  for (final rel in relsRoot.childElements) {
    if (rel.getAttribute('Id') == relId) {
      target = rel.getAttribute('Target');
      break;
    }
  }
  if (target == null) {
    return const _ParsedSheet(<(int, Map<String, String>)>[], false, 0);
  }
  var sheetPath =
      target.startsWith('worksheets/') ? target : 'worksheets/$target';
  if (!sheetPath.startsWith('xl/')) {
    sheetPath = 'xl/$sheetPath';
  }
  if (!archive.files.any((file) => file.name == sheetPath)) {
    return const _ParsedSheet(<(int, Map<String, String>)>[], false, 0);
  }

  final root =
      parseSafeXml(readArchiveEntry(archive, sheetPath)).rootElement;
  final parsedRows = <(int, Map<String, String>)>[];
  var truncated = false;
  var maxUsedCols = 0;
  for (final rowElem in _elementsByLocal(root, 'row', _mainNs)) {
    if (parsedRows.length >= kMaxXlsxRowsPerSheet) {
      truncated = true;
      break;
    }
    final rowNum = int.tryParse(rowElem.getAttribute('r') ?? '') ??
        parsedRows.length + 1;
    final cells = <String, String>{};
    var rowTruncated = false;
    for (final cell in _elementsByLocal(rowElem, 'c', _mainNs)) {
      final ref = cell.getAttribute('r');
      if (ref == null) {
        continue;
      }
      final parsedRef = _parseXlsxCellRef(ref);
      if (parsedRef == null) {
        continue;
      }
      final colLetter = parsedRef.$1;
      final colIndex = _colLetterToIndex(colLetter);
      if (colIndex >= kMaxXlsxColumns) {
        rowTruncated = true;
        truncated = true;
        break;
      }
      final value = _xlsxCellValue(cell, sharedStrings).trim();
      if (value.isNotEmpty) {
        cells[colLetter] = value;
        maxUsedCols = maxUsedCols > colIndex + 1 ? maxUsedCols : colIndex + 1;
      }
    }
    if (rowTruncated) {
      break;
    }
    if (cells.isNotEmpty) {
      parsedRows.add((rowNum, cells));
    }
  }
  return _ParsedSheet(
    parsedRows,
    truncated,
    maxUsedCols > kMaxXlsxColumns ? kMaxXlsxColumns : maxUsedCols,
  );
}

int _xlsxHeaderRowIndex(List<(int, Map<String, String>)> parsedRows) {
  for (var index = 0; index < parsedRows.length; index++) {
    if (parsedRows[index].$2.length >= 2) {
      return index;
    }
  }
  return 0;
}

(String, int)? _parseXlsxCellRef(String ref) {
  final match = RegExp(r'^([A-Za-z]+)(\d+)$').firstMatch(ref);
  if (match == null) {
    return null;
  }
  return (match.group(1)!.toUpperCase(), int.parse(match.group(2)!));
}

int _colLetterToIndex(String letters) {
  var index = 0;
  for (final code in letters.toUpperCase().codeUnits) {
    index = index * 26 + (code - 65 + 1);
  }
  return index - 1;
}

String _formatXlsxSparseColumns(Map<String, String> cells) {
  final ordered = cells.entries.toList()
    ..sort((a, b) => _colLetterToIndex(a.key).compareTo(_colLetterToIndex(b.key)));
  return ordered.map((entry) => '${entry.key}=${entry.value}').join(', ');
}

String _formatXlsxSparseRow(int rowNum, Map<String, String> cells) {
  final ordered = cells.entries.toList()
    ..sort((a, b) => _colLetterToIndex(a.key).compareTo(_colLetterToIndex(b.key)));
  final parts = ordered.map((entry) => '${entry.key}=${entry.value}').join(' | ');
  return 'row=$rowNum $parts';
}

String _formatXlsxSearchableRow(
  String sheetName,
  int rowNum,
  Map<String, String> cells,
) {
  final ordered = cells.entries.toList()
    ..sort((a, b) => _colLetterToIndex(a.key).compareTo(_colLetterToIndex(b.key)));
  final parts = ordered.map((entry) => '${entry.key}=${entry.value}').join(' | ');
  return '[sheet=$sheetName row=$rowNum]\n$parts';
}

String _xlsxCellValue(XmlElement cell, List<String> sharedStrings) {
  final cellType = cell.getAttribute('t');
  final valueNode = _firstChildByLocal(cell, 'v', _mainNs);
  if (valueNode == null) {
    final inline = _firstChildByLocal(cell, 'is', _mainNs);
    if (inline != null) {
      return inline
          .findAllElements('t')
          .map((node) => node.innerText)
          .join();
    }
    return '';
  }
  final valueText = valueNode.innerText;
  if (cellType == 's') {
    final index = int.tryParse(valueText);
    if (index != null && index >= 0 && index < sharedStrings.length) {
      return sharedStrings[index];
    }
  }
  return valueText;
}

Iterable<XmlElement> _elementsByLocal(
  XmlElement root,
  String local,
  String namespace,
) {
  return root.descendants.whereType<XmlElement>().where(
        (element) =>
            element.name.local == local &&
            element.name.namespaceUri == namespace,
      );
}

XmlElement? _firstChildByLocal(XmlElement parent, String local, String namespace) {
  for (final child in parent.childElements) {
    if (child.name.local == local && child.name.namespaceUri == namespace) {
      return child;
    }
  }
  return null;
}
