import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/local/client_content_revision.dart';
import 'package:personal_secretary/local/local_resource_extractor.dart';

import 'duckdb_test_support.dart';
import 'format_parity_fixtures.dart';
import 'pdf_test_support.dart';

void main() {
  late bool pdfAvailable;

  setUpAll(() async {
    configureDuckDbForTests();
    pdfAvailable = await isPdfAvailableForTests();
  });

  late Directory tempDir;
  late LocalResourceExtractor extractor;

  setUp(() {
    tempDir = Directory.systemTemp.createTempSync('extractor-test-');
    extractor = LocalResourceExtractor();
  });

  tearDown(() {
    if (tempDir.existsSync()) {
      tempDir.deleteSync(recursive: true);
    }
  });

  File writeFile(String name, String content) {
    final file = File('${tempDir.path}/$name');
    file.writeAsStringSync(content);
    return file;
  }

  test('small txt produces full representation', () async {
    final file = writeFile('small.txt', 'short text');
    final result = await extractor.extractFile(file);
    expect(result.metadataOnly, isFalse);
    expect(result.representations.single['kind'], 'full');
  });

  test('large txt produces bounded chunks', () async {
    final file = writeFile('large.txt', 'word ' * 5000);
    final result = await extractor.extractFile(file);
    expect(result.metadataOnly, isFalse);
    expect(result.representations.every((r) => r['kind'] == 'chunk'), isTrue);
    expect(result.representations.length <= kMaxExtractorParts, isTrue);
  });

  test('md treated as text', () async {
    final file = writeFile('note.md', '# Title\n\nBody');
    final result = await extractor.extractFile(file);
    expect(result.suggestedKind, 'document');
    expect(result.representations.isNotEmpty, isTrue);
  });

  test('csv produces schema sample statistics', () async {
    final file = writeFile('data.csv', 'a,b\n1,2\n3,4');
    final result = await extractor.extractFile(file);
    final kinds = result.representations.map((r) => r['kind']).toSet();
    expect(kinds.contains('schema'), isTrue);
    expect(kinds.contains('sample'), isTrue);
    expect(kinds.contains('statistics'), isTrue);
  });

  test('legacy doc remains metadata-only', () async {
    final file = writeFile('legacy.doc', 'legacy');
    final result = await extractor.extractFile(file);
    expect(result.metadataOnly, isTrue);
    expect(result.representations, isEmpty);
  });

  test('revision stable for unchanged file', () async {
    final file = writeFile('stable.txt', 'same');
    final first = await extractor.extractFile(file);
    final second = await extractor.extractFile(file);
    expect(first.contentRevision, second.contentRevision);
  });

  test('changed content changes revision', () async {
    final file = writeFile('change.txt', 'one');
    final first = await extractor.extractFile(file);
    file.writeAsStringSync('two');
    final second = await extractor.extractFile(file);
    expect(first.contentRevision, isNot(second.contentRevision));
  });

  test('revision matches backend algorithm', () async {
    final file = writeFile('align.txt', 'payload');
    final result = await extractor.extractFile(file);
    final expected = computeClientContentRevision(
      clientSourceLocator: file.path,
      size: result.size,
      modifiedAt: result.modifiedAt,
      contentHash: result.contentHash,
    );
    expect(result.contentRevision, expected);
  });

  test('utf8 byte bounds per part', () async {
    final file = writeFile('bytes.txt', 'й' * 20000);
    final result = await extractor.extractFile(file);
    for (final rep in result.representations) {
      expect(utf8ByteLength(rep['text'] as String), lessThanOrEqualTo(kMaxExtractorPartBytes));
    }
  });

  test('aggregate utf8 byte bound', () async {
    final file = writeFile('aggregate.txt', 'word ' * 10000);
    final result = await extractor.extractFile(file);
    var total = 0;
    for (final rep in result.representations) {
      total += utf8ByteLength(rep['text'] as String);
    }
    expect(total, lessThanOrEqualTo(kMaxExtractorTotalBytes));
  });

  test('whitespace-heavy text stays bounded', () async {
    final file = writeFile('spaces.txt', ' ' * 50000);
    final result = await extractor.extractFile(file);
    expect(result.representations.length <= kMaxExtractorParts, isTrue);
    for (final rep in result.representations) {
      expect(utf8ByteLength(rep['text'] as String), lessThanOrEqualTo(kMaxExtractorPartBytes));
    }
  });

  test('quoted csv comma parsed', () async {
    final file = writeFile('quoted.csv', 'name,value\n"Doe, John",42\n"Smith",17');
    final result = await extractor.extractFile(file);
    final stats = result.representations.firstWhere((r) => r['kind'] == 'statistics');
    expect(stats['metadata']?['row_count'], 2);
    final sample = result.representations.firstWhere((r) => r['kind'] == 'sample');
    expect(sample['text'], contains('Doe, John'));
  });

  test('escaped quote csv parsed', () async {
    final file = writeFile('escape.csv', 'name,note\n"John","said ""hi"""');
    final result = await extractor.extractFile(file);
    final sample = result.representations.firstWhere((r) => r['kind'] == 'sample');
    expect(sample['text'], contains('said'));
  });

  test('empty csv cell preserved', () async {
    final file = writeFile('empty.csv', 'a,b\n,2');
    final result = await extractor.extractFile(file);
    final sample = result.representations.firstWhere((r) => r['kind'] == 'sample');
    expect(sample['text'], isNotEmpty);
  });

  test('utf8 csv values', () async {
    final file = writeFile('utf8.csv', 'name,value\nМосква,42');
    final result = await extractor.extractFile(file);
    final sample = result.representations.firstWhere((r) => r['kind'] == 'sample');
    expect(sample['text'], contains('Москва'));
  });

  test('large csv uses distributed coverage not prefix-only', () async {
    final file = File('${tempDir.path}/huge.csv');
    await writeLargeCsv(file, 20000);
    final first = await extractor.extractFile(file);
    final second = await extractor.extractFile(file);
    final searchable = first.representations
        .where((rep) => rep['kind'] == 'chunk' || rep['kind'] == 'full')
        .map((rep) => rep['text'] as String)
        .join('\n');
    expect(searchable, contains('row19999'));
    expect(searchable, contains('Doe, John'));
    final metaRep = first.representations.firstWhere(
      (rep) => rep['metadata']?['dataset_sampling_mode'] != null,
      orElse: () => first.representations.last,
    );
    expect(metaRep['metadata']?['dataset_sampling_mode'], 'distributed');
    expect(first.representations, second.representations);
  });

  test('large csv preserves quoted multiline across chunk boundary', () async {
    final file = File('${tempDir.path}/multiline.csv');
    await writeLargeCsvWithMultilineQuoted(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('multiline_marker_'));
    expect(joined, contains('end,marker'));
  });

  test('small csv full mode is not marked truncated', () async {
    final file = writeFile('small.csv', 'a,b\n1,2\n3,4\n5,6');
    final result = await extractor.extractFile(file);
    final metaRep = result.representations.firstWhere(
      (rep) => rep['metadata']?['dataset_sampling_mode'] != null,
    );
    expect(metaRep['metadata']?['dataset_sampling_mode'], 'full');
    expect(metaRep['metadata']?['dataset_sampling_truncated'], isFalse);
  });

  test('pdf text extraction', () async {
    if (!pdfAvailable) {
      fail('BLOCKED: PDFium is required but unavailable on this host');
    }
    final file = File('${tempDir.path}/sample.pdf');
    await writeMinimalPdf(file, text: 'pdf distinctive phrase delta');
    final result = await extractor.extractFile(file);
    expect(result.metadataOnly, isFalse);
    expect(
      result.representations.map((r) => r['text']).join('\n'),
      contains('pdf distinctive phrase delta'),
    );
  });

  test('blank pdf is metadata-only', () async {
    if (!pdfAvailable) {
      fail('BLOCKED: PDFium is required but unavailable on this host');
    }
    final file = File('${tempDir.path}/blank.pdf');
    await writeBlankPdf(file);
    final result = await extractor.extractFile(file);
    expect(result.metadataOnly, isTrue);
    expect(result.userMessage, anyOf(
      contains('нет извлекаемого текста'),
      contains('Не удалось прочитать PDF'),
    ));
  });

  test('docx extracts paragraph and table', () async {
    final file = File('${tempDir.path}/sample.docx');
    await writeMinimalDocx(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('docx paragraph beta'));
    expect(joined, contains('cell1'));
  });

  test('xlsx extracts values', () async {
    final file = File('${tempDir.path}/sample.xlsx');
    await writeMinimalXlsx(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('xlsx_value'));
  });

  test('pptx extracts slide text', () async {
    final file = File('${tempDir.path}/sample.pptx');
    await writeMinimalPptx(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('slide distinctive gamma'));
  });

  test('pptx slide order is numeric not lexicographic', () async {
    final file = File('${tempDir.path}/ordered.pptx');
    await writeOrderedPptx(file, 12);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    final slide2 = joined.indexOf('slide_text_2');
    final slide10 = joined.indexOf('slide_text_10');
    expect(slide2, greaterThan(-1));
    expect(slide10, greaterThan(slide2));
  });

  test('odt extracts text', () async {
    final file = File('${tempDir.path}/sample.odt');
    await writeMinimalOdt(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('odt distinctive alpha'));
    expect(joined, contains('cell_a'));
  });

  test('ods extracts values', () async {
    final file = File('${tempDir.path}/sample.ods');
    await writeMinimalOds(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('ods_value'));
  });

  test('odp extracts slide text', () async {
    final file = File('${tempDir.path}/sample.odp');
    await writeMinimalOdp(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('odp distinctive slide'));
  });

  test('odt repeated columns are bounded with truncation metadata', () async {
    final file = File('${tempDir.path}/repeat.odt');
    await writeOdtWithRepeatedColumns(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('repeat_marker_odt'));
    final truncated = result.representations.any(
      (rep) => (rep['metadata'] as Map?)?['truncated'] == true,
    );
    expect(truncated, isTrue);
  });

  test('ods repeated rows expand stored values', () async {
    final file = File('${tempDir.path}/repeat.ods');
    await writeOdsWithRepeatedRows(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('repeat_marker_ods'));
    final statsRep = result.representations.firstWhere((r) => r['kind'] == 'statistics');
    expect((statsRep['metadata'] as Map?)?['stats_truncated'], isTrue);
  });

  test('odp repeated table rows are bounded with truncation metadata', () async {
    final file = File('${tempDir.path}/repeat.odp');
    await writeOdpWithRepeatedTable(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('repeat_marker_odp'));
    final truncated = result.representations.any(
      (rep) => (rep['metadata'] as Map?)?['truncated'] == true,
    );
    expect(truncated, isTrue);
  });

  test('large multi-sheet ods preserves sheet coverage and row counts', () async {
    final file = File('${tempDir.path}/multi.ods');
    await writeLargeMultiSheetOds(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('ods_sheet_beta_marker'));
    expect(joined, contains('Alpha'));
    expect(joined, contains('Beta'));
    final statsRep = result.representations.firstWhere((r) => r['kind'] == 'statistics');
    expect((statsRep['metadata'] as Map?)?['row_count'], 100);
    final kinds = result.representations.map((r) => r['kind']).toSet();
    expect(kinds.contains('schema'), isTrue);
    expect(kinds.contains('sample'), isTrue);
    expect(kinds.contains('statistics'), isTrue);
  });

  test('parquet small full coverage', () async {
    requireDuckDbForTests(isDuckDbAvailable);
    final file = File('${tempDir.path}/sample.parquet');
    await writeMinimalParquet(file);
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('parquet_marker_alpha'));
    expect(result.metadataOnly, isFalse);
  });

  test('parquet large distributed deterministic', () async {
    requireDuckDbForTests(isDuckDbAvailable);
    final file = File('${tempDir.path}/large.parquet');
    await writeLargeParquet(file, 10000, markerRow: 9999);
    final first = await extractor.extractFile(file);
    final second = await extractor.extractFile(file);
    final joined = first.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('format_parity_marker_row'));
    expect(joined, contains('row_0'));
    expect(first.representations, second.representations);
  });

  test('malformed docx fails safely', () async {
    final file = File('${tempDir.path}/bad.docx');
    await writeMalformedZip(file);
    final result = await extractor.extractFile(file);
    expect(result.metadataOnly, isTrue);
    expect(result.extractionFailed, isTrue);
  });

  test('pdf over old 50-page prefix limit still extracts tail pages', () async {
    if (!pdfAvailable) {
      fail('BLOCKED: PDFium is required but unavailable on this host');
    }
    final file = File('${tempDir.path}/many.pdf');
    await writeMergedMultiPagePdf(file, 55, marker: 'bounded_page');
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('[page 1]'));
    expect(joined, contains('bounded_page-0'));
    expect(joined, contains('[page 55]'));
    expect(joined, contains('bounded_page-54'));
    final meta = result.representations.first['metadata'] as Map?;
    expect(meta?['page_count'], 55);
    expect(meta?['page_truncated'], isNot(true));
  });

  test('oversized pdf is metadata-only without reading file', () async {
    final file = File('${tempDir.path}/huge.pdf');
    await file.writeAsBytes(List.filled(kMaxPdfInputBytes + 1, 0));
    final result = await extractor.extractFile(file);
    expect(result.metadataOnly, isTrue);
    expect(result.extractionFailed, isTrue);
    expect(result.userMessage, contains('слишком большой'));
  });
}
