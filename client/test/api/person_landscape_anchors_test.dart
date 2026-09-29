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

  test('people workspace keeps landscape task context exactly', () {
    final parsed = GraphWorkspaceOut.fromJson({
      'seed_ids': <String>[],
      'nodes': <Map<String, dynamic>>[],
      'edges': <Map<String, dynamic>>[],
      'truncated': false,
      'landscape_task_context_complete': false,
      'landscape_tasks': [
        {
          'id': 'task-b',
          'kind': 'task',
          'title': 'B',
          'origin': 'user',
          'state': 'confirmed',
          'created_at': '2026-01-01T00:00:00Z',
          'updated_at': '2026-01-01T00:00:00Z',
        },
        {
          'id': 'task-a',
          'kind': 'task',
          'title': 'A',
          'origin': 'user',
          'state': 'confirmed',
          'created_at': '2026-01-01T00:00:00Z',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ],
      'landscape_task_edges': [
        {
          'id': 'edge-2',
          'source_id': 'task-a',
          'target_id': 'task-b',
          'type': 'part_of',
          'origin': 'user',
          'state': 'confirmed',
          'created_at': '2026-01-01T00:00:00Z',
          'updated_at': '2026-01-01T00:00:00Z',
        },
      ],
    });
    expect(parsed.landscapeTaskContextComplete, isFalse);
    expect(parsed.landscapeTasks.map((item) => item.id), ['task-b', 'task-a']);
    expect(parsed.landscapeTasks.map((item) => item.title), ['B', 'A']);
    expect(parsed.landscapeTaskEdges.single.id, 'edge-2');
    expect(parsed.landscapeTaskEdges.single.type, 'part_of');
  });

  test('omitted landscape task context stays empty and complete', () {
    final parsed = GraphWorkspaceOut.fromJson({
      'seed_ids': <String>[],
      'nodes': <Map<String, dynamic>>[],
      'edges': <Map<String, dynamic>>[],
      'truncated': false,
    });
    expect(parsed.landscapeTasks, isEmpty);
    expect(parsed.landscapeTaskEdges, isEmpty);
    expect(parsed.landscapeTaskContextComplete, isTrue);
  });
}
