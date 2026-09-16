import 'dart:io';

import 'package:archive/archive.dart';
import 'package:xml/xml.dart';

import 'archive_xml_utils.dart';
import 'dataset_sampling.dart';
import 'extraction_constants.dart';
import 'representation_builder.dart';

const _pptxNs = 'http://schemas.openxmlformats.org/drawingml/2006/main';

Future<List<Map<String, dynamic>>> extractPptxFile(File file) async {
  final archive = await readZipArchive(file);
  final slidePaths = archive.files
      .map((entry) => entry.name)
      .where(
        (name) => name.startsWith('ppt/slides/slide') && name.endsWith('.xml'),
      )
      .toList()
    ..sort((a, b) => _pptxSlideIndex(a).compareTo(_pptxSlideIndex(b)));
  final totalSlides = slidePaths.length;
  final sourceTruncated = totalSlides > kMaxPptxSlides;
  final selectedIndices =
      selectDistributedRowIndices(totalSlides, kMaxPptxSlides);
  final lines = <String>[];
  for (final index in selectedIndices) {
    final slidePath = slidePaths[index];
    final slideNumber = _pptxSlideIndex(slidePath);
    final root =
        parseSafeXml(readArchiveEntry(archive, slidePath)).rootElement;
    final texts = root
        .descendants
        .whereType<XmlElement>()
        .where(
          (element) =>
              element.name.local == 't' &&
              element.name.namespaceUri == _pptxNs,
        )
        .map((node) => node.innerText.trim())
        .where((text) => text.isNotEmpty)
        .toList();
    lines.add('[slide $slideNumber]');
    lines.addAll(texts);
  }
  final text = lines.join('\n');
  if (text.trim().isEmpty) {
    throw const FormatException('no_extractable_text');
  }
  return buildTextRepresentations(
    text,
    metadata: {'slide_count': totalSlides, 'truncated': sourceTruncated},
  );
}

int _pptxSlideIndex(String path) {
  final match = RegExp(r'slide(\d+)\.xml$').firstMatch(path);
  return match == null ? 0 : int.parse(match.group(1)!);
}
