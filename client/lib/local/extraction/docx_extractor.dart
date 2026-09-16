import 'dart:io';

import 'package:xml/xml.dart';

import 'archive_xml_utils.dart';
import 'representation_builder.dart';

const _docxNs = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';

Future<List<Map<String, dynamic>>> extractDocxFile(File file) async {
  final archive = await readZipArchive(file);
  final xmlBytes = readArchiveEntry(archive, 'word/document.xml');
  final root = parseSafeXml(xmlBytes).rootElement;
  final paragraphs = <String>[];

  for (final paragraph in root.findAllElements('p', namespace: _docxNs)) {
    final texts = paragraph
        .findAllElements('t', namespace: _docxNs)
        .map((node) => node.innerText)
        .join();
    final line = texts.trim();
    if (line.isNotEmpty) {
      paragraphs.add(line);
    }
  }

  for (final table in root.findAllElements('tbl', namespace: _docxNs)) {
    for (final row in table.findAllElements('tr', namespace: _docxNs)) {
      final cellTexts = <String>[];
      for (final cell in row.findAllElements('tc', namespace: _docxNs)) {
        final cellText = cell
            .findAllElements('t', namespace: _docxNs)
            .map((node) => node.innerText)
            .join()
            .trim();
        cellTexts.add(cellText);
      }
      if (cellTexts.any((text) => text.isNotEmpty)) {
        paragraphs.add('| ${cellTexts.join(' | ')} |');
      }
    }
  }

  final text = paragraphs.join('\n');
  if (text.trim().isEmpty) {
    throw const FormatException('no_extractable_text');
  }
  return buildTextRepresentations(text);
}
