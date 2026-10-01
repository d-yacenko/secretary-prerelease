import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/relation_target_label.dart';

import 'graph_test_harness.dart';

void main() {
  test('duplicate task titles use confirmed part_of parents', () {
    final work = _task('work', 'Обучение');
    final academic = _task('academic', 'Обучение');
    final unique = _task('unique', 'Уникальная');
    final note = _task('note', 'Обучение', kind: 'note');
    final results = [work, academic, unique, note];

    expect(
      relationTargetLabel(
        object: work,
        results: results,
        confirmedParentTitleByTaskId: {'work': 'Основная работа'},
      ),
      'Обучение (Основная работа)',
    );
    expect(
      relationTargetLabel(
        object: academic,
        results: results,
        confirmedParentTitleByTaskId: {'academic': 'Академическая деятельность'},
      ),
      'Обучение (Академическая деятельность)',
    );
    expect(
      relationTargetLabel(
        object: unique,
        results: results,
        confirmedParentTitleByTaskId: {'unique': 'Не показывать'},
      ),
      'Уникальная',
    );
    expect(
      relationTargetLabel(
        object: note,
        results: results,
        confirmedParentTitleByTaskId: {},
      ),
      'Обучение',
    );
  });

  test('missing confirmed parent is honest and proposed is ignored', () {
    final orphan = _task('orphan', 'Обучение');
    final proposed = _task('proposed', 'Обучение');
    final rejected = _task('rejected', 'Обучение');
    final results = [orphan, proposed, rejected];

    expect(confirmedPartOfParentTitle(null), isNull);
    expect(
      confirmedPartOfParentTitle(_parent('Нельзя', 'proposed')),
      isNull,
    );
    expect(
      confirmedPartOfParentTitle(_parent('Нельзя', 'rejected')),
      isNull,
    );
    expect(
      confirmedPartOfParentTitle(_parent('Основная работа', 'confirmed')),
      'Основная работа',
    );
    expect(
      confirmedPartOfParentTitle(_parent('   ', 'confirmed')),
      isNull,
    );

    for (final task in results) {
      expect(
        relationTargetLabel(
          object: task,
          results: results,
          confirmedParentTitleByTaskId: {task.id: null},
        ),
        'Обучение (без родителя)',
      );
    }
  });

  test('visually equivalent task titles share a parent suffix', () {
    final teaching = _task('teaching', 'Создание курсов');
    final spaced = _task('spaced', 'создание   курсов');
    final padded = _task('padded', '  Создание   курсов ');
    final other = _task('other', 'Другая задача');
    final results = [teaching, spaced, padded, other];
    final stored = results.map((item) => item.title).toList();

    expect(
      relationTargetLabel(
        object: teaching,
        results: results,
        confirmedParentTitleByTaskId: {'teaching': 'Направление А'},
      ),
      'Создание курсов (Направление А)',
    );
    expect(
      relationTargetLabel(
        object: spaced,
        results: results,
        confirmedParentTitleByTaskId: {'spaced': 'Направление Б'},
      ),
      'создание   курсов (Направление Б)',
    );
    expect(
      relationTargetLabel(
        object: padded,
        results: results,
        confirmedParentTitleByTaskId: {'padded': null},
      ),
      '  Создание   курсов  (без родителя)',
    );
    expect(
      relationTargetLabel(
        object: other,
        results: results,
        confirmedParentTitleByTaskId: {'other': 'Скрытый родитель'},
      ),
      'Другая задача',
    );
    expect(results.map((item) => item.id).toSet(), {
      'teaching',
      'spaced',
      'padded',
      'other',
    });
    expect(results.map((item) => item.title).toList(), stored);
    expect(
      confirmedPartOfParentTitle(_parent('Направление А', 'proposed')),
      isNull,
    );
    expect(
      confirmedPartOfParentTitle(_parent('Направление А', 'rejected')),
      isNull,
    );
  });
}

SecretaryObject _task(String id, String title, {String kind = 'task'}) {
  return SecretaryObject.fromJson(graphObjectJson(id: id, title: title, kind: kind));
}

TaskLinkItem _parent(String title, String state) {
  return TaskLinkItem(
    edgeId: 'edge',
    objectId: 'parent',
    title: title,
    kind: 'task',
    edgeState: state,
    edgeOrigin: 'user',
  );
}
