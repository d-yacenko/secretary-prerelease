/// Positional spreadsheet column identity shared by CSV/ODS/XLSX extractors.
library;

String columnIndexToLetter(int index) {
  var dividend = index + 1;
  final buffer = StringBuffer();
  while (dividend > 0) {
    final modulo = (dividend - 1) % 26;
    buffer.writeCharCode('A'.codeUnitAt(0) + modulo);
    dividend = (dividend - modulo) ~/ 26;
  }
  return buffer.toString().split('').reversed.join();
}

List<String> positionalColumnKeys(int count) {
  return List.generate(count, columnIndexToLetter);
}

List<String> displayHeadersFromRaw(
  List<String> rawHeaders,
  List<String> columnKeys,
) {
  return [
    for (var i = 0; i < columnKeys.length; i++)
      i < rawHeaders.length && rawHeaders[i].trim().isNotEmpty
          ? rawHeaders[i].trim()
          : columnKeys[i],
  ];
}

String formatPositionalSchemaColumn(String columnKey, String displayHeader) {
  return '$columnKey=$displayHeader=string';
}

String formatSheetPositionalSchema(
  String sheetName,
  List<String> columnKeys,
  List<String> displayHeaders,
) {
  final parts = <String>[
    for (var i = 0; i < columnKeys.length; i++)
      formatPositionalSchemaColumn(columnKeys[i], displayHeaders[i]),
  ];
  return '$sheetName: ${parts.join(', ')}';
}

String formatPositionalSchemaLine(
  List<String> columnKeys,
  List<String> displayHeaders,
) {
  final parts = <String>[
    for (var i = 0; i < columnKeys.length; i++)
      '${columnKeys[i]}=${displayHeaders[i]}',
  ];
  return 'columns: ${parts.join(', ')}';
}

List<String> unionPositionalColumnKeys(Iterable<List<String>> perSheetKeys) {
  var maxLen = 0;
  for (final keys in perSheetKeys) {
    if (keys.length > maxLen) {
      maxLen = keys.length;
    }
  }
  return positionalColumnKeys(maxLen);
}

class PositionalSchema {
  const PositionalSchema({
    required this.columnKeys,
    required this.displayHeaders,
    required this.truncated,
  });

  final List<String> columnKeys;
  final List<String> displayHeaders;
  final bool truncated;
}

/// Derive bounded positional column identity from header plus observed row widths.
PositionalSchema resolvePositionalSchema({
  required List<String> rawHeader,
  required Iterable<int> observedRowWidths,
  required int maxColumns,
}) {
  var maxWidth = 0;
  var truncated = false;

  void consider(int width) {
    if (width > maxColumns) {
      truncated = true;
      if (maxColumns > maxWidth) {
        maxWidth = maxColumns;
      }
    } else if (width > maxWidth) {
      maxWidth = width;
    }
  }

  consider(rawHeader.length);
  for (final width in observedRowWidths) {
    consider(width);
  }

  final headerCells = [
    for (var i = 0; i < maxWidth; i++)
      i < rawHeader.length ? rawHeader[i] : '',
  ];
  final columnKeys = positionalColumnKeys(maxWidth);
  return PositionalSchema(
    columnKeys: columnKeys,
    displayHeaders: displayHeadersFromRaw(headerCells, columnKeys),
    truncated: truncated,
  );
}
