import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('task relation dialog offers part_of as child to parent', (tester) async {
    final searches = <Map<String, String>>[];
    final posts = <Map<String, dynamic>>[];
    var rootedRefreshes = 0;
    final harness = _harness(
      searches: searches,
      posts: posts,
      onRootedRefresh: () => rootedRefreshes++,
    );
    harness.configure();
    await _openDialog(tester, harness, 'child');

    expect(
      find.text('Выбранная задача входит в выбранную родительскую задачу.'),
      findsNothing,
    );
    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    expect(find.text('Входит в'), findsWidgets);
    expect(find.text('Связано с'), findsWidgets);
    expect(find.text('Ссылается на'), findsWidgets);
    expect(find.text('Зависит от'), findsWidgets);

    await tester.tap(find.text('Входит в').last);
    await tester.pumpAndSettle();
    expect(
      find.text('Выбранная задача входит в выбранную родительскую задачу.'),
      findsOneWidget,
    );

    await _search(tester, 'parent');
    expect(searches.single['kind'], 'task');
    expect(_dialogText('Дочерняя'), findsNothing);
    expect(_dialogText('Родитель'), findsOneWidget);
    expect(_dialogTile('Заметка'), findsNothing);

    await tester.tap(_dialogText('Родитель'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Создать'));
    await tester.pumpAndSettle();

    expect(posts, hasLength(1));
    expect(posts.single['source_id'], 'child');
    expect(posts.single['target_id'], 'parent');
    expect(posts.single['type'], 'part_of');
    expect(rootedRefreshes, 1);
    expect(harness.graph.shouldFitAfterLayout, isFalse);
    expect(find.textContaining('входит в'), findsWidgets);
  });

  testWidgets('non-task source does not offer part_of', (tester) async {
    final harness = _harness();
    harness.configure();
    await _openDialog(tester, harness, 'note');

    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    expect(find.text('Входит в'), findsNothing);
    expect(find.text('Связано с'), findsWidgets);
    expect(find.text('Ссылается на'), findsWidgets);
    expect(find.text('Зависит от'), findsWidgets);
  });

  testWidgets('entering part_of clears a non-task target and search results', (
    tester,
  ) async {
    final searches = <Map<String, String>>[];
    final harness = _harness(searches: searches);
    harness.configure();
    await _openDialog(tester, harness, 'child');

    await _search(tester, 'note');
    expect(searches.single.containsKey('kind'), isFalse);
    await tester.tap(_dialogTile('Заметка'));
    await tester.pumpAndSettle();
    expect(
      tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Создать')).onPressed,
      isNotNull,
    );

    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Входит в').last);
    await tester.pumpAndSettle();

    expect(_dialogTile('Заметка'), findsNothing);
    expect(
      tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Создать')).onPressed,
      isNull,
    );

    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Связано с').last);
    await tester.pumpAndSettle();
    expect(
      find.text('Выбранная задача входит в выбранную родительскую задачу.'),
      findsNothing,
    );
    expect(_dialogTile('Заметка'), findsNothing);
  });

  testWidgets('part_of validation error is shown without another request', (tester) async {
    final posts = <Map<String, dynamic>>[];
    final harness = _harness(posts: posts, rejectPartOf: true);
    harness.configure();
    await _openDialog(tester, harness, 'child');
    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Входит в').last);
    await tester.pumpAndSettle();
    await _search(tester, 'parent');
    await tester.tap(_dialogText('Родитель'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Создать'));
    await tester.pumpAndSettle();

    expect(posts, [
      {'source_id': 'child', 'target_id': 'parent', 'type': 'part_of'},
    ]);
    expect(find.text('Задача уже входит в другую задачу.'), findsOneWidget);
    expect(harness.graph.edges.where((edge) => edge.type == 'part_of'), isEmpty);
  });
}

Finder _dialogText(String text) {
  return find.descendant(of: find.byType(AlertDialog), matching: find.text(text));
}

Finder _dialogTile(String text) {
  return find.descendant(
    of: find.byType(AlertDialog),
    matching: find.widgetWithText(ListTile, text),
  );
}

Future<void> _openDialog(WidgetTester tester, GraphTestHarness harness, String objectId) async {
  tester.view.physicalSize = const Size(1280, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await openGraph(tester, harness);
  harness.graph.selectObject(objectId);
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
  List<Map<String, String>>? searches,
  List<Map<String, dynamic>>? posts,
  void Function()? onRootedRefresh,
  bool rejectPartOf = false,
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
        searches?.add(request.url.queryParameters);
        final kind = request.url.queryParameters['kind'];
        if (kind == 'task') {
          return jsonUtf8Response([
            graphObjectJson(id: 'child', title: 'Дочерняя'),
            graphObjectJson(id: 'parent', title: 'Родитель'),
            graphObjectJson(id: 'note', title: 'Заметка', kind: 'note'),
          ]);
        }
        return jsonUtf8Response([
          graphObjectJson(id: 'note', title: 'Заметка', kind: 'note'),
        ]);
      }
      if (request.method == 'POST' && request.url.path == '/relations') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        posts?.add(body);
        if (rejectPartOf && body['type'] == 'part_of') {
          return jsonUtf8Response(
            {'detail': 'Задача уже входит в другую задачу.'},
            statusCode: 422,
          );
        }
        return jsonUtf8Response({
          'created': true,
          'edge': {
            'id': 'edge-part',
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
        final rootId = request.url.queryParameters['root_id'];
        if (rootId != null) {
          onRootedRefresh?.call();
        }
        return jsonUtf8Response(
          graphWorkspaceJson(
            rootId: rootId,
            nodes: [
              graphObjectJson(id: 'child', title: 'Дочерняя'),
              graphObjectJson(id: 'parent', title: 'Родитель'),
              graphObjectJson(id: 'note', title: 'Заметка', kind: 'note'),
            ],
            edges: rootId == null
                ? const []
                : [
                    {
                      'id': 'edge-part',
                      'source_id': 'child',
                      'target_id': 'parent',
                      'type': 'part_of',
                      'origin': 'user',
                      'state': 'confirmed',
                      'confidence': null,
                      'metadata': {},
                      'created_at': '2026-01-01T00:00:00Z',
                      'updated_at': '2026-01-01T00:00:00Z',
                    },
                  ],
          ),
        );
      }
      return jsonUtf8Response({}, statusCode: 404);
    }),
  );
}
