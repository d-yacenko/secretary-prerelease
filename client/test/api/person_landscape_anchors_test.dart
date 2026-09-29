import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';

void main() {
  test('person presentation keeps landscape task anchors exactly', () {
    final parsed = PersonPresentation.fromJson({
      'person_id': 'person-1',
      'landscape_task_ids': ['task-b', 'task-a'],
      'landscape_task_ids_complete': false,
    });
    expect(parsed.landscapeTaskIds, ['task-b', 'task-a']);
    expect(parsed.landscapeTaskIdsComplete, isFalse);
  });

  test('omitted landscape anchors stay empty and complete', () {
    final parsed = PersonPresentation.fromJson({'person_id': 'person-1'});
    expect(parsed.landscapeTaskIds, isEmpty);
    expect(parsed.landscapeTaskIdsComplete, isTrue);
  });
}
