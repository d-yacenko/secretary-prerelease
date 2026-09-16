import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/local/extraction/extraction_constants.dart';
import 'package:personal_secretary/local/local_resource_extractor.dart';

import 'format_parity_fixtures.dart';

void main() {
  late Directory tempDir;
  late LocalResourceExtractor extractor;

  setUp(() {
    tempDir = Directory.systemTemp.createTempSync('spreadsheet-regression-');
    extractor = LocalResourceExtractor();
  });

  tearDown(() {
    if (tempDir.existsSync()) {
      tempDir.deleteSync(recursive: true);
    }
  });

  test('ods bounded repeat advances logical row past declared gap', () async {
    final file = File('${tempDir.path}/large_repeat.ods');
    await writeOdsLargeRepeatWithMarker(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('[sheet=SheetA row=102]'));
    expect(joined, contains('after_repeat_marker'));
    final hasTruncated = result.representations.any(
      (rep) => (rep['metadata'] as Map?)?['truncated'] == true,
    );
    expect(hasTruncated, isTrue);
  });

  test('ods source row numbers survive blank and repeated rows', () async {
    final file = File('${tempDir.path}/source_rows.ods');
    await writeOdsSourceRowIdentity(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('[sheet=SheetA row=3]'));
    expect(joined, contains('after_blank'));
    expect(joined, contains('[sheet=SheetA row=4]'));
    expect(joined, contains('[sheet=SheetA row=5]'));
    expect(joined, contains('repeat_marker'));
    expect(joined, contains('[sheet=SheetB row=2]'));
    expect(joined, contains('sheetb_row2_value'));
    expect(joined, isNot(contains('[sheet=SheetA row=2]')));
  });

  test('ods data rows wider than header preserve extra positional columns', () async {
    final file = File('${tempDir.path}/wide_data.ods');
    await writeOdsWiderDataThanHeader(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('C=C=string'));
    expect(joined, contains('hidden_marker'));
    expect(joined, contains('Alice,42,hidden_marker'));
  });

  test('ods positional columns preserve empty and duplicate headers', () async {
    final file = File('${tempDir.path}/positional.ods');
    await writeOdsPositionalColumns(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('A=Alice'));
    expect(joined, contains('B=mid'));
    expect(joined, contains('C=42'));
    expect(joined, contains('A=a'));
    expect(joined, contains('B=b'));
    expect(joined, contains('C=1'));
    expect(joined, contains('A=a2'));
    expect(joined, contains('B=b2'));
    expect(joined, contains('C=2'));
    expect(joined, isNot(contains('Amount=mid')));
  });

  test('ods compact sample does not duplicate sheet marker', () async {
    final file = File('${tempDir.path}/sample.ods');
    await writeMinimalOds(file);
    final result = await extractor.extractFile(file);
    final sample = result.representations
        .firstWhere((rep) => rep['kind'] == 'sample')['text'] as String;
    expect(RegExp(r'\[Sheet1\]').allMatches(sample).length, 1);
  });

  test('xlsx row cap surfaces truncated metadata', () async {
    final file = File('${tempDir.path}/many_rows.xlsx');
    await writeXlsxWithRowCount(file, kMaxXlsxRowsPerSheet + 5);
    final result = await extractor.extractFile(file);
    final hasTruncated = result.representations.any(
      (rep) => (rep['metadata'] as Map?)?['truncated'] == true,
    );
    expect(hasTruncated, isTrue);
  });

  test('xlsx column cap surfaces truncated metadata', () async {
    final file = File('${tempDir.path}/wide.xlsx');
    await writeXlsxWithWideColumn(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, isNot(contains('beyond_column_cap')));
    final hasTruncated = result.representations.any(
      (rep) => (rep['metadata'] as Map?)?['truncated'] == true,
    );
    expect(hasTruncated, isTrue);
  });

  test('xlsx sheet cap surfaces truncated metadata', () async {
    final file = File('${tempDir.path}/many_sheets.xlsx');
    await writeXlsxWithSheetCount(file, kMaxXlsxSheets + 1);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, isNot(contains('sheet_17')));
    final hasTruncated = result.representations.any(
      (rep) => (rep['metadata'] as Map?)?['truncated'] == true,
    );
    expect(hasTruncated, isTrue);
  });

  test('small xlsx is not marked truncated', () async {
    final file = File('${tempDir.path}/small.xlsx');
    await writeMinimalXlsx(file);
    final result = await extractor.extractFile(file);
    final hasTruncated = result.representations.any(
      (rep) => (rep['metadata'] as Map?)?['truncated'] == true,
    );
    expect(hasTruncated, isFalse);
  });

  test('csv positional columns preserve empty and duplicate headers', () async {
    final file = File('${tempDir.path}/positional.csv');
    file.writeAsStringSync('Name,,Amount\nAlice,mid,42\nName,Name,1\na,b,c\n');
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('columns: A=Name, B=B, C=Amount'));
    expect(joined, contains('Alice,mid,42'));
    expect(joined, contains('a,b,c'));
    expect(joined, isNot(contains('Amount=mid')));
  });

  test('small csv data row wider than header preserves extra columns', () async {
    final file = File('${tempDir.path}/wide_small.csv');
    file.writeAsStringSync('Name,Amount\nAlice,42,extra_marker\n');
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('columns: A=Name, B=Amount, C=C'));
    expect(joined, contains('extra_marker'));
    expect(joined, contains('Alice,42,extra_marker'));
  });

  test('large csv data row wider than header preserves extra columns', () async {
    final file = File('${tempDir.path}/wide_large.csv');
    await writeLargeCsvWiderThanHeader(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('columns: A=name, B=value, C=C'));
    expect(joined, contains('extra_marker'));
  });

  test('csv wider than column cap surfaces truncated metadata', () async {
    final file = File('${tempDir.path}/wide_cap.csv');
    final header = List.generate(kMaxCsvColumns, (i) => 'h$i').join(',');
    final data = List.generate(kMaxCsvColumns + 1, (i) => 'v$i').join(',');
    file.writeAsStringSync('$header\n$data\n');
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, isNot(contains('v$kMaxCsvColumns')));
    final hasTruncated = result.representations.any(
      (rep) => (rep['metadata'] as Map?)?['truncated'] == true,
    );
    expect(hasTruncated, isTrue);
  });
}
