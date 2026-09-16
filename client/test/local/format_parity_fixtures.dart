import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:personal_secretary/local/extraction/duckdb_session.dart';
import 'package:personal_secretary/local/extraction/extraction_constants.dart';

Future<void> writeMinimalPdf(File file, {String text = 'pdf distinctive phrase delta'}) async {
  await file.writeAsBytes(_minimalPdfBytes(text));
}

List<int> _minimalPdfBytes(String text) {
  final escaped = text
      .replaceAll('\\', r'\\')
      .replaceAll('(', r'\(')
      .replaceAll(')', r'\)');
  final stream = 'BT /F1 12 Tf 50 700 Td ($escaped) Tj ET';
  final objs = <String>[
    '1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n',
    '2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n',
    '3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
        '/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n',
    '4 0 obj<< /Length ${stream.length} >>stream\n$stream\nendstream endobj\n',
    '5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n',
  ];
  final header = utf8.encode('%PDF-1.4\n');
  final bodyParts = <List<int>>[];
  final xrefPositions = <int>[];
  var pos = header.length;
  for (final obj in objs) {
    xrefPositions.add(pos);
    final chunk = utf8.encode(obj);
    bodyParts.add(chunk);
    pos += chunk.length;
  }
  final body = bodyParts.expand((part) => part).toList();
  final xrefStart = pos;
  final xrefLines = <String>[
    'xref\n',
    '0 ${objs.length + 1}\n',
    '0000000000 65535 f \n',
    for (final offset in xrefPositions) '${offset.toString().padLeft(10, '0')} 00000 n \n',
  ];
  final xref = utf8.encode(xrefLines.join());
  final trailer = utf8.encode(
    'trailer<< /Size ${objs.length + 1} /Root 1 0 R >>\n'
    'startxref\n$xrefStart\n%%EOF\n',
  );
  return [...header, ...body, ...xref, ...trailer];
}

Future<void> writeBlankPdf(File file) async {
  await file.writeAsBytes(_blankPdfBytes());
}

List<int> _blankPdfBytes() {
  final objs = <String>[
    '1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n',
    '2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n',
    '3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>endobj\n',
  ];
  final header = utf8.encode('%PDF-1.4\n');
  final bodyParts = <List<int>>[];
  final xrefPositions = <int>[];
  var pos = header.length;
  for (final obj in objs) {
    xrefPositions.add(pos);
    final chunk = utf8.encode(obj);
    bodyParts.add(chunk);
    pos += chunk.length;
  }
  final body = bodyParts.expand((part) => part).toList();
  final xrefStart = pos;
  final xrefLines = <String>[
    'xref\n',
    '0 ${objs.length + 1}\n',
    '0000000000 65535 f \n',
    for (final offset in xrefPositions) '${offset.toString().padLeft(10, '0')} 00000 n \n',
  ];
  final xref = utf8.encode(xrefLines.join());
  final trailer = utf8.encode(
    'trailer<< /Size ${objs.length + 1} /Root 1 0 R >>\n'
    'startxref\n$xrefStart\n%%EOF\n',
  );
  return [...header, ...body, ...xref, ...trailer];
}

Future<void> writeMultiPagePdf(File file, int pages, {String marker = 'page_marker'}) async {
  final pageKids = <String>[];
  final pageObjs = <String>[];
  final contentObjs = <String>[];
  const fontObjNum = 3;
  final firstPageObjNum = 4;
  for (var index = 0; index < pages; index++) {
    final pageObjNum = firstPageObjNum + index * 2;
    final contentObjNum = pageObjNum + 1;
    pageKids.add('$pageObjNum 0 R');
    final escaped = '$marker-$index'
        .replaceAll('\\', r'\\')
        .replaceAll('(', r'\(')
        .replaceAll(')', r'\)');
    final stream = 'BT /F1 12 Tf 50 700 Td ($escaped) Tj ET';
    pageObjs.add(
      '$pageObjNum 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
      '/Contents $contentObjNum 0 R /Resources<< /Font<< /F1 $fontObjNum 0 R >> >> >>endobj\n',
    );
    contentObjs.add(
      '$contentObjNum 0 obj<< /Length ${stream.length} >>stream\n$stream\nendstream endobj\n',
    );
  }
  final fontObj =
      '$fontObjNum 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n';
  final objs = <String>[
    '1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n',
    '2 0 obj<< /Type /Pages /Kids [${pageKids.join(' ')}] /Count $pages >>endobj\n',
    fontObj,
    ...pageObjs,
    ...contentObjs,
  ];
  await file.writeAsBytes(_buildPdf(objs));
}

Future<void> writeMergedMultiPagePdf(
  File file,
  int pages, {
  String marker = 'page_marker',
  int bodyPaddingChars = 0,
}) async {
  final partsDir = Directory('${file.parent.path}/pdf-parts-${pages}-${DateTime.now().microsecondsSinceEpoch}');
  partsDir.createSync(recursive: true);
  final partPaths = <String>[];
  try {
    for (var index = 0; index < pages; index++) {
      final part = File('${partsDir.path}/page-$index.pdf');
      final padding = bodyPaddingChars > 0 ? ' ${'p' * bodyPaddingChars}' : '';
      await writeMinimalPdf(part, text: '$marker-$index$padding');
      partPaths.add(part.path);
    }
    final result = await Process.run('pdfunite', [...partPaths, file.path]);
    if (result.exitCode != 0) {
      throw StateError(
        'pdfunite failed (${result.exitCode}): ${result.stderr}',
      );
    }
  } finally {
    if (partsDir.existsSync()) {
      partsDir.deleteSync(recursive: true);
    }
  }
}

Future<void> writeMinimalDocx(File file, {String text = 'docx paragraph beta'}) async {
  final documentXml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>$text</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>cell1</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>cell2</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>''';
  await _writeOoxmlZip(file, {
    'word/document.xml': documentXml,
    '[Content_Types].xml': _contentTypesXml(
      '/word/document.xml',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml',
    ),
  });
}

Future<void> writeMinimalXlsx(File file) async {
  final workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>''';
  final rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>''';
  final sheet1 = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>col_a</t></is></c><c r="B1" t="inlineStr"><is><t>col_b</t></is></c></row>
    <row r="2"><c r="A2" t="inlineStr"><is><t>xlsx_value</t></is></c><c r="B2" t="inlineStr"><is><t>2</t></is></c></row>
  </sheetData>
</worksheet>''';
  await _writeOoxmlZip(file, {
    '[Content_Types].xml': _genericContentTypes(),
    'xl/workbook.xml': workbook,
    'xl/_rels/workbook.xml.rels': rels,
    'xl/worksheets/sheet1.xml': sheet1,
  });
}

Future<void> writeMinimalPptx(File file, {String text = 'slide distinctive gamma'}) async {
  final slide = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:txBody><a:p><a:r><a:t>$text</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:sld>''';
  await _writeOoxmlZip(file, {
    '[Content_Types].xml': _genericContentTypes(),
    'ppt/slides/slide1.xml': slide,
  });
}

Future<void> writeMinimalOdt(File file, {String paragraph = 'odt distinctive alpha'}) async {
  final contentXml = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:text>
      <text:h>ODT Heading</text:h>
      <text:p>$paragraph</text:p>
      <text:list><text:list-item><text:p>list item one</text:p></text:list-item></text:list>
      <table:table>
        <table:table-row>
          <table:table-cell><text:p>cell_a</text:p></table:table-cell>
          <table:table-cell><text:p>cell_b</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:text>
  </office:body>
</office:document-content>''';
  await _writeOdfZip(file, contentXml, 'application/vnd.oasis.opendocument.text');
}

Future<void> writeMinimalOds(File file) async {
  final contentXml = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:spreadsheet>
      <table:table table:name="Sheet1">
        <table:table-row>
          <table:table-cell><text:p>col_a</text:p></table:table-cell>
          <table:table-cell><text:p>col_b</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>ods_value</text:p></table:table-cell>
          <table:table-cell><text:p>4</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>''';
  await _writeOdfZip(
    file,
    contentXml,
    'application/vnd.oasis.opendocument.spreadsheet',
  );
}

Future<void> writeOdtWithRepeatedColumns(File file) async {
  final contentXml = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:text>
      <table:table>
        <table:table-row>
          <table:table-cell table:number-columns-repeated="100">
            <text:p>repeat_marker_odt</text:p>
          </table:table-cell>
        </table:table-row>
      </table:table>
    </office:text>
  </office:body>
</office:document-content>''';
  await _writeOdfZip(file, contentXml, 'application/vnd.oasis.opendocument.text');
}

Future<void> writeOdsWithRepeatedRows(File file) async {
  final contentXml = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:spreadsheet>
      <table:table table:name="Sheet1">
        <table:table-row>
          <table:table-cell><text:p>name</text:p></table:table-cell>
        </table:table-row>
        <table:table-row table:number-rows-repeated="100">
          <table:table-cell office:value-type="string" office:string-value="repeat_marker_ods"/>
        </table:table-row>
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>''';
  await _writeOdfZip(
    file,
    contentXml,
    'application/vnd.oasis.opendocument.spreadsheet',
  );
}

Future<void> writeOdpWithRepeatedTable(File file) async {
  final contentXml = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
  xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0">
  <office:body>
    <office:presentation>
      <draw:page>
        <table:table>
          <table:table-row table:number-rows-repeated="100">
            <table:table-cell><text:p>repeat_marker_odp</text:p></table:table-cell>
          </table:table-row>
        </table:table>
      </draw:page>
    </office:presentation>
  </office:body>
</office:document-content>''';
  await _writeOdfZip(
    file,
    contentXml,
    'application/vnd.oasis.opendocument.presentation',
  );
}

Future<void> writeLargeMultiSheetOds(File file, {int rowsPerSheet = 50}) async {
  final sheet1Data = StringBuffer()
    ..writeln('<table:table table:name="Alpha">')
    ..writeln('<table:table-row>')
    ..writeln('<table:table-cell><text:p>name</text:p></table:table-cell>')
    ..writeln('<table:table-cell><text:p>value</text:p></table:table-cell>')
    ..writeln('</table:table-row>');
  for (var i = 1; i <= rowsPerSheet; i++) {
    sheet1Data.writeln(
      '<table:table-row>'
      '<table:table-cell><text:p>alpha_$i</text:p></table:table-cell>'
      '<table:table-cell><text:p>$i</text:p></table:table-cell>'
      '</table:table-row>',
    );
  }
  sheet1Data.writeln('</table:table>');

  final sheet2Data = StringBuffer()
    ..writeln('<table:table table:name="Beta">')
    ..writeln('<table:table-row>')
    ..writeln('<table:table-cell><text:p>name</text:p></table:table-cell>')
    ..writeln('<table:table-cell><text:p>value</text:p></table:table-cell>')
    ..writeln('</table:table-row>');
  for (var i = 1; i <= rowsPerSheet; i++) {
    final marker = i == rowsPerSheet ? 'ods_sheet_beta_marker' : 'beta_$i';
    sheet2Data.writeln(
      '<table:table-row>'
      '<table:table-cell><text:p>$marker</text:p></table:table-cell>'
      '<table:table-cell><text:p>$i</text:p></table:table-cell>'
      '</table:table-row>',
    );
  }
  sheet2Data.writeln('</table:table>');

  final contentXml = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:spreadsheet>
      $sheet1Data
      $sheet2Data
    </office:spreadsheet>
  </office:body>
</office:document-content>''';
  await _writeOdfZip(
    file,
    contentXml,
    'application/vnd.oasis.opendocument.spreadsheet',
  );
}

Future<void> writeOdsSourceRowIdentity(File file) async {
  final contentXml = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:spreadsheet>
      <table:table table:name="SheetA">
        <table:table-row>
          <table:table-cell><text:p>Name</text:p></table:table-cell>
          <table:table-cell><text:p>Value</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p></text:p></table:table-cell>
          <table:table-cell><text:p></text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>after_blank</text:p></table:table-cell>
          <table:table-cell><text:p>v1</text:p></table:table-cell>
        </table:table-row>
        <table:table-row table:number-rows-repeated="2">
          <table:table-cell office:value-type="string" office:string-value="repeat_marker"/>
        </table:table-row>
      </table:table>
      <table:table table:name="SheetB">
        <table:table-row>
          <table:table-cell><text:p>Key</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell office:value-type="string" office:string-value="sheetb_row2_value"/>
        </table:table-row>
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>''';
  await _writeOdfZip(
    file,
    contentXml,
    'application/vnd.oasis.opendocument.spreadsheet',
  );
}

Future<void> writeOdsLargeRepeatWithMarker(File file) async {
  final contentXml = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:spreadsheet>
      <table:table table:name="SheetA">
        <table:table-row>
          <table:table-cell><text:p>Name</text:p></table:table-cell>
          <table:table-cell><text:p>Value</text:p></table:table-cell>
        </table:table-row>
        <table:table-row table:number-rows-repeated="${kMaxOdfRepeatExpansion + 36}">
          <table:table-cell office:value-type="string" office:string-value="repeat_gap_filler"/>
        </table:table-row>
        <table:table-row>
          <table:table-cell office:value-type="string" office:string-value="after_repeat_marker"/>
        </table:table-row>
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>''';
  await _writeOdfZip(
    file,
    contentXml,
    'application/vnd.oasis.opendocument.spreadsheet',
  );
}

Future<void> writeOdsWiderDataThanHeader(File file) async {
  final contentXml = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:spreadsheet>
      <table:table table:name="SheetA">
        <table:table-row>
          <table:table-cell><text:p>Name</text:p></table:table-cell>
          <table:table-cell><text:p>Amount</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>Alice</text:p></table:table-cell>
          <table:table-cell><text:p>42</text:p></table:table-cell>
          <table:table-cell><text:p>hidden_marker</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>''';
  await _writeOdfZip(
    file,
    contentXml,
    'application/vnd.oasis.opendocument.spreadsheet',
  );
}

Future<void> writeOdsPositionalColumns(File file) async {
  final contentXml = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:spreadsheet>
      <table:table table:name="SheetA">
        <table:table-row>
          <table:table-cell><text:p>Name</text:p></table:table-cell>
          <table:table-cell><text:p></text:p></table:table-cell>
          <table:table-cell><text:p>Amount</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>Alice</text:p></table:table-cell>
          <table:table-cell><text:p>mid</text:p></table:table-cell>
          <table:table-cell><text:p>42</text:p></table:table-cell>
        </table:table-row>
      </table:table>
      <table:table table:name="SheetB">
        <table:table-row>
          <table:table-cell><text:p>Name</text:p></table:table-cell>
          <table:table-cell><text:p>Name</text:p></table:table-cell>
          <table:table-cell><text:p>Qty</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>a</text:p></table:table-cell>
          <table:table-cell><text:p>b</text:p></table:table-cell>
          <table:table-cell><text:p>1</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>a2</text:p></table:table-cell>
          <table:table-cell><text:p>b2</text:p></table:table-cell>
          <table:table-cell><text:p>2</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>''';
  await _writeOdfZip(
    file,
    contentXml,
    'application/vnd.oasis.opendocument.spreadsheet',
  );
}

Future<void> writeXlsxWithRowCount(File file, int dataRows) async {
  final sheetRows = StringBuffer()
    ..writeln(
      '<row r="1"><c r="A1" t="inlineStr"><is><t>header</t></is></c></row>',
    );
  for (var i = 1; i <= dataRows; i++) {
    final rowNum = i + 1;
    sheetRows.writeln(
      '<row r="$rowNum"><c r="A$rowNum" t="inlineStr"><is><t>row_$i</t></is></c></row>',
    );
  }
  await _writeSingleSheetXlsx(file, sheetRows.toString());
}

Future<void> writeXlsxWithWideColumn(File file) async {
  const sheet = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>h</t></is></c>
      <c r="BM1" t="inlineStr"><is><t>wide_header</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>left</t></is></c>
      <c r="BM2" t="inlineStr"><is><t>beyond_column_cap</t></is></c>
    </row>
  </sheetData>
</worksheet>''';
  await _writeSingleSheetXlsx(file, '', sheetXml: sheet);
}

Future<void> writeXlsxWithSheetCount(File file, int sheetCount) async {
  final relEntries = StringBuffer();
  final workbookSheets = StringBuffer();
  final contentTypes = StringBuffer(
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>',
  );
  final archiveEntries = <String, String>{};
  for (var i = 1; i <= sheetCount; i++) {
    workbookSheets.writeln(
      '<sheet name="Sheet$i" sheetId="$i" r:id="rId$i"/>',
    );
    relEntries.writeln(
      '<Relationship Id="rId$i" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet$i.xml"/>',
    );
    contentTypes.writeln(
      '<Override PartName="/xl/worksheets/sheet$i.xml" '
      'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>',
    );
    archiveEntries['xl/worksheets/sheet$i.xml'] = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>sheet_$i</t></is></c></row>
  </sheetData>
</worksheet>''';
  }
  archiveEntries['[Content_Types].xml'] = '$contentTypes</Types>';
  archiveEntries['xl/_rels/workbook.xml.rels'] = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
$relEntries</Relationships>''';
  archiveEntries['xl/workbook.xml'] = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>$workbookSheets</sheets>
</workbook>''';
  await _writeOoxmlZip(file, archiveEntries);
}

Future<void> _writeSingleSheetXlsx(
  File file,
  String sheetDataRows, {
  String? sheetXml,
}) async {
  final sheet = sheetXml ??
      '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
$sheetDataRows  </sheetData>
</worksheet>''';
  await _writeOoxmlZip(file, {
    '[Content_Types].xml': _genericContentTypes(),
    'xl/workbook.xml': '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>''',
    'xl/_rels/workbook.xml.rels': '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>''',
    'xl/worksheets/sheet1.xml': sheet,
  });
}

Future<void> writeOdpPresentation(
  File file,
  int slideCount, {
  Map<int, String> markers = const {},
  int bodyPaddingChars = 0,
}) async {
  final pages = StringBuffer();
  for (var slide = 1; slide <= slideCount; slide++) {
    final text = markers[slide] ?? 'slide_text_$slide';
    final padding = bodyPaddingChars > 0 ? ' ${'p' * bodyPaddingChars}' : '';
    pages.writeln('''
      <draw:page>
        <text:p>$text$padding</text:p>
      </draw:page>''');
  }
  final contentXml = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0">
  <office:body>
    <office:presentation>
      $pages
    </office:presentation>
  </office:body>
</office:document-content>''';
  await _writeOdfZip(
    file,
    contentXml,
    'application/vnd.oasis.opendocument.presentation',
  );
}

Future<void> writePptxPresentation(
  File file,
  int slideCount, {
  Map<int, String> markers = const {},
  int bodyPaddingChars = 0,
}) async {
  final entries = <String, String>{
    '[Content_Types].xml': _genericContentTypes(),
  };
  for (var index = 1; index <= slideCount; index++) {
    final text = markers[index] ?? 'slide_text_$index';
    final padding = bodyPaddingChars > 0 ? ' ${'p' * bodyPaddingChars}' : '';
    entries['ppt/slides/slide$index.xml'] = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:txBody><a:p><a:r><a:t>$text$padding</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:sld>''';
  }
  await _writeOoxmlZip(file, entries);
}

Future<void> writeMinimalOdp(File file) async {
  final contentXml = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0">
  <office:body>
    <office:presentation>
      <draw:page>
        <text:p>odp distinctive slide</text:p>
      </draw:page>
    </office:presentation>
  </office:body>
</office:document-content>''';
  await _writeOdfZip(
    file,
    contentXml,
    'application/vnd.oasis.opendocument.presentation',
  );
}

Future<void> writeMinimalParquet(File file, {String marker = 'parquet_marker_alpha'}) async {
  await withDuckDb((session) async {
    final path = file.absolute.path.replaceAll("'", "''");
    await session.queryRows(
      "COPY (SELECT '$marker' AS marker, 1 AS value UNION ALL SELECT 'row_two', 2) "
      "TO '$path' (FORMAT PARQUET)",
    );
  });
}

Future<void> writeLargeParquet(File file, int rowCount, {int? markerRow}) async {
  await withDuckDb((session) async {
    final path = file.absolute.path.replaceAll("'", "''");
    await session.queryRows(
      'CREATE TABLE tmp_rows AS SELECT '
      "CASE WHEN i = ${markerRow ?? -1} THEN 'format_parity_marker_row' ELSE 'row_' || i::VARCHAR END AS marker, "
      'i AS value '
      'FROM range($rowCount) t(i)',
    );
    await session.queryRows(
      "COPY tmp_rows TO '$path' (FORMAT PARQUET, ROW_GROUP_SIZE 2048)",
    );
  });
}

Future<void> writeMalformedZip(File file) async {
  await file.writeAsBytes(utf8.encode('not a zip archive'));
}

Future<void> writeLargeCsv(File file, int rowCount, {String marker = 'Doe, John'}) async {
  final buffer = StringBuffer('name,value\n"$marker",42\n');
  for (var i = 0; i < rowCount; i++) {
    buffer.writeln('row$i,value$i');
  }
  await file.writeAsString(buffer.toString());
}

Future<void> writeLargeCsvWithMultilineQuoted(File file) async {
  final marker = 'multiline_marker_${'й' * 40}';
  final buffer = StringBuffer()
    ..writeln('name,value')
    ..writeln('"line1\n$marker",42');
  while (buffer.length < 300 * 1024) {
    buffer.writeln('row${buffer.length},plain');
  }
  buffer.writeln('end,marker');
  await file.writeAsString(buffer.toString());
}

Future<void> writeLargeCsvWiderThanHeader(File file) async {
  final buffer = StringBuffer('name,value\n');
  while (buffer.length < 300 * 1024) {
    buffer.writeln('row${buffer.length},plain,extra_marker');
  }
  await file.writeAsString(buffer.toString());
}

Future<void> writeOrderedPptx(File file, int slideCount) async {
  final entries = <String, String>{
    '[Content_Types].xml': _genericContentTypes(),
  };
  for (var index = 1; index <= slideCount; index++) {
    entries['ppt/slides/slide$index.xml'] = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:txBody><a:p><a:r><a:t>slide_text_$index</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:sld>''';
  }
  await _writeOoxmlZip(file, entries);
}

List<int> _buildPdf(List<String> objs) {
  final header = utf8.encode('%PDF-1.4\n');
  final bodyParts = <List<int>>[];
  final xrefPositions = <int>[];
  var pos = header.length;
  for (final obj in objs) {
    xrefPositions.add(pos);
    final chunk = utf8.encode(obj);
    bodyParts.add(chunk);
    pos += chunk.length;
  }
  final body = bodyParts.expand((part) => part).toList();
  final xrefStart = pos;
  final xrefLines = <String>[
    'xref\n',
    '0 ${objs.length + 1}\n',
    '0000000000 65535 f \n',
    for (final offset in xrefPositions) '${offset.toString().padLeft(10, '0')} 00000 n \n',
  ];
  final xref = utf8.encode(xrefLines.join());
  final trailer = utf8.encode(
    'trailer<< /Size ${objs.length + 1} /Root 1 0 R >>\n'
    'startxref\n$xrefStart\n%%EOF\n',
  );
  return [...header, ...body, ...xref, ...trailer];
}

Future<void> _writeOoxmlZip(File file, Map<String, String> entries) async {
  final archive = Archive();
  for (final entry in entries.entries) {
    archive.addFile(ArchiveFile.string(entry.key, entry.value));
  }
  final encoder = ZipEncoder();
  await file.writeAsBytes(encoder.encode(archive)!);
}

Future<void> _writeOdfZip(File file, String contentXml, String mimetype) async {
  final archive = Archive()
    ..addFile(ArchiveFile.string('mimetype', mimetype))
    ..addFile(ArchiveFile.string('content.xml', contentXml));
  final encoder = ZipEncoder();
  await file.writeAsBytes(encoder.encode(archive)!);
}

String _genericContentTypes() => '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
</Types>''';

String _contentTypesXml(String partName, String contentType) => '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="$partName" ContentType="$contentType"/>
</Types>''';
