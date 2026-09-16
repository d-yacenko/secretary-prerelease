import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/ui/today_event_emphasis.dart';

SecretaryObject _event({
  required String id,
  String? startAt,
  String? dueAt,
}) {
  return SecretaryObject(
    id: id,
    kind: 'event',
    title: id,
    body: null,
    provider: 'google_calendar',
    externalId: null,
    canonicalUri: null,
    status: null,
    startAt: startAt,
    dueAt: dueAt,
    occurredAt: null,
    metadata: const {},
    origin: 'source',
    state: 'observed',
    confidence: null,
    createdAt: '2026-09-08T08:00:00Z',
    updatedAt: '2026-09-08T08:00:00Z',
  );
}

void main() {
  final now = DateTime.parse('2026-09-08T12:00:00+03:00');

  test('current event when now is inside start/end', () {
    expect(
      todayEventEmphasis(
        _event(
          id: 'now',
          startAt: '2026-09-08T11:30:00+03:00',
          dueAt: '2026-09-08T12:30:00+03:00',
        ),
        now: now,
      ),
      TodayEventEmphasis.current,
    );
  });

  test('soon event starts within 60 minutes', () {
    expect(
      todayEventEmphasis(
        _event(id: 'soon', startAt: '2026-09-08T12:45:00+03:00'),
        now: now,
      ),
      TodayEventEmphasis.soon,
    );
  });

  test('future beyond 60 minutes is neutral', () {
    expect(
      todayEventEmphasis(
        _event(id: 'later', startAt: '2026-09-08T14:00:00+03:00'),
        now: now,
      ),
      TodayEventEmphasis.none,
    );
  });

  test('past event is neutral', () {
    expect(
      todayEventEmphasis(
        _event(
          id: 'past',
          startAt: '2026-09-08T10:00:00+03:00',
          dueAt: '2026-09-08T11:00:00+03:00',
        ),
        now: now,
      ),
      TodayEventEmphasis.none,
    );
  });

  test('missing end is never indefinitely current', () {
    expect(
      todayEventEmphasis(
        _event(id: 'open-ended', startAt: '2026-09-08T11:00:00+03:00'),
        now: now,
      ),
      TodayEventEmphasis.none,
    );
  });
}
