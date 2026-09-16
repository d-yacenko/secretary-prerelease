import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/ui/domain_labels.dart';

SecretaryObject _task({String? status, String state = 'confirmed'}) {
  return SecretaryObject(
    id: 't1',
    kind: 'task',
    title: 'Test',
    metadata: {},
    origin: 'user',
    state: state,
    status: status,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

void main() {
  test('task status labels', () {
    expect(taskStatusLabel('open'), 'Открыта');
    expect(taskStatusLabel('in_progress'), 'В работе');
    expect(taskStatusLabel('done'), 'Выполнена');
    expect(taskStatusLabel('unknown_future'), 'unknown_future');
  });

  test('object kind labels', () {
    expect(objectKindLabel('task'), 'Задача');
    expect(objectKindLabel('email'), 'Письмо');
    expect(objectKindLabel('custom_kind'), 'custom_kind');
  });

  test('object lifecycle display label', () {
    expect(
      objectLifecycleDisplayLabel(_task(status: 'in_progress')),
      'В работе',
    );
    expect(
      objectLifecycleDisplayLabel(_task(status: null, state: 'proposed')),
      'Открыта',
    );
    expect(
      objectSummaryLabel(_task(status: null, state: 'proposed')),
      'Задача • Открыта • Предложено',
    );
  });

  test('relation type labels', () {
    expect(relationTypeLabel('related_to'), 'Связано с');
    expect(relationTypeLabel('contains'), 'Содержит');
    expect(relationTypeLabel('custom_edge'), 'custom_edge');
  });

  test('folder kind label', () {
    expect(objectKindLabel('folder'), 'Папка');
  });
}
