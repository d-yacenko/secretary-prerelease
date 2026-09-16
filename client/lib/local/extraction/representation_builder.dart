import 'dart:convert';
import 'dart:math' as math;

import '../client_content_revision.dart';
import 'extraction_constants.dart';

List<Map<String, dynamic>> boundedRepresentations(
  List<Map<String, dynamic>> reps,
) {
  final bounded = <Map<String, dynamic>>[];
  var totalBytes = 0;
  for (final rep in reps) {
    if (bounded.length >= kMaxExtractorParts) {
      break;
    }
    final text = rep['text'] as String? ?? '';
    final partText = truncateToUtf8Bytes(text, kMaxExtractorPartBytes);
    final partBytes = utf8ByteLength(partText);
    if (totalBytes + partBytes > kMaxExtractorTotalBytes) {
      break;
    }
    totalBytes += partBytes;
    bounded.add({
      ...rep,
      'text': partText,
    });
  }
  return bounded;
}

(String, bool) capStructuralText(String text) {
  final bytes = utf8.encode(text);
  if (bytes.length <= kMaxExtractorPartBytes) {
    return (text, false);
  }
  return (
    truncateToUtf8Bytes(text, kMaxExtractorPartBytes),
    true,
  );
}

(String, bool) capText(String text) {
  if (utf8ByteLength(text) <= kMaxExtractedTextBytes) {
    return (text, false);
  }
  return (distributedTextSample(text, kMaxExtractedTextBytes), true);
}

String distributedTextSample(String text, int maxBytes) {
  if (maxBytes <= 0 || text.isEmpty) {
    return '';
  }
  if (utf8ByteLength(text) <= maxBytes) {
    return text;
  }
  const maxSlots = 64;
  for (var targetSlots = maxSlots; targetSlots >= 3; targetSlots--) {
    final quota = maxBytes ~/ targetSlots;
    if (quota <= 0) {
      continue;
    }
    final positions = <int>{0, text.length ~/ 2, text.length - 1};
    final remainingSlots = targetSlots - positions.length;
    for (var slot = 0; slot < remainingSlots; slot++) {
      positions.add(
        ((slot + 1) * (text.length - 1) / (remainingSlots + 1)).round(),
      );
    }
    final sortedPositions = positions.toList()..sort();
    final buffer = StringBuffer();
    var usedBytes = 0;
    var fits = true;
    for (final position in sortedPositions) {
      final slice = sliceAroundPosition(text, position, quota);
      final sliceBytes = utf8ByteLength(slice);
      if (usedBytes + sliceBytes > maxBytes) {
        fits = false;
        break;
      }
      buffer.write(slice);
      usedBytes += sliceBytes;
    }
    if (fits && usedBytes > 0) {
      return buffer.toString();
    }
  }
  final anchorQuota = maxBytes ~/ 3;
  if (anchorQuota > 0) {
    final anchors = [
      sliceAroundPosition(text, 0, anchorQuota),
      sliceAroundPosition(text, text.length ~/ 2, anchorQuota),
      sliceAroundPosition(text, text.length - 1, anchorQuota),
    ];
    final buffer = StringBuffer();
    var usedBytes = 0;
    for (final slice in anchors) {
      final sliceBytes = utf8ByteLength(slice);
      if (usedBytes + sliceBytes > maxBytes) {
        return '';
      }
      buffer.write(slice);
      usedBytes += sliceBytes;
    }
    if (usedBytes > 0) {
      return buffer.toString();
    }
  }
  return '';
}

String sliceAroundPosition(String text, int position, int maxBytes) {
  if (maxBytes <= 0 || text.isEmpty) {
    return '';
  }
  final pos = position.clamp(0, math.max(0, text.length - 1)).toInt();
  final encoded = utf8.encode(text);
  if (encoded.length <= maxBytes) {
    return text;
  }

  final anchorByte = utf8.encode(text.substring(0, pos)).length;
  var leftBudget = maxBytes ~/ 2;
  var rightBudget = maxBytes - leftBudget;
  var startByte = anchorByte - leftBudget;
  var endByte = anchorByte + rightBudget;
  if (startByte < 0) {
    endByte -= startByte;
    startByte = 0;
  }
  if (endByte > encoded.length) {
    startByte -= endByte - encoded.length;
    endByte = encoded.length;
    if (startByte < 0) {
      startByte = 0;
    }
  }

  startByte = _alignUtf8Start(encoded, startByte);
  endByte = _alignUtf8End(encoded, endByte);
  if (endByte <= startByte) {
    return '';
  }

  var slice = utf8.decode(encoded.sublist(startByte, endByte), allowMalformed: true);
  while (utf8ByteLength(slice) > maxBytes && slice.isNotEmpty) {
    final trimChars = math.max(1, slice.length ~/ 20);
    final anchorInSlice = slice.indexOf(text[pos]);
    if (anchorInSlice >= 0) {
      if (anchorInSlice > trimChars) {
        slice = slice.substring(trimChars);
      } else if (slice.length - anchorInSlice > trimChars) {
        slice = slice.substring(0, slice.length - trimChars);
      } else {
        break;
      }
    } else {
      slice = slice.substring(0, slice.length - trimChars);
    }
  }
  if (slice.isEmpty || !slice.contains(text[pos])) {
    final forced = _centeredCharSlice(text, pos, maxBytes);
    if (forced.isNotEmpty && forced.contains(text[pos])) {
      return forced;
    }
    return '';
  }
  return slice;
}

int _alignUtf8Start(List<int> bytes, int offset) {
  var start = offset.clamp(0, bytes.length).toInt();
  while (start > 0 && (bytes[start] & 0xC0) == 0x80) {
    start -= 1;
  }
  return start;
}

int _alignUtf8End(List<int> bytes, int offset) {
  var end = offset.clamp(0, bytes.length).toInt();
  while (end > 0 && (bytes[end - 1] & 0xC0) == 0x80) {
    end -= 1;
  }
  return end;
}

String _centeredCharSlice(String text, int position, int maxBytes) {
  final pos = position.clamp(0, math.max(0, text.length - 1)).toInt();
  var left = 0;
  var right = 0;
  final buffer = StringBuffer()..write(text[pos]);
  while (utf8ByteLength(buffer.toString()) < maxBytes) {
    final expanded = left <= right;
    if (expanded && pos - left - 1 >= 0) {
      left += 1;
      buffer
        ..clear()
        ..write(text.substring(pos - left, pos + right + 1));
      continue;
    }
    if (pos + right + 1 < text.length) {
      right += 1;
      buffer
        ..clear()
        ..write(text.substring(pos - left, pos + right + 1));
      continue;
    }
    if (left > 0 && pos - left >= 0) {
      left -= 1;
      buffer
        ..clear()
        ..write(text.substring(pos - left, pos + right + 1));
      continue;
    }
    break;
  }
  var slice = buffer.toString();
  while (utf8ByteLength(slice) > maxBytes && slice.length > 1) {
    if (left >= right && left > 0) {
      left -= 1;
    } else if (right > 0) {
      right -= 1;
    } else {
      break;
    }
    slice = text.substring(pos - left, pos + right + 1);
  }
  return slice.contains(text[pos]) ? slice : '';
}

Map<String, dynamic> truncationMetadata(bool truncated) {
  if (!truncated) {
    return {};
  }
  return {'truncated': true};
}

bool isTextTruncated({
  required bool textCapTruncated,
  required int totalChunks,
  required int selectedChunks,
  required int inputReps,
  required int outputReps,
}) {
  return textCapTruncated ||
      (totalChunks > 0 && selectedChunks < totalChunks) ||
      (inputReps > 0 && outputReps < inputReps);
}

List<Map<String, dynamic>> buildTextRepresentations(
  String text, {
  Map<String, dynamic>? metadata,
}) {
  return _buildPackedTextRepresentations(
    text: text,
    extraMeta: metadata ?? <String, dynamic>{},
    maxParts: kMaxExtractorParts,
    maxTotalBytes: kMaxExtractorTotalBytes,
  );
}

List<Map<String, dynamic>> buildBoundedTextRepresentations(
  String text,
  int maxParts, {
  Map<String, dynamic>? metadata,
}) {
  if (maxParts <= 0 || text.trim().isEmpty) {
    return [];
  }
  return _buildPackedTextRepresentations(
    text: text,
    extraMeta: metadata ?? <String, dynamic>{},
    maxParts: maxParts < kMaxExtractorParts ? maxParts : kMaxExtractorParts,
    maxTotalBytes: kMaxExtractorTotalBytes,
  );
}

List<Map<String, dynamic>> _buildPackedTextRepresentations({
  required String text,
  required Map<String, dynamic> extraMeta,
  required int maxParts,
  required int maxTotalBytes,
}) {
  final capped = capText(text);
  final cappedText = capped.$1;
  final textCapTruncated = capped.$2;
  if (cappedText.trim().length <= kSmallTextMaxChars &&
      utf8ByteLength(cappedText) <= kMaxExtractorPartBytes) {
    return boundedRepresentations([
      {
        'kind': 'full',
        'text': cappedText,
        'metadata': {
          ...extraMeta,
          ...truncationMetadata(textCapTruncated),
        },
      },
    ]);
  }

  final parts = packTextIntoRepresentationParts(cappedText);
  final selectedIndices = selectRepresentationPartIndices(
    parts,
    maxParts: maxParts,
    maxTotalBytes: maxTotalBytes,
  );
  final samplingTruncated = selectedIndices.length < parts.length;
  final truncated = isTextTruncated(
    textCapTruncated: textCapTruncated,
    totalChunks: parts.length,
    selectedChunks: selectedIndices.length,
    inputReps: parts.length,
    outputReps: selectedIndices.length,
  );

  final reps = <Map<String, dynamic>>[];
  for (var slot = 0; slot < selectedIndices.length; slot++) {
    final index = selectedIndices[slot];
    reps.add({
      'kind': 'chunk',
      'text': parts[index],
      'part_index': slot,
      'metadata': {
        ...extraMeta,
        ...truncationMetadata(truncated || samplingTruncated),
        'source_chunk_index': index,
      },
    });
  }

  final bounded = boundedRepresentations(reps);
  if (bounded.length < reps.length) {
    return [
      for (final rep in bounded)
        {
          ...rep,
          'metadata': {
            ...(rep['metadata'] as Map<String, dynamic>? ?? {}),
            ...truncationMetadata(true),
          },
        },
    ];
  }
  return bounded;
}

List<String> packTextIntoRepresentationParts(String text) {
  if (text.isEmpty) {
    return [];
  }
  final parts = <String>[];
  var start = 0;
  while (start < text.length) {
    var end = maxEndForUtf8Bytes(text, start, kMaxExtractorPartBytes);
    if (end >= text.length) {
      parts.add(text.substring(start));
      break;
    }
    end = preferSplitBoundary(text, start, end);
    if (end <= start) {
      end = maxEndForUtf8Bytes(text, start, kMaxExtractorPartBytes);
      if (end <= start) {
        end = (start + 1).clamp(0, text.length);
      }
    }
    parts.add(text.substring(start, end));
    start = end;
  }
  return parts;
}

int maxEndForUtf8Bytes(String text, int start, int maxBytes) {
  if (start >= text.length || maxBytes <= 0) {
    return start;
  }
  var low = start + 1;
  var high = text.length;
  while (low < high) {
    final mid = (low + high + 1) ~/ 2;
    if (utf8ByteLength(text.substring(start, mid)) <= maxBytes) {
      low = mid;
    } else {
      high = mid - 1;
    }
  }
  return low;
}

int preferSplitBoundary(String text, int start, int candidateEnd) {
  final slice = text.substring(start, candidateEnd);
  final lastNewline = slice.lastIndexOf('\n');
  if (lastNewline > 0) {
    final newlineEnd = start + lastNewline + 1;
    if (utf8ByteLength(text.substring(start, newlineEnd)) <= kMaxExtractorPartBytes) {
      return newlineEnd;
    }
  }

  final lineStart = text.lastIndexOf('\n', candidateEnd - 1) + 1;
  final nextNewline = text.indexOf('\n', candidateEnd);
  final lineEnd = nextNewline == -1 ? text.length : nextNewline;
  if (lineStart < candidateEnd && candidateEnd < lineEnd) {
    final line = text.substring(lineStart, lineEnd);
    if (line.startsWith('[slide ') || line.startsWith('[page ')) {
      if (lineStart > start) {
        return lineStart;
      }
    }
  }
  return candidateEnd;
}

List<int> selectRepresentationPartIndices(
  List<String> parts, {
  required int maxParts,
  required int maxTotalBytes,
}) {
  if (parts.isEmpty || maxParts <= 0 || maxTotalBytes <= 0) {
    return [];
  }
  final totalBytes = parts.fold<int>(0, (sum, part) => sum + utf8ByteLength(part));
  if (parts.length <= maxParts && totalBytes <= maxTotalBytes) {
    return List.generate(parts.length, (index) => index);
  }

  final upperBound = parts.length < maxParts ? parts.length : maxParts;
  for (var candidate = upperBound; candidate >= 1; candidate--) {
    final indices = selectBoundedIndices(parts.length, candidate);
    final bytes = _indicesByteTotal(parts, indices);
    if (bytes <= maxTotalBytes) {
      return indices;
    }
  }
  return [];
}

int _indicesByteTotal(List<String> parts, List<int> indices) {
  var total = 0;
  for (final index in indices) {
    total += utf8ByteLength(parts[index]);
  }
  return total;
}

List<String> chunkText(String text, int chunkSize, int overlap) {
  if (chunkSize <= 0 || text.isEmpty) {
    return [];
  }
  final chunks = <String>[];
  var start = 0;
  while (start < text.length) {
    final end = start + chunkSize > text.length ? text.length : start + chunkSize;
    chunks.add(text.substring(start, end));
    if (end >= text.length) {
      break;
    }
    start = end - overlap;
  }
  return chunks;
}

List<int> selectBoundedIndices(int total, int maxChunks) {
  if (total <= 0 || maxChunks <= 0) {
    return [];
  }
  if (total <= maxChunks) {
    return List.generate(total, (i) => i);
  }
  if (maxChunks == 1) {
    return [0];
  }
  if (maxChunks == 2) {
    return [0, total - 1];
  }

  final indices = <int>[];
  final seen = <int>{};

  void addIndex(int index) {
    final bounded = index.clamp(0, total - 1).toInt();
    if (seen.add(bounded)) {
      indices.add(bounded);
    }
  }

  addIndex(0);
  addIndex(total - 1);
  if (maxChunks == 3) {
    addIndex(total ~/ 2);
    indices.sort();
    return indices;
  }

  addIndex(total ~/ 2);
  if (maxChunks >= 5) {
    final alternateMiddle = (total - 1) ~/ 2;
    if (alternateMiddle != total ~/ 2) {
      addIndex(alternateMiddle);
    }
  }

  var remaining = maxChunks - indices.length;
  for (var slot = 0; slot < remaining; slot++) {
    if (indices.length >= maxChunks) {
      break;
    }
    final primary = ((slot + 1) * (total - 1) / (remaining + 1)).round();
    if (seen.add(primary.clamp(0, total - 1).toInt())) {
      indices.add(primary.clamp(0, total - 1).toInt());
      continue;
    }
    var offset = 1;
    while (indices.length < maxChunks && offset < total) {
      final left = primary - offset;
      if (left >= 0 && seen.add(left)) {
        indices.add(left);
        break;
      }
      final right = primary + offset;
      if (right < total && seen.add(right)) {
        indices.add(right);
        break;
      }
      offset += 1;
    }
  }
  indices.sort();
  if (indices.length > maxChunks) {
    return indices.sublist(0, maxChunks);
  }
  return indices;
}

String formatSchemaText(
  List<String> fieldnames,
  Map<String, String> columnTypes,
) {
  final parts = fieldnames
      .map((name) => '$name:${columnTypes[name] ?? 'string'}')
      .join(', ');
  return 'schema\ncolumns: $parts';
}

String formatSampleText(
  List<Map<String, String>> rows,
  List<String> fieldnames,
) {
  final lines = <String>['sample', fieldnames.join(',')];
  for (final row in rows) {
    lines.add(fieldnames.map((name) => row[name] ?? '').join(','));
  }
  return lines.join('\n');
}
