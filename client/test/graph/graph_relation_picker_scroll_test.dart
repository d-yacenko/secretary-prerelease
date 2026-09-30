import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('a long relation result list scrolls inside the dialog', (
    tester,
  ) async {
    final posts = <Map<String, dynamic>>[];
    final harness = _harness(resultCount: 22, posts: posts);
    harness.configure();
    await _openDialog(tester, harness, const Size(960, 640));

    await _search(tester, 'результат');

    expect(tester.takeException(), isNull);
    expect(find.text('Поиск объекта'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Создать'), findsOneWidget);
    expect(find.text('Отмена'), findsOneWidget);
    expect(find.byKey(const ValueKey('relation-target-hit-0')), findsOneWidget);

    final list = find.byKey(const ValueKey('relation-target-list'));
    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('relation-target-hit-21')),
      80,
      scrollable: find.descendant(of: list, matching: find.byType(Scrollable)),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);

    await tester.tap(find.byKey(const ValueKey('relation-target-hit-21')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Создать'));
    await tester.pumpAndSettle();

    expect(posts, hasLength(1));
    expect(posts.single['target_id'], 'hit-21');
    expect(posts.single['source_id'], 'source');
    expect(posts.single['type'], 'related_to');
  });

  testWidgets('a short relation result list stays in the dialog', (tester) async {
    final harness = _harness(resultCount: 1);
    harness.configure();
    await _openDialog(tester, harness, const Size(960, 640));

    await _search(tester, 'результат');

    expect(tester.takeException(), isNull);
    expect(find.byKey(const ValueKey('relation-target-hit-0')), findsOneWidget);
    expect(find.text('Результат 01'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Создать'), findsOneWidget);
    final create = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'Создать'),
    );
    expect(create.onPressed, isNull);
  });
}

Future<void> _openDialog(
  WidgetTester tester,
  GraphTestHarness harness,
  Size size,
) async {
  tester.view.physicalSize = size;
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
  final field = find.descendant(
    of: find.byType(AlertDialog),
    matching: find.byType(TextField),
  );
  await tester.enterText(field, query);
  await tester.testTextInput.receiveAction(TextInputAction.done);
  await tester.pumpAndSettle();
}

GraphTestHarness _harness({
  required int resultCount,
  List<Map<String, dynamic>>? posts,
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
          for (var index = 0; index < resultCount; index++)
            graphObjectJson(
              id: 'hit-$index',
              title: 'Результат ${(index + 1).toString().padLeft(2, '0')}',
            ),
        ]);
      }
      if (request.method == 'POST' && request.url.path == '/relations') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        posts?.add(body);
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
            nodes: [
              graphObjectJson(id: 'source', title: 'Источник'),
            ],
          ),
        );
      }
      if (request.url.path == '/graph/task-layout') {
        return jsonUtf8Response({
          'topology_revision': 1,
          'snapshot_revision': 1,
          'algorithm_version': kTaskLayoutAlgorithmVersion,
          'usable': true,
          'centers': [
            {'task_id': 'source', 'world_x': 40, 'world_y': 40},
          ],
        });
      }
      return jsonUtf8Response({}, statusCode: 404);
    }),
  );
}
