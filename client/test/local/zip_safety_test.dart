import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/local/extraction/archive_xml_utils.dart';
import 'package:personal_secretary/local/extraction/extraction_constants.dart';
import 'package:personal_secretary/local/extraction/zip_safety.dart';

void main() {
  test('rejects zip with too many entries', () {
    final archive = Archive();
    for (var i = 0; i <= kMaxOoxmlZipEntries; i++) {
      archive.addFile(ArchiveFile.string('entry_$i.txt', 'x'));
    }
    expect(
      () => validateZipArchive(archive),
      throwsA(isA<UnsafeZipError>()),
    );
  });

  test('rejects zip with excessive uncompressed size', () {
    final archive = Archive();
    final chunk = 'x' * (1024 * 1024);
    for (var i = 0; i < 33; i++) {
      archive.addFile(ArchiveFile.string('big_$i.txt', chunk));
    }
    expect(
      () => validateZipArchive(archive),
      throwsA(isA<UnsafeZipError>()),
    );
  });

  test('rejects excessive compression ratio with UnsafeZipError', () {
    final archive = Archive();
    archive.addFile(
      ArchiveFile('tiny.txt', 10 * 1024 * 1024, [1, 2, 3]),
    );
    expect(
      () => validateZipArchive(archive),
      throwsA(
        allOf(
          isA<UnsafeZipError>(),
          predicate<UnsafeZipError>(
            (error) => error.message.contains('compression ratio'),
          ),
        ),
      ),
    );
  });

  test('malformed zip fails safely on read', () async {
    final tempDir = Directory.systemTemp.createTempSync('zip-malformed-');
    try {
      final file = File('${tempDir.path}/bad.zip');
      await file.writeAsBytes([0x50, 0x4b, 0x03, 0x04, 0xff, 0xff]);
      await expectLater(
        readZipArchive(file),
        throwsA(isA<Object>()),
      );
    } finally {
      if (tempDir.existsSync()) {
        tempDir.deleteSync(recursive: true);
      }
    }
  });

  test('malformed xml fails safely on parse', () {
    expect(
      () => parseSafeXml(utf8.encode('<root><unclosed>')),
      throwsA(isA<Object>()),
    );
  });
}
