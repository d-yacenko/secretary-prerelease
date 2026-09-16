import 'dart:io';

import 'package:archive/archive.dart';
import 'package:archive/archive_io.dart';
import 'package:xml/xml.dart';

import 'zip_safety.dart';

Future<Archive> readZipArchive(File file) async {
  final input = InputFileStream(file.path);
  try {
    final archive = ZipDecoder().decodeStream(input);
    if (archive.files.isEmpty && file.lengthSync() > 0) {
      throw const FormatException('invalid zip archive');
    }
    validateZipArchive(archive);
    return archive;
  } finally {
    await input.close();
  }
}

List<int> readArchiveEntry(Archive archive, String name) {
  final file = archive.find(name);
  if (file == null || !file.isFile) {
    throw FormatException('missing archive entry: $name');
  }
  return file.content;
}

XmlDocument parseSafeXml(List<int> bytes) {
  return XmlDocument.parse(String.fromCharCodes(bytes));
}

String elementText(XmlElement element) => element.innerText.trim();

String odfStoredCellValue(XmlElement cell, {required String officeNs}) {
  final visible = elementText(cell);
  if (visible.isNotEmpty) {
    return visible;
  }
  final stringValue = cell.getAttribute('string-value', namespace: officeNs);
  if (stringValue != null && stringValue.isNotEmpty) {
    return stringValue;
  }
  final booleanValue = cell.getAttribute('boolean-value', namespace: officeNs);
  if (booleanValue != null && booleanValue.isNotEmpty) {
    return booleanValue;
  }
  final value = cell.getAttribute('value', namespace: officeNs);
  if (value != null && value.isNotEmpty) {
    return value;
  }
  final dateValue = cell.getAttribute('date-value', namespace: officeNs);
  if (dateValue != null && dateValue.isNotEmpty) {
    return dateValue;
  }
  final timeValue = cell.getAttribute('time-value', namespace: officeNs);
  if (timeValue != null && timeValue.isNotEmpty) {
    return timeValue;
  }
  return '';
}

String escapeSqlString(String value) => value.replaceAll("'", "''");
