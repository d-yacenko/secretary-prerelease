import 'dart:convert';

import 'package:crypto/crypto.dart';

String normalizeClientSourcePath(String sourcePath) {
  var text = sourcePath.replaceAll('\\', '/').trim();
  while (text.contains('//')) {
    text = text.replaceAll('//', '/');
  }
  return text;
}

String computeClientContentRevision({
  required String clientSourceLocator,
  required int size,
  required String modifiedAt,
  String? contentHash,
}) {
  final normalized = normalizeClientSourcePath(clientSourceLocator);
  final parts = <String, String>{
    'modified_at': modifiedAt,
    'size': size.toString(),
    'source_path': normalized,
  };
  if (contentHash != null) {
    parts['content_hash'] = contentHash;
  }
  final keys = parts.keys.toList()..sort();
  final payload = keys.map((key) => '$key=${parts[key]}').join('|');
  return sha256.convert(utf8.encode(payload)).toString();
}

int utf8ByteLength(String text) => utf8.encode(text).length;

String truncateToUtf8Bytes(String text, int maxBytes) {
  if (maxBytes <= 0) {
    return '';
  }
  final bytes = utf8.encode(text);
  if (bytes.length <= maxBytes) {
    return text;
  }
  var end = maxBytes;
  while (end > 0) {
    while (end > 0 && (bytes[end - 1] & 0xC0) == 0x80) {
      end -= 1;
    }
    final candidate = utf8.decode(bytes.sublist(0, end), allowMalformed: true);
    final candidateBytes = utf8.encode(candidate);
    if (candidateBytes.length <= maxBytes) {
      return candidate;
    }
    end -= 1;
  }
  return '';
}
