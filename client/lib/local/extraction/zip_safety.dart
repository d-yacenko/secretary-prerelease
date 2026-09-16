import 'package:archive/archive.dart';

import 'extraction_constants.dart';

class UnsafeZipError implements Exception {
  UnsafeZipError(this.message);
  final String message;

  @override
  String toString() => 'UnsafeZipError: $message';
}

void validateZipArchive(Archive archive) {
  final entries = archive.files.where((file) => file.isFile).toList();
  if (entries.length > kMaxOoxmlZipEntries) {
    throw UnsafeZipError('zip entry count exceeds limit');
  }
  var totalUncompressed = 0;
  for (final file in entries) {
    final uncompressed = file.size;
    final compressed = _compressedSize(file);
    if (uncompressed / compressed > kMaxOoxmlCompressionRatio) {
      throw UnsafeZipError('zip compression ratio exceeds limit');
    }
    totalUncompressed += uncompressed;
    if (totalUncompressed > kMaxOoxmlUncompressedBytes) {
      throw UnsafeZipError('zip uncompressed size exceeds limit');
    }
  }
}

int _compressedSize(ArchiveFile file) {
  final raw = file.rawContent;
  if (raw != null) {
    final length = raw.getStream().length;
    if (length > 0) {
      return length;
    }
  }
  return file.size > 0 ? file.size : 1;
}
