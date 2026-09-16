import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/ui/linkified_text.dart';
import 'package:personal_secretary/ui/ui_text_scale.dart';

void main() {
  test('safeHttpUri accepts http and https only', () {
    expect(safeHttpUri('https://example.com/a'), isNotNull);
    expect(safeHttpUri('http://example.com'), isNotNull);
    expect(safeHttpUri('javascript:alert(1)'), isNull);
    expect(safeHttpUri('ftp://files.example'), isNull);
    expect(safeHttpUri('not a url'), isNull);
    expect(safeHttpUri('https://example.com/path.'), isNotNull);
  });

  test('invalid stored text scale clamps', () {
    expect(clampUiTextScale(null), 1.0);
    expect(clampUiTextScale(double.nan), 1.0);
    expect(clampUiTextScale(0.5), 0.5);
    expect(clampUiTextScale(0.4), 0.5);
    expect(clampUiTextScale(2.0), 1.3);
    expect(clampUiTextScale(0.90), 0.90);
    expect(clampUiTextScale(1.1), 1.1);
    expect(clampUiTextScale(1.0), 1.0);
  });
}
