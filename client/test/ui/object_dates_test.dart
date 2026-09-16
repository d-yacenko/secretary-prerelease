import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/ui/date_format.dart';
import 'package:personal_secretary/ui/object_dates.dart';

SecretaryObject _object({
  required String kind,
  String? dueAt,
  String? startAt,
  String? plannedStartAt,
  String? plannedEndAt,
  String? occurredAt,
  String? updatedAt,
  Map<String, dynamic>? metadata,
}) {
  return SecretaryObject(
    id: 'o1',
    kind: kind,
    title: 'Test',
    dueAt: dueAt,
    startAt: startAt,
    plannedStartAt: plannedStartAt,
    plannedEndAt: plannedEndAt,
    occurredAt: occurredAt,
    metadata: metadata ?? {},
    origin: 'user',
    state: 'confirmed',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: updatedAt ?? '2026-08-30T12:43:00Z',
  );
}

void main() {
  test('primary date selection by kind', () {
    expect(
      objectPrimaryDateIso(_object(kind: 'task', dueAt: '2026-08-31T18:00:00Z')),
      '2026-08-31T18:00:00Z',
    );
    expect(
      objectPlannedIntervalDisplayValue(
        _object(kind: 'task', dueAt: '2026-08-31T18:00:00Z'),
      ),
      isNull,
    );
    expect(
      objectPrimaryDateLabel(
        _object(kind: 'task', dueAt: '2026-08-31T18:00:00Z'),
      ),
      contains('Срок:'),
    );
    expect(objectPrimaryDateFieldLabel(_object(kind: 'task')), 'Срок');
    expect(
      objectPrimaryDateDisplayValue(
        _object(kind: 'email', occurredAt: '2026-08-30T15:43:00Z'),
      ),
      contains('30.08.2026'),
    );
    expect(objectPrimaryDateFieldLabel(_object(kind: 'email')), 'Дата');
    expect(
      objectPrimaryDateIso(
        _object(kind: 'event', startAt: '2026-08-30T10:00:00Z'),
      ),
      '2026-08-30T10:00:00Z',
    );
    expect(
      objectPrimaryDateIso(
        _object(kind: 'temporal_hint', startAt: '2026-08-30T10:00:00Z'),
      ),
      '2026-08-30T10:00:00Z',
    );
    expect(
      objectPrimaryDateFieldLabel(_object(kind: 'temporal_hint')),
      'Начало',
    );
    expect(
      objectPrimaryDateIso(
        _object(
          kind: 'email',
          occurredAt: '2026-08-30T15:43:00Z',
        ),
      ),
      '2026-08-30T15:43:00Z',
    );
    expect(
      objectPrimaryDateIso(
        _object(
          kind: 'file',
          metadata: {'modified_at': '2026-08-29T08:00:00Z'},
          occurredAt: '2026-08-28T08:00:00Z',
        ),
      ),
      '2026-08-29T08:00:00Z',
    );
    expect(
      objectPrimaryDateIso(
        _object(kind: 'note', occurredAt: null, updatedAt: '2026-08-30T12:43:00Z'),
      ),
      '2026-08-30T12:43:00Z',
    );
  });

  test('planned interval uses local timezone and is not the due date', () {
    final task = _object(
      kind: 'task',
      dueAt: '2026-08-31T18:00:00Z',
      plannedStartAt: '2026-09-07T08:00:00Z',
      plannedEndAt: '2026-09-07T09:00:00Z',
    );
    expect(objectPrimaryDateIso(task), '2026-08-31T18:00:00Z');
    final planned = objectPlannedIntervalDisplayValue(task);
    expect(planned, isNotNull);
    expect(planned, contains(formatUserDateTime('2026-09-07T08:00:00Z')));
    expect(objectPlannedIntervalDisplayValue(_object(kind: 'note')), isNull);
  });
}
