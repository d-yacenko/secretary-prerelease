import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/account/source_history_days_format.dart';

void main() {
  test('1 day pluralization', () {
    expect(formatHistoryDays(1), '1 день');
  });

  test('2-4 days pluralization', () {
    expect(formatHistoryDays(2), '2 дня');
    expect(formatHistoryDays(3), '3 дня');
    expect(formatHistoryDays(4), '4 дня');
    expect(formatHistoryDays(22), '22 дня');
  });

  test('5+ days pluralization', () {
    expect(formatHistoryDays(5), '5 дней');
    expect(formatHistoryDays(30), '30 дней');
    expect(formatHistoryDays(11), '11 дней');
    expect(formatHistoryDays(25), '25 дней');
  });

  test('preset values outside server bounds unavailable', () {
    final choices = availableHistoryDayChoices(
      currentDays: 30,
      minDays: 10,
      maxDays: 45,
    );
    expect(choices.contains(1), isFalse);
    expect(choices.contains(3), isFalse);
    expect(choices.contains(7), isFalse);
    expect(choices.contains(60), isFalse);
    expect(choices.contains(90), isFalse);
    expect(choices.contains(14), isTrue);
    expect(choices.contains(30), isTrue);
  });

  test('current effective value always included', () {
    final choices = availableHistoryDayChoices(
      currentDays: 21,
      minDays: 1,
      maxDays: 90,
    );
    expect(choices.contains(21), isTrue);
    expect(formatHistoryDays(21), '21 день');
  });
}
