import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/ui/inbox_date_groups.dart';

InboxSourceObjectOut _row({
  required String id,
  required String title,
  String? primaryAt,
  String? feedAt,
}) {
  return InboxSourceObjectOut(
    id: id,
    title: title,
    kind: 'email',
    provider: 'gmail',
    state: 'observed',
    status: null,
    origin: 'source',
    excerpt: 'excerpt',
    primaryAt: primaryAt,
    feedAt: feedAt,
  );
}

void main() {
  test('inserts separators when local date changes without reordering', () {
    final monday = DateTime(2026, 9, 7, 10).toIso8601String();
    final tuesday = DateTime(2026, 9, 8, 9).toIso8601String();
    final objects = [
      _row(id: '1', title: 'A', primaryAt: tuesday),
      _row(id: '2', title: 'B', primaryAt: tuesday),
      _row(id: '3', title: 'C', primaryAt: monday),
    ];
    final grouped = groupInboxSourceEntries(objects);
    expect(grouped[0], isA<InboxDateSeparatorEntry>());
    expect((grouped[0] as InboxDateSeparatorEntry).isWeekend, isFalse);
    expect(grouped[1], isA<InboxSourceObjectEntry>());
    expect((grouped[1] as InboxSourceObjectEntry).sourceObject.id, '1');
    expect((grouped[2] as InboxSourceObjectEntry).sourceObject.id, '2');
    expect(grouped[3], isA<InboxDateSeparatorEntry>());
    expect((grouped[4] as InboxSourceObjectEntry).sourceObject.id, '3');
  });

  test('weekend separator path', () {
    final saturday = DateTime(2026, 9, 5, 12).toIso8601String();
    final grouped = groupInboxSourceEntries([
      _row(id: '1', title: 'Sat', primaryAt: saturday),
    ]);
    final sep = grouped.first as InboxDateSeparatorEntry;
    expect(sep.isWeekend, isTrue);
    expect(sep.label.toLowerCase(), contains('суббот'));
  });

  test('missing dates fail gracefully', () {
    final grouped = groupInboxSourceEntries([
      _row(id: '1', title: 'No date', primaryAt: null),
      _row(id: '2', title: 'Bad', primaryAt: 'not-a-date'),
    ]);
    expect(grouped.first, isA<InboxDateSeparatorEntry>());
    expect((grouped.first as InboxDateSeparatorEntry).label, 'Без даты');
    expect(grouped.whereType<InboxSourceObjectEntry>().length, 2);
  });

  test('groups by feed_at not primary_at', () {
    final grouped = groupInboxSourceEntries([
      _row(
        id: '1',
        title: 'Future event',
        primaryAt: DateTime(2026, 12, 7, 6, 30).toIso8601String(),
        feedAt: DateTime(2026, 9, 8, 12).toIso8601String(),
      ),
    ]);
    final sep = grouped.first as InboxDateSeparatorEntry;
    expect(sep.date, DateTime(2026, 9, 8));
    expect(
      (grouped[1] as InboxSourceObjectEntry).sourceObject.primaryAt,
      contains('2026-12-07'),
    );
  });

  test('page-boundary same feed day has one separator', () {
    final day = DateTime(2026, 9, 7, 18).toIso8601String();
    final grouped = groupInboxSourceEntries([
      _row(id: '1', title: 'A', primaryAt: day, feedAt: day),
      _row(id: '2', title: 'B', primaryAt: day, feedAt: day),
    ]);
    expect(grouped.whereType<InboxDateSeparatorEntry>().length, 1);
  });

  test('monotonic feed dates never reverse', () {
    final grouped = groupInboxSourceEntries([
      _row(
        id: '1',
        title: 'A',
        primaryAt: DateTime(2026, 9, 8).toIso8601String(),
        feedAt: DateTime(2026, 9, 8).toIso8601String(),
      ),
      _row(
        id: '2',
        title: 'B',
        primaryAt: DateTime(2026, 12, 7).toIso8601String(),
        feedAt: DateTime(2026, 9, 7).toIso8601String(),
      ),
      _row(
        id: '3',
        title: 'C',
        primaryAt: DateTime(2026, 9, 9).toIso8601String(),
        feedAt: DateTime(2026, 9, 6).toIso8601String(),
      ),
    ]);
    final dates = grouped
        .whereType<InboxDateSeparatorEntry>()
        .map((entry) => entry.date)
        .toList();
    expect(dates, [
      DateTime(2026, 9, 8),
      DateTime(2026, 9, 7),
      DateTime(2026, 9, 6),
    ]);
  });
}
