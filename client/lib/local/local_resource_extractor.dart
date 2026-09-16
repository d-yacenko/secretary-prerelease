import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:path/path.dart' as p;

import 'client_content_revision.dart';
import 'extraction/csv_extractor.dart';
import 'extraction/docx_extractor.dart';
import 'extraction/extraction_constants.dart';
import 'extraction/odf_extractors.dart';
import 'extraction/parquet_extractor.dart';
import 'extraction/pdf_extractor.dart';
import 'extraction/pptx_extractor.dart';
import 'extraction/text_extractor.dart';
import 'extraction/xlsx_extractor.dart';

export 'extraction/extraction_constants.dart';

class LocalExtractionResult {
  const LocalExtractionResult({
    required this.sourcePath,
    required this.filename,
    required this.extension,
    required this.size,
    required this.modifiedAt,
    required this.contentRevision,
    required this.suggestedKind,
    required this.metadataOnly,
    required this.representations,
    this.contentHash,
    this.userMessage,
    this.extractionFailed = false,
  });

  final String sourcePath;
  final String filename;
  final String extension;
  final int size;
  final String modifiedAt;
  final String contentRevision;
  final String suggestedKind;
  final bool metadataOnly;
  final List<Map<String, dynamic>> representations;
  final String? contentHash;
  final String? userMessage;
  final bool extractionFailed;
}

class LocalResourceExtractor {
  Future<LocalExtractionResult> extractFile(File file) async {
    final path = file.path;
    final stat = await file.stat();
    final filename = p.basename(path);
    final extension = p.extension(filename).toLowerCase();
    final modifiedAt = stat.modified.toUtc().toIso8601String();
    final size = stat.size;

    String? contentHash;
    if (size <= kCheapHashMaxBytes) {
      final digest = sha256.convert(await file.readAsBytes());
      contentHash = digest.toString();
    }

    final revision = computeClientContentRevision(
      clientSourceLocator: path,
      size: size,
      modifiedAt: modifiedAt,
      contentHash: contentHash,
    );

    if (kLegacyMetadataOnlySuffixes.contains(extension)) {
      return LocalExtractionResult(
        sourcePath: path,
        filename: filename,
        extension: extension,
        size: size,
        modifiedAt: modifiedAt,
        contentRevision: revision,
        suggestedKind: 'file',
        metadataOnly: true,
        representations: [],
        contentHash: contentHash,
        userMessage: 'Формат пока индексируется только по метаданным',
      );
    }

    if (!kSupportedModernSuffixes.contains(extension)) {
      return LocalExtractionResult(
        sourcePath: path,
        filename: filename,
        extension: extension,
        size: size,
        modifiedAt: modifiedAt,
        contentRevision: revision,
        suggestedKind: 'file',
        metadataOnly: true,
        representations: [],
        contentHash: contentHash,
        userMessage: 'Формат пока индексируется только по метаданным',
      );
    }

    try {
      final extracted = await _extractSupported(file, extension);
      return LocalExtractionResult(
        sourcePath: path,
        filename: filename,
        extension: extension,
        size: size,
        modifiedAt: modifiedAt,
        contentRevision: revision,
        suggestedKind: _suggestedKind(extension),
        metadataOnly: extracted.metadataOnly,
        representations: extracted.representations,
        contentHash: contentHash,
        userMessage: extracted.userMessage,
        extractionFailed: extracted.extractionFailed,
      );
    } catch (_) {
      return LocalExtractionResult(
        sourcePath: path,
        filename: filename,
        extension: extension,
        size: size,
        modifiedAt: modifiedAt,
        contentRevision: revision,
        suggestedKind: _suggestedKind(extension),
        metadataOnly: true,
        representations: [],
        contentHash: contentHash,
        userMessage: 'Не удалось прочитать файл',
        extractionFailed: true,
      );
    }
  }

  Future<_ExtractedPayload> _extractSupported(
    File file,
    String extension,
  ) async {
    switch (extension) {
      case '.txt':
      case '.md':
        return _ExtractedPayload(
          representations: extractTextFile(file),
        );
      case '.csv':
        return _ExtractedPayload(
          representations: await extractCsvFile(file),
        );
      case '.pdf':
        final pdf = await extractPdfFile(file);
        return _ExtractedPayload(
          representations: pdf.representations,
          metadataOnly: pdf.metadataOnly,
          userMessage: pdf.userMessage,
          extractionFailed: pdf.extractionFailed,
        );
      case '.docx':
        return _ExtractedPayload(
          representations: await extractDocxFile(file),
        );
      case '.xlsx':
        return _ExtractedPayload(
          representations: await extractXlsxFile(file),
        );
      case '.pptx':
        return _ExtractedPayload(
          representations: await extractPptxFile(file),
        );
      case '.odt':
        return _ExtractedPayload(
          representations: await extractOdtFile(file),
        );
      case '.ods':
        return _ExtractedPayload(
          representations: await extractOdsFile(file),
        );
      case '.odp':
        return _ExtractedPayload(
          representations: await extractOdpFile(file),
        );
      case '.parquet':
        return _ExtractedPayload(
          representations: await extractParquetFile(file),
        );
      default:
        throw UnsupportedError('unsupported extension: $extension');
    }
  }

  String _suggestedKind(String extension) {
    if (extension == '.csv' || extension == '.parquet') {
      return 'dataset';
    }
    return 'document';
  }
}

class _ExtractedPayload {
  const _ExtractedPayload({
    required this.representations,
    this.metadataOnly = false,
    this.userMessage,
    this.extractionFailed = false,
  });

  final List<Map<String, dynamic>> representations;
  final bool metadataOnly;
  final String? userMessage;
  final bool extractionFailed;
}
