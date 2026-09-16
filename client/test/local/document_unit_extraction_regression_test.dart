import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/local/extraction/dataset_sampling.dart';
import 'package:personal_secretary/local/extraction/extraction_constants.dart';
import 'package:personal_secretary/local/local_resource_extractor.dart';

import 'format_parity_fixtures.dart';
import 'pdf_test_support.dart';

void main() {
  late bool pdfAvailable;

  setUpAll(() async {
    pdfAvailable = await isPdfAvailableForTests();
  });

  late Directory tempDir;
  late LocalResourceExtractor extractor;

  setUp(() {
    tempDir = Directory.systemTemp.createTempSync('document-unit-regression-');
    extractor = LocalResourceExtractor();
  });

  tearDown(() {
    if (tempDir.existsSync()) {
      tempDir.deleteSync(recursive: true);
    }
  });

  test('odp extracts all slides with real numbering up to 130', () async {
    final file = File('${tempDir.path}/many.odp');
    await writeOdpPresentation(
      file,
      130,
      markers: {5: 'odp_marker_5', 54: 'odp_marker_54', 120: 'odp_marker_120'},
    );
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('[slide 5]'));
    expect(joined, contains('odp_marker_5'));
    expect(joined, contains('[slide 54]'));
    expect(joined, contains('odp_marker_54'));
    expect(joined, contains('[slide 120]'));
    expect(joined, contains('odp_marker_120'));
    final meta = result.representations.first['metadata'] as Map?;
    expect(meta?['slide_count'], 130);
    final hasSourceTruncated = result.representations.any(
      (rep) => (rep['metadata'] as Map?)?['truncated'] == true,
    );
    expect(hasSourceTruncated, isFalse);
  });

  test('pptx extracts all slides with real numbering up to 130', () async {
    final file = File('${tempDir.path}/many.pptx');
    await writePptxPresentation(
      file,
      130,
      markers: {5: 'pptx_marker_5', 54: 'pptx_marker_54', 120: 'pptx_marker_120'},
    );
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('[slide 5]'));
    expect(joined, contains('pptx_marker_5'));
    expect(joined, contains('[slide 54]'));
    expect(joined, contains('pptx_marker_54'));
    expect(joined, contains('[slide 120]'));
    expect(joined, contains('pptx_marker_120'));
    final meta = result.representations.first['metadata'] as Map?;
    expect(meta?['slide_count'], 130);
    final hasSourceTruncated = result.representations.any(
      (rep) => (rep['metadata'] as Map?)?['truncated'] == true,
    );
    expect(hasSourceTruncated, isFalse);
  });

  test('pdf extracts pages beyond old 50-page prefix limit', () async {
    if (!pdfAvailable) {
      fail('BLOCKED: PDFium is required but unavailable on this host');
    }
    final file = File('${tempDir.path}/many.pdf');
    await writeMergedMultiPagePdf(file, 120, marker: 'fpb_pdf_marker');
    final result = await extractor.extractFile(file);
    final joined = result.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('[page 1]'));
    expect(joined, contains('fpb_pdf_marker-0'));
    expect(joined, contains('[page 55]'));
    expect(joined, contains('fpb_pdf_marker-54'));
    expect(joined, contains('[page 120]'));
    expect(joined, contains('fpb_pdf_marker-119'));
    final meta = result.representations.first['metadata'] as Map?;
    expect(meta?['page_count'], 120);
    expect(meta?['page_truncated'], isNot(true));
  });

  test('pptx over safety cap uses distributed slides with real numbers', () async {
    const overCapSlides = kMaxPptxSlides + 5;
    final file = File('${tempDir.path}/huge.pptx');
    await writePptxPresentation(
      file,
      overCapSlides,
      markers: {
        1: 'pptx_cap_begin',
        overCapSlides ~/ 2: 'pptx_cap_middle',
        overCapSlides: 'pptx_cap_end',
      },
    );
    final first = await extractor.extractFile(file);
    final second = await extractor.extractFile(file);
    final joined = first.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('[slide 1]'));
    expect(joined, contains('pptx_cap_begin'));
    expect(joined, contains('[slide ${overCapSlides ~/ 2}]'));
    expect(joined, contains('pptx_cap_middle'));
    expect(joined, contains('[slide $overCapSlides]'));
    expect(joined, contains('pptx_cap_end'));
    final meta = first.representations.first['metadata'] as Map?;
    expect(meta?['slide_count'], overCapSlides);
    expect(
      first.representations.any(
        (rep) => (rep['metadata'] as Map?)?['truncated'] == true,
      ),
      isTrue,
    );
    expect(first.representations, second.representations);
  });

  test('odp over safety cap uses distributed slides with real numbers', () async {
    final file = File('${tempDir.path}/huge.odp');
    await writeOdpPresentation(
      file,
      kMaxOdpSlides + 20,
      markers: {
        1: 'odp_cap_begin',
        (kMaxOdpSlides + 20) ~/ 2: 'odp_cap_middle',
        kMaxOdpSlides + 20: 'odp_cap_end',
      },
    );
    final first = await extractor.extractFile(file);
    final second = await extractor.extractFile(file);
    final joined = first.representations.map((r) => r['text']).join('\n');
    expect(joined, contains('[slide 1]'));
    expect(joined, contains('odp_cap_begin'));
    expect(joined, contains('[slide ${(kMaxOdpSlides + 20) ~/ 2}]'));
    expect(joined, contains('odp_cap_middle'));
    expect(joined, contains('[slide ${kMaxOdpSlides + 20}]'));
    expect(joined, contains('odp_cap_end'));
    final meta = first.representations.first['metadata'] as Map?;
    expect(meta?['slide_count'], kMaxOdpSlides + 20);
    expect(
      first.representations.any(
        (rep) => (rep['metadata'] as Map?)?['truncated'] == true,
      ),
      isTrue,
    );
    expect(first.representations, second.representations);
  });

  test('distributed unit index selector is deterministic', () {
    final first = selectDistributedRowIndices(520, 500);
    final second = selectDistributedRowIndices(520, 500);
    expect(first, second);
    expect(first.first, 0);
    expect(first.last, 519);
    expect(first.length, 500);
  });
}
