import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/people_landscape.dart';

void main() {
  const tasks = {
    'task-a': Offset(10, 20),
    'task-b': Offset(30, 60),
    'task-c': Offset(90, 0),
  };

  test('one Task anchors the Person to that Task top-left', () {
    final placed = projectPeopleFromTasks(
      personIds: const ['person-ada'],
      taskPositions: tasks,
      taskIdsByPerson: const {
        'person-ada': ['task-a'],
      },
    );
    expect(placed, {'person-ada': tasks['task-a']});
  });

  test('two Tasks use the unweighted midpoint', () {
    final placed = projectPeopleFromTasks(
      personIds: const ['person-ada'],
      taskPositions: tasks,
      taskIdsByPerson: const {
        'person-ada': ['task-a', 'task-b'],
      },
    );
    expect(placed['person-ada'], const Offset(20, 40));
  });

  test('three Tasks use the arithmetic centroid', () {
    final placed = projectPeopleFromTasks(
      personIds: const ['person-ada'],
      taskPositions: tasks,
      taskIdsByPerson: const {
        'person-ada': ['task-c', 'task-a', 'task-b'],
      },
    );
    expect(placed['person-ada'], const Offset(130 / 3, 80 / 3));
  });

  test('duplicate Task ids from extra roles do not change the centroid', () {
    final once = projectPeopleFromTasks(
      personIds: const ['person-ada'],
      taskPositions: tasks,
      taskIdsByPerson: const {
        'person-ada': ['task-a', 'task-b'],
      },
    );
    final twice = projectPeopleFromTasks(
      personIds: const ['person-ada'],
      taskPositions: tasks,
      taskIdsByPerson: const {
        'person-ada': ['task-a', 'task-a', 'task-b', 'task-b'],
      },
    );
    expect(twice, once);
    expect(twice['person-ada'], isNot(tasks['task-a']));
  });

  test('missing Task ids are ignored and an unanchored Person is omitted', () {
    final placed = projectPeopleFromTasks(
      personIds: const ['person-ada', 'person-none', 'person-missing'],
      taskPositions: tasks,
      taskIdsByPerson: const {
        'person-ada': ['missing', 'task-b', 'also-missing'],
        'person-none': ['missing'],
        'person-missing': [],
      },
    );
    expect(placed, {'person-ada': tasks['task-b']});
  });

  test('shared base points separate deterministically and ignore input order', () {
    const links = {
      'person-c': ['task-a', 'task-a'],
      'person-a': ['task-a'],
      'person-b': ['task-a'],
    };
    final forward = projectPeopleFromTasks(
      personIds: const ['person-c', 'person-b', 'person-a'],
      taskPositions: tasks,
      taskIdsByPerson: links,
    );
    final reversed = projectPeopleFromTasks(
      personIds: const ['person-a', 'person-b', 'person-c'],
      taskPositions: tasks,
      taskIdsByPerson: const {
        'person-b': ['task-a'],
        'person-a': ['task-a'],
        'person-c': ['task-a'],
      },
    );
    expect(reversed, forward);
    expect(forward['person-a'], tasks['task-a']);
    expect(forward['person-b'], isNot(tasks['task-a']));
    expect(forward['person-c'], isNot(tasks['task-a']));
    expect(forward['person-b'], isNot(forward['person-c']));
    final positions = forward.values.toList();
    for (var i = 0; i < positions.length; i++) {
      for (var j = i + 1; j < positions.length; j++) {
        expect(GraphLayout.nodeRectsOverlap(positions[i], positions[j]), isFalse);
      }
    }
  });
}
