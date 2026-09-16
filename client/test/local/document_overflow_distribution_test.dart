import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/local/client_content_revision.dart';
import 'package:personal_secretary/local/extraction/extraction_constants.dart';
import 'package:personal_secretary/local/extraction/representation_builder.dart';

const _overflowBegin = 'OVERFLOW_BEGIN_MARKER';
const _overflowMiddle = 'OVERFLOW_MIDDLE_MARKER';
const _overflowTail = 'OVERFLOW_TAIL_MARKER';

const _capBegin = 'CAP_BEGIN_MARKER';
const _capMiddle = 'CAP_MIDDLE_MARKER';
const _capTail = 'CAP_TAIL_MARKER';

String _overflowTextWithMarkers() {
  final block = '${'f' * 15800}\n';
  final buffer = StringBuffer('$_overflowBegin\n$block');
  for (var index = 0; index < 10; index++) {
    buffer.write(block);
  }
  buffer.write('$_overflowMiddle\n$block');
  for (var index = 0; index < 10; index++) {
    buffer.write(block);
  }
  buffer.write('$_overflowTail\n');
  final text = buffer.toString();
  expect(utf8ByteLength(text), greaterThan(kMaxExtractorTotalBytes));
  final parts = packTextIntoRepresentationParts(text);
  final middlePartIndex = parts.indexWhere((part) => part.contains(_overflowMiddle));
  expect(middlePartIndex, greaterThan(-1));
  final selected = selectRepresentationPartIndices(
    parts,
    maxParts: kMaxExtractorParts,
    maxTotalBytes: kMaxExtractorTotalBytes,
  );
  expect(selected, contains(middlePartIndex));
  return text;
}

String _largeOverflowText() {
  final line = 'row-${'x' * 500}\n';
  return '${line * 2600}LARGE_OVERFLOW_TAIL';
}

String _safetyCapTextWithMarkers() {
  final block = '${'a' * 12000}\n';
  final buffer = StringBuffer('$_capBegin\n$block');
  for (var index = 0; index < 90; index++) {
    buffer.write(block);
  }
  buffer.write('$_capMiddle\n$block');
  for (var index = 0; index < 90; index++) {
    buffer.write(block);
  }
  buffer.write('$_capTail\n');
  final text = buffer.toString();
  expect(utf8ByteLength(text), greaterThan(kMaxExtractedTextBytes));
  return text;
}

List<Map<String, dynamic>> _buildReps(String text) => buildTextRepresentations(text);

String _joined(List<Map<String, dynamic>> reps) =>
    reps.map((rep) => rep['text'] as String).join('\n');

void _assertByteBounds(List<Map<String, dynamic>> reps) {
  var total = 0;
  for (final rep in reps) {
    final bytes = utf8ByteLength(rep['text'] as String);
    expect(bytes, lessThanOrEqualTo(kMaxExtractorPartBytes));
    total += bytes;
  }
  expect(reps.length, lessThanOrEqualTo(kMaxExtractorParts));
  expect(total, lessThanOrEqualTo(kMaxExtractorTotalBytes));
}

List<int> _sourceChunkIndices(List<Map<String, dynamic>> reps) {
  return [
    for (final rep in reps)
      (rep['metadata'] as Map?)?['source_chunk_index'] as int,
  ];
}

void main() {
  test('A >256KiB overflow keeps begin middle and tail markers', () {
    final source = _overflowTextWithMarkers();
    final first = _buildReps(source);
    final second = _buildReps(source);
    final joined = _joined(first);
    expect(joined, contains(_overflowBegin));
    expect(joined, contains(_overflowMiddle));
    expect(joined, contains(_overflowTail));
    expect(
      first.any((rep) => (rep['metadata'] as Map?)?['truncated'] == true),
      isTrue,
    );
    _assertByteBounds(first);
    expect(first, second);
  });

  test('B large overflow spans beginning middle and tail part indices', () {
    final source = _largeOverflowText();
    final parts = packTextIntoRepresentationParts(source);
    expect(parts.length, greaterThan(kMaxExtractorParts));
    final first = _buildReps(source);
    final second = _buildReps(source);
    final indices = _sourceChunkIndices(first);
    expect(indices, isNotEmpty);
    expect(indices.first, lessThan(parts.length ~/ 4));
    expect(
      indices.any((index) => index >= parts.length ~/ 3 && index <= 2 * parts.length ~/ 3),
      isTrue,
    );
    expect(indices.last, greaterThan(2 * parts.length ~/ 3));
    expect(first, second);
    _assertByteBounds(first);
  });

  test('C >2MiB safety cap keeps begin middle and tail markers', () {
    final source = _safetyCapTextWithMarkers();
    final capped = capText(source);
    expect(capped.$2, isTrue);
    expect(utf8ByteLength(capped.$1), lessThanOrEqualTo(kMaxExtractedTextBytes));
    final first = _buildReps(source);
    final second = _buildReps(source);
    final joined = _joined(first);
    expect(joined, contains(_capBegin));
    expect(joined, contains(_capMiddle));
    expect(joined, contains(_capTail));
    expect(
      first.any((rep) => (rep['metadata'] as Map?)?['truncated'] == true),
      isTrue,
    );
    expect(first, second);
  });

  test('E >2MiB Cyrillic capText keeps begin middle and tail markers', () {
    const begin = 'CAP_UTF8_BEGIN';
    const middle = 'CAP_UTF8_MIDDLE';
    const tail = 'CAP_UTF8_TAIL';
    final block = '${'щ' * 12000}\n';
    final buffer = StringBuffer('$begin\n$block');
    for (var index = 0; index < 95; index++) {
      buffer.write(block);
    }
    buffer.write('$middle\n$block');
    for (var index = 0; index < 95; index++) {
      buffer.write(block);
    }
    buffer.write('$tail\n');
    final source = buffer.toString();
    expect(utf8ByteLength(source), greaterThan(kMaxExtractedTextBytes));

    final cappedFirst = capText(source);
    final cappedSecond = capText(source);
    expect(cappedFirst.$2, isTrue);
    expect(utf8ByteLength(cappedFirst.$1), lessThanOrEqualTo(kMaxExtractedTextBytes));
    expect(cappedFirst.$1, contains(begin));
    expect(cappedFirst.$1, contains(middle));
    expect(cappedFirst.$1, contains(tail));
    expect(cappedFirst.$1, cappedSecond.$1);

    final repsFirst = _buildReps(source);
    final repsSecond = _buildReps(source);
    final joined = _joined(repsFirst);
    expect(joined, contains(begin));
    expect(joined, contains(middle));
    expect(joined, contains(tail));
    _assertByteBounds(repsFirst);
    expect(repsFirst, repsSecond);
  });

  test('sliceAroundPosition keeps emoji anchor inside byte-bounded slice', () {
    const prefix = 'abc';
    const anchor = '🙂';
    const suffix = 'defghijklmnopqrstuvwxyz';
    final text = '$prefix$anchor$suffix';
    final anchorPos = prefix.length;
    final slice = sliceAroundPosition(text, anchorPos, 8);
    expect(slice, contains(anchor));
    expect(utf8ByteLength(slice), lessThanOrEqualTo(8));
  });

  test('D Cyrillic overflow keeps distributed markers within byte bounds', () {
    const begin = 'НАЧАЛО_МАРКЕР';
    const middle = 'СЕРЕДИНА_МАРКЕР';
    const tail = 'КОНЕЦ_МАРКЕР';
    final block = '${'й' * 15800}\n';
    final buffer = StringBuffer('$begin\n$block');
    for (var index = 0; index < 10; index++) {
      buffer.write(block);
    }
    buffer.write('$middle\n$block');
    for (var index = 0; index < 10; index++) {
      buffer.write(block);
    }
    buffer.write('$tail\n');
    final source = buffer.toString();
    expect(utf8ByteLength(source), greaterThan(kMaxExtractorTotalBytes));
    final first = _buildReps(source);
    final second = _buildReps(source);
    final joined = _joined(first);
    expect(joined, contains(begin));
    expect(joined, contains(middle));
    expect(joined, contains(tail));
    _assertByteBounds(first);
    expect(first, second);
  });
}
