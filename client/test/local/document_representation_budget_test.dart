import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/local/client_content_revision.dart';
import 'package:personal_secretary/local/extraction/extraction_constants.dart';
import 'package:personal_secretary/local/extraction/representation_builder.dart';
import 'package:personal_secretary/local/local_resource_extractor.dart';

import 'format_parity_fixtures.dart';
import 'pdf_test_support.dart';

const _beginMarker = 'BEGIN_MARKER';
const _middleMarker = 'MIDDLE_MARKER';
const _tailMarker = 'TAIL_MARKER';

String _oldStyleChunkCountText(int targetOldChunks) {
  // Old 800-char chunks with 100 overlap need roughly 700 * (n-1) + 800 chars.
  final minChars = (targetOldChunks - 1) * (kChunkSize - kChunkOverlap) + kChunkSize + 1;
  final middlePos = minChars ~/ 2;
  final tailPos = minChars - 1200;
  final buffer = StringBuffer();
  buffer.write('$_beginMarker\n');
  buffer.write('x' * (middlePos - buffer.length - _middleMarker.length - 1));
  buffer.write('$_middleMarker\n');
  buffer.write('y' * (tailPos - buffer.length - _tailMarker.length - 1));
  buffer.write('$_tailMarker\n');
  buffer.write('z' * (minChars - buffer.length));
  final text = buffer.toString();
  expect(chunkText(text, kChunkSize, kChunkOverlap).length, greaterThan(64));
  expect(utf8ByteLength(text), lessThan(kMaxExtractorTotalBytes));
  return text;
}

List<Map<String, dynamic>> _chunkReps(String text, {Map<String, dynamic>? metadata}) {
  return buildTextRepresentations(text, metadata: metadata);
}

String _joinedText(List<Map<String, dynamic>> reps) {
  return reps.map((rep) => rep['text'] as String).join('\n');
}

void _assertByteBounds(List<Map<String, dynamic>> reps) {
  var total = 0;
  for (final rep in reps) {
    final bytes = utf8ByteLength(rep['text'] as String);
    expect(bytes, lessThanOrEqualTo(kMaxExtractorPartBytes));
    total += bytes;
  }
  expect(reps.length, lessThanOrEqualTo(kMaxExtractorParts));
  expect(total, lessThanOrEqualTo(kMaxExtractorTotalBytes));
}

void main() {
  late bool pdfAvailable;
  late Directory tempDir;
  late LocalResourceExtractor extractor;

  setUpAll(() async {
    pdfAvailable = await isPdfAvailableForTests();
  });

  setUp(() {
    tempDir = Directory.systemTemp.createTempSync('doc-rep-budget-');
    extractor = LocalResourceExtractor();
  });

  tearDown(() {
    if (tempDir.existsSync()) {
      tempDir.deleteSync(recursive: true);
    }
  });

  test('A text above old 64x800 threshold but below 256KiB keeps all markers', () {
    final reps = _chunkReps(_oldStyleChunkCountText(80));
    final joined = _joinedText(reps);
    expect(joined, contains(_beginMarker));
    expect(joined, contains(_middleMarker));
    expect(joined, contains(_tailMarker));
    _assertByteBounds(reps);
    expect(
      reps.any((rep) => (rep['metadata'] as Map?)?['truncated'] == true),
      isFalse,
    );
  });

  test('B ODP realistic presentation preserves beginning middle and tail slides', () async {
    const slideCount = 125;
    final file = File('${tempDir.path}/budget.odp');
    await writeOdpPresentation(
      file,
      slideCount,
      markers: {
        5: 'odp_budget_marker_5',
        54: 'odp_budget_marker_54',
        115: 'odp_budget_marker_115',
      },
      bodyPaddingChars: 420,
    );
    final result = await extractor.extractFile(file);
    final joined = _joinedText(result.representations);
    expect(joined, contains('[slide 5]'));
    expect(joined, contains('odp_budget_marker_5'));
    expect(joined, contains('[slide 54]'));
    expect(joined, contains('odp_budget_marker_54'));
    expect(joined, contains('[slide 115]'));
    expect(joined, contains('odp_budget_marker_115'));
    final meta = result.representations.first['metadata'] as Map?;
    expect(meta?['slide_count'], slideCount);
    expect(
      result.representations.any(
        (rep) => (rep['metadata'] as Map?)?['truncated'] == true,
      ),
      isFalse,
    );
    _assertByteBounds(result.representations);
  });

  test('C PPTX realistic presentation preserves beginning middle and tail slides', () async {
    const slideCount = 125;
    final file = File('${tempDir.path}/budget.pptx');
    await writePptxPresentation(
      file,
      slideCount,
      markers: {
        5: 'pptx_budget_marker_5',
        54: 'pptx_budget_marker_54',
        115: 'pptx_budget_marker_115',
      },
      bodyPaddingChars: 420,
    );
    final result = await extractor.extractFile(file);
    final joined = _joinedText(result.representations);
    expect(joined, contains('[slide 5]'));
    expect(joined, contains('pptx_budget_marker_5'));
    expect(joined, contains('[slide 54]'));
    expect(joined, contains('pptx_budget_marker_54'));
    expect(joined, contains('[slide 115]'));
    expect(joined, contains('pptx_budget_marker_115'));
    _assertByteBounds(result.representations);
  });

  test('D PDF beyond old chunk threshold keeps beginning middle and tail markers', () async {
    if (!pdfAvailable) {
      fail('BLOCKED: PDFium is required but unavailable on this host');
    }
    final file = File('${tempDir.path}/budget.pdf');
    await writeMergedMultiPagePdf(
      file,
      90,
      marker: 'pdf_budget_marker',
      bodyPaddingChars: 420,
    );
    final result = await extractor.extractFile(file);
    final joined = _joinedText(result.representations);
    expect(joined, contains('[page 1]'));
    expect(joined, contains('pdf_budget_marker-0'));
    expect(joined, contains('[page 45]'));
    expect(joined, contains('pdf_budget_marker-44'));
    expect(joined, contains('[page 90]'));
    expect(joined, contains('pdf_budget_marker-89'));
    final meta = result.representations.first['metadata'] as Map?;
    expect(meta?['page_count'], 90);
    expect(meta?['page_truncated'], isNot(true));
    _assertByteBounds(result.representations);
  });

  test('E overflow above 256KiB uses distributed coverage with truthful truncation', () {
    final segment = 'segment-${'w' * 700}\n';
    final text = StringBuffer();
    while (utf8ByteLength(text.toString()) < kMaxExtractorTotalBytes + 32 * 1024) {
      text.write(segment);
    }
    text.write('OVERFLOW_TAIL_MARKER');
    final source = text.toString();
    final first = _chunkReps(source);
    final second = _chunkReps(source);
    final joined = _joinedText(first);
    expect(joined, contains('segment-'));
    expect(joined.length, lessThan(source.length));
    expect(
      first.any((rep) => (rep['metadata'] as Map?)?['truncated'] == true),
      isTrue,
    );
    _assertByteBounds(first);
    expect(first, second);
    final lateWindow = source.substring(source.length - 4096);
    expect(lateWindow, contains('OVERFLOW_TAIL_MARKER'));
    expect(joined, contains('OVERFLOW_TAIL_MARKER'));
  });

  test('F Cyrillic text respects UTF-8 byte bounds', () {
    final reps = _chunkReps('й' * 50000);
    _assertByteBounds(reps);
    final joined = _joinedText(reps);
    expect(joined, contains('й'));
  });

  test('packTextIntoRepresentationParts keeps source markers intact', () {
    final text = '[slide 5]\nmarker body\n${'a' * 20000}\n[slide 6]\nnext';
    final parts = packTextIntoRepresentationParts(text);
    final joined = parts.join('');
    expect(joined, contains('[slide 5]'));
    expect(joined, contains('[slide 6]'));
    for (final part in parts) {
      expect(utf8ByteLength(part), lessThanOrEqualTo(kMaxExtractorPartBytes));
    }
  });
}
