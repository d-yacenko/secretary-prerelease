import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/local/client_content_revision.dart';

void main() {
  test('truncateToUtf8Bytes respects hard byte limit', () {
    final text = 'й' * 10;
    final truncated = truncateToUtf8Bytes(text, 1);
    expect(utf8ByteLength(truncated), lessThanOrEqualTo(1));
  });

  test('truncateToUtf8Bytes never expands beyond budget on malformed cut', () {
    final bytes = List<int>.generate(32, (i) => 0xC0);
    final text = String.fromCharCodes(bytes);
    final truncated = truncateToUtf8Bytes(text, 3);
    expect(utf8ByteLength(truncated), lessThanOrEqualTo(3));
  });

  test('truncateToUtf8Bytes returns empty for zero budget', () {
    expect(truncateToUtf8Bytes('hello', 0), '');
    expect(utf8ByteLength(truncateToUtf8Bytes('hello', 0)), 0);
  });
}
