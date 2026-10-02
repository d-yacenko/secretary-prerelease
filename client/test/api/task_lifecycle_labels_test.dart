import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';

void main() {
  test('update task proposal label includes frozen object id', () {
    final action = PendingAction(
      toolName: 'update_task',
      arguments: {'object_id': '0635adf9-1234-5678-90ab-cdef12345678'},
    );
    expect(action.displayLabel, 'Update task: 0635adf9-1234-5678-90ab-cdef12345678');
  });

  test('set task status proposal label includes object id and status', () {
    final action = PendingAction(
      toolName: 'set_task_status',
      arguments: {
        'object_id': '0635adf9-1234-5678-90ab-cdef12345678',
        'status': 'done',
      },
    );
    expect(
      action.displayLabel,
      'Set task status: 0635adf9-1234-5678-90ab-cdef12345678 -> done',
    );
  });

  test('delete task proposal label includes frozen object id', () {
    final action = PendingAction(
      toolName: 'delete_task',
      arguments: {'object_id': '0635adf9-1234-5678-90ab-cdef12345678'},
    );
    expect(
      action.displayLabel,
      'Delete task: 0635adf9-1234-5678-90ab-cdef12345678',
    );
  });

  test('semantic status snapshot hides the raw id', () {
    const objectId = '0635adf9-1234-5678-90ab-cdef12345678';
    final action = PendingAction(
      toolName: 'set_task_status',
      arguments: {'object_id': objectId, 'status': 'open'},
      presentation: {
        'operation': 'set_task_status',
        'entities': [
          {'role': 'target', 'id': objectId, 'title': 'Публикации', 'kind': 'task'},
        ],
        'fields': [
          {'name': 'current_status', 'value': 'open'},
          {'name': 'status', 'value': 'open'},
        ],
      },
    );
    expect(action.displayLabel, 'Публикации: open -> open');
    expect(action.displayLabel, isNot(contains(objectId)));
  });

  test('semantic part_of snapshot names child and parent', () {
    final action = PendingAction.fromJson({
      'tool_name': 'link_objects',
      'arguments': {
        'source_id': '11111111-1111-1111-1111-111111111111',
        'target_id': '22222222-2222-2222-2222-222222222222',
        'type': 'part_of',
      },
      'presentation': {
        'operation': 'link_objects',
        'relation_type': 'part_of',
        'entities': [
          {'role': 'source', 'title': 'Бизнес', 'kind': 'task'},
          {'role': 'target', 'title': 'Экспериментальная рубрика октября', 'kind': 'task'},
        ],
        'fields': [],
      },
    });
    expect(
      action.displayLabel,
      'Добавить в направление: Бизнес -> Экспериментальная рубрика октября',
    );
    expect(action.displayLabel, isNot(contains('11111111')));
  });

  test('semantic remove snapshot does not collapse to remove relation', () {
    final action = PendingAction.fromJson({
      'tool_name': 'remove_relation',
      'arguments': {'edge_id': '33333333-3333-3333-3333-333333333333'},
      'presentation': {
        'operation': 'remove_relation',
        'relation_type': 'references',
        'entities': [
          {'role': 'source', 'title': 'Экспериментальная рубрика октября', 'kind': 'task'},
          {'role': 'target', 'title': 'Приглашение_ЮФУ.pdf', 'kind': 'note'},
        ],
        'fields': [],
      },
    });
    expect(
      action.displayLabel,
      'Удалить основание: Экспериментальная рубрика октября -> Приглашение_ЮФУ.pdf',
    );
    expect(action.displayLabel.toLowerCase(), isNot(contains('remove relation')));
  });

  test('legacy action without presentation keeps the old label', () {
    final action = PendingAction.fromJson({
      'tool_name': 'update_task',
      'arguments': {'object_id': '0635adf9-1234-5678-90ab-cdef12345678'},
    });
    expect(action.presentation, isNull);
    expect(action.displayLabel, 'Update task: 0635adf9-1234-5678-90ab-cdef12345678');
  });

  test('set task status proposal label without object id falls back', () {
    final action = PendingAction(
      toolName: 'set_task_status',
      arguments: {'status': 'done'},
    );
    expect(action.displayLabel, 'Set task status: done');
  });

  test('affected object prefers lifecycle status in chip label', () {
    final affected = AssistantAffectedObject(
      objectId: 'id-1',
      title: 'Prepare report',
      kind: 'task',
      state: 'confirmed',
      status: 'done',
    );
    expect(affected.displayLabel, 'task: Prepare report — done');
  });

  test('affected object deleted status chip', () {
    final affected = AssistantAffectedObject(
      objectId: 'id-2',
      title: 'TEST-DELETE',
      kind: 'task',
      state: 'confirmed',
      status: 'deleted',
    );
    expect(affected.displayLabel, 'task: TEST-DELETE — deleted');
  });
}
