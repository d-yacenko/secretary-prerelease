import 'dart:io';

import 'package:pdfrx/pdfrx.dart';

import 'dataset_sampling.dart';
import 'extraction_constants.dart';
import 'representation_builder.dart';

bool _pdfInitialized = false;

Future<void> _ensurePdfInitialized() async {
  if (_pdfInitialized) {
    return;
  }
  _tryConfigureBundledPdfium();
  try {
    await pdfrxFlutterInitialize(dismissPdfiumWasmWarnings: true);
  } catch (_) {
    await pdfrxInitialize();
  }
  _pdfInitialized = true;
}

void _tryConfigureBundledPdfium() {
  if (!Platform.isLinux || Pdfrx.pdfiumModulePath != null) {
    return;
  }
  final executableDir = File(Platform.resolvedExecutable).parent.path;
  final candidates = <String>[
    '$executableDir/lib/libpdfium.so',
    '${Directory.current.path}/build/linux/x64/debug/bundle/lib/libpdfium.so',
    '${Directory.current.path}/build/linux/x64/release/bundle/lib/libpdfium.so',
  ];
  for (final path in candidates) {
    if (File(path).existsSync()) {
      Pdfrx.pdfiumModulePath = path;
      return;
    }
  }
}

class PdfExtractionResult {
  const PdfExtractionResult({
    required this.representations,
    this.userMessage,
    this.extractionFailed = false,
    this.metadataOnly = false,
  });

  final List<Map<String, dynamic>> representations;
  final String? userMessage;
  final bool extractionFailed;
  final bool metadataOnly;
}

Future<PdfExtractionResult> extractPdfFile(File file) async {
  final size = await file.length();
  if (size > kMaxPdfInputBytes) {
    return const PdfExtractionResult(
      representations: [],
      metadataOnly: true,
      extractionFailed: true,
      userMessage: 'PDF слишком большой для локального извлечения текста',
    );
  }

  await _ensurePdfInitialized();
  PdfDocument? document;
  try {
    document = await PdfDocument.openFile(file.path);
    if (document.isEncrypted) {
      return const PdfExtractionResult(
        representations: [],
        metadataOnly: true,
        extractionFailed: true,
        userMessage: 'PDF зашифрован; извлечение текста недоступно',
      );
    }

    final pageCount = document.pages.length;
    final sourceTruncated = pageCount > kMaxPdfPages;
    final selectedPageIndices =
        selectDistributedRowIndices(pageCount, kMaxPdfPages);
    final parts = <String>[];
    for (final pageIndex in selectedPageIndices) {
      final rawText = await document.pages[pageIndex].loadText();
      final pageText = rawText?.fullText.trim() ?? '';
      if (pageText.isNotEmpty) {
        parts.add('[page ${pageIndex + 1}]\n$pageText');
      }
    }
    if (parts.isEmpty) {
      return const PdfExtractionResult(
        representations: [],
        metadataOnly: true,
        userMessage: 'В PDF нет извлекаемого текста',
      );
    }
    return PdfExtractionResult(
      representations: buildTextRepresentations(
        parts.join('\n\n'),
        metadata: {
          'page_count': pageCount,
          'page_truncated': sourceTruncated,
        },
      ),
    );
  } on PdfException catch (error) {
    if (error is PdfPasswordException) {
      return const PdfExtractionResult(
        representations: [],
        metadataOnly: true,
        extractionFailed: true,
        userMessage: 'PDF зашифрован; извлечение текста недоступно',
      );
    }
    return const PdfExtractionResult(
      representations: [],
      metadataOnly: true,
      extractionFailed: true,
      userMessage: 'Не удалось прочитать PDF',
    );
  } catch (_) {
    return const PdfExtractionResult(
      representations: [],
      metadataOnly: true,
      extractionFailed: true,
      userMessage: 'Не удалось прочитать PDF',
    );
  } finally {
    await document?.dispose();
  }
}
