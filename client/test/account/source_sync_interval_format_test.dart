import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/account/source_sync_interval_format.dart';

void main() {
  test('120 seconds renders 2 мин', () {
    expect(formatSyncIntervalSeconds(120), '2 мин');
  });

  test('180 seconds renders 3 мин', () {
    expect(formatSyncIntervalSeconds(180), '3 мин');
  });

  test('5400 seconds renders 1 ч 30 мин', () {
    expect(formatSyncIntervalSeconds(5400), '1 ч 30 мин');
  });

  test('preset values outside server min/max unavailable', () {
    final choices = availableSyncIntervalChoices(
      currentSeconds: 300,
      minSeconds: 300,
      maxSeconds: 3600,
    );
    expect(choices.contains(60), isFalse);
    expect(choices.contains(120), isFalse);
    expect(choices.contains(300), isTrue);
    expect(choices.contains(3600), isTrue);
    expect(choices.contains(86400), isFalse);
  });

  test('current effective value always included', () {
    final choices = availableSyncIntervalChoices(
      currentSeconds: 180,
      minSeconds: 60,
      maxSeconds: 86400,
    );
    expect(choices.contains(180), isTrue);
  });
}
