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
