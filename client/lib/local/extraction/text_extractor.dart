import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'extraction_constants.dart';
import 'representation_builder.dart';

List<Map<String, dynamic>> extractTextFile(File file) {
  final bytes = _readBoundedBytes(file);
  final text = utf8.decode(bytes, allowMalformed: true);
  return buildTextRepresentations(text);
}

List<int> _readBoundedBytes(File file) {
  final size = file.lengthSync();
  if (size <= kMaxExtractedTextBytes) {
    return file.readAsBytesSync();
  }
  final raf = file.openSync();
  try {
    final windows = <int>{0};
    if (size > kReadWindowBytes) {
      windows.add(max(0, (size ~/ 2) - (kReadWindowBytes ~/ 2)));
      windows.add(max(0, size - kReadWindowBytes));
    }
    final buffer = <int>[];
    for (final offset in windows) {
      raf.setPositionSync(offset);
      final toRead = min(kReadWindowBytes, size - offset);
      buffer.addAll(raf.readSync(toRead));
      if (buffer.length >= kMaxExtractedTextBytes) {
        break;
      }
    }
    return buffer.take(kMaxExtractedTextBytes).toList();
  } finally {
    raf.closeSync();
  }
}
