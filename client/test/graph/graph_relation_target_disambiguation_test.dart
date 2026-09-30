import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('duplicate task targets show confirmed parents and keep ids', (
    tester,
  ) async {
    final posts = <Map<String, dynamic>>[];
    final profilePaths = <String>[];
    final harness = _harness(posts: posts, profilePaths: profilePaths);
    harness.configure();
    await _openDialog(tester, harness);

    await _search(tester, 'обучение');
    expect(profilePaths, hasLength(4));
    expect(
      profilePaths,
      containsAll([
        '/tasks/work/profile',
        '/tasks/academic/profile',
        '/tasks/orphan/profile',
        '/tasks/proposed/profile',
      ]),
    );
    expect(profilePaths, isNot(contains('/tasks/unique/profile')));
    expect(_dialogText('Обучение (Основная работа)'), findsOneWidget);
    expect(_dialogText('Обучение (Академическая деятельность)'), findsOneWidget);
    expect(_dialogText('Обучение (без родителя)'), findsNWidgets(2));
    expect(_dialogText('Уникальная'), findsOneWidget);
    expect(_dialogText('Уникальная ('), findsNothing);
    expect(find.textContaining('Нельзя'), findsNothing);
    expect(find.textContaining('Выдуманный'), findsNothing);

    await tester.tap(find.byKey(const ValueKey('relation-target-academic')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Создать'));
    await tester.pumpAndSettle();

    expect(posts, hasLength(1));
    expect(posts.single['source_id'], 'source');
    expect(posts.single['target_id'], 'academic');
    expect(posts.single['type'], 'related_to');
    expect(harness.graph.nodeById('academic')?.title, isNot('Обучение (Академическая деятельность)'));
  });

  testWidgets('selecting the other duplicate uses that task id', (tester) async {
    final posts = <Map<String, dynamic>>[];
    final harness = _harness(posts: posts);
    harness.configure();
    await _openDialog(tester, harness);
    await _search(tester, 'обучение');

    await tester.tap(find.byKey(const ValueKey('relation-target-work')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Создать'));
    await tester.pumpAndSettle();

    expect(posts.single['target_id'], 'work');
  });
}

Finder _dialogText(String text) {
  return find.descendant(of: find.byType(AlertDialog), matching: find.text(text));
}

Future<void> _openDialog(WidgetTester tester, GraphTestHarness harness) async {
  tester.view.physicalSize = const Size(1280, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await openGraph(tester, harness);
  harness.graph.selectObject('source');
  await tester.pumpAndSettle();
  await tester.tap(find.text('Добавить связь'));
  await tester.pumpAndSettle();
}

Future<void> _search(WidgetTester tester, String query) async {
  await tester.enterText(
    find.descendant(of: find.byType(AlertDialog), matching: find.byType(TextField)),
    query,
  );
  await tester.testTextInput.receiveAction(TextInputAction.done);
  await tester.pumpAndSettle();
}

GraphTestHarness _harness({
  List<Map<String, dynamic>>? posts,
  List<String>? profilePaths,
}) {
  return GraphTestHarness(
    MockClient((request) async {
      if (request.url.path == '/notifications') {
        return jsonUtf8Response({'notifications': []});
      }
      if (request.url.path == '/today') {
        return jsonUtf8Response({
          'date': '2026-08-28',
          'timezone': 'Europe/Amsterdam',
          'day_start': '2026-08-28T08:00:00+02:00',
          'tasks': [],
          'calendar_events': [],
          'notifications': [],
        });
      }
      if (request.url.path == '/search') {
        return jsonUtf8Response([
          graphObjectJson(id: 'work', title: 'Обучение'),
          graphObjectJson(id: 'academic', title: 'Обучение'),
          graphObjectJson(id: 'orphan', title: 'Обучение'),
          graphObjectJson(id: 'proposed', title: 'Обучение'),
          graphObjectJson(id: 'unique', title: 'Уникальная'),
        ]);
      }
      if (request.url.path == '/tasks/work/profile') {
        profilePaths?.add(request.url.path);
        return jsonUtf8Response(_profile('work', _parent('main', 'Основная работа', 'confirmed')));
      }
      if (request.url.path == '/tasks/academic/profile') {
        profilePaths?.add(request.url.path);
        return jsonUtf8Response(
          _profile('academic', _parent('study', 'Академическая деятельность', 'confirmed')),
        );
      }
      if (request.url.path == '/tasks/orphan/profile') {
        profilePaths?.add(request.url.path);
        return jsonUtf8Response(_profile('orphan', null));
      }
      if (request.url.path == '/tasks/proposed/profile') {
        profilePaths?.add(request.url.path);
        return jsonUtf8Response(
          _profile('proposed', _parent('nope', 'Нельзя', 'proposed')),
        );
      }
      if (request.method == 'POST' && request.url.path == '/relations') {
        posts?.add(jsonDecode(request.body) as Map<String, dynamic>);
        final body = posts!.last;
        return jsonUtf8Response({
          'created': true,
          'edge': {
            'id': 'edge-new',
            'source_id': body['source_id'],
            'target_id': body['target_id'],
            'type': body['type'],
            'origin': 'user',
            'state': 'confirmed',
            'confidence': null,
            'metadata': {},
            'created_at': '2026-01-01T00:00:00Z',
            'updated_at': '2026-01-01T00:00:00Z',
          },
        });
      }
      if (request.url.path == '/graph/workspace') {
        return jsonUtf8Response(
          graphWorkspaceJson(
            nodes: [graphObjectJson(id: 'source', title: 'Источник')],
          ),
        );
      }
      if (request.url.path == '/search/facets') {
        return jsonUtf8Response({
          'kinds': [
            {'value': 'task', 'count': 1},
          ],
          'providers': [],
        });
      }
      return jsonUtf8Response({}, statusCode: 404);
    }),
  );
}

Map<String, dynamic> _profile(String taskId, Map<String, dynamic>? parent) {
  return {
    'task': graphObjectJson(id: taskId, title: 'Обучение'),
    'status': 'open',
    'start_at': null,
    'due_at': null,
    'planned_start_at': null,
    'planned_end_at': null,
    'requested_by': const [],
    'delegated_to': const [],
    'waiting_on': const [],
    'involves': const [],
    'depends_on': const [],
    'dependent_tasks': const [],
    if (parent != null) 'parent_task': parent,
    'child_tasks': const [],
    'evidence': const [],
  };
}

Map<String, dynamic> _parent(String id, String title, String state) {
  return {
    'edge_id': 'edge-$id',
    'object_id': id,
    'title': title,
    'kind': 'task',
    'edge_state': state,
    'edge_origin': 'user',
  };
}
