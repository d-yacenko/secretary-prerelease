import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:personal_secretary/ui/object_bookmark.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('relation targets use one dense identity row', (tester) async {
    final harness = _harness(
      results: _mixedResults(),
      onBookmarks: (_) => {'file': 'red'},
    );
    harness.configure();
    await _openDialog(tester, harness);
    await _search(tester, 'объект');

    expect(tester.takeException(), isNull);
    expect(find.byKey(const ValueKey('relation-target-finite')), findsOneWidget);
    expect(find.byKey(const ValueKey('relation-target-direction')), findsOneWidget);
    expect(find.byKey(const ValueKey('relation-target-gmail')), findsOneWidget);
    expect(find.byKey(const ValueKey('relation-target-yandex')), findsOneWidget);
    expect(find.byKey(const ValueKey('relation-target-file')), findsOneWidget);
    expect(
      find.descendant(of: find.byType(AlertDialog), matching: find.text('Задача')),
      findsNothing,
    );
    expect(
      find.descendant(of: find.byType(AlertDialog), matching: find.text('Письмо')),
      findsNothing,
    );
    expect(
      find.descendant(of: find.byType(AlertDialog), matching: find.text('Файл')),
      findsNothing,
    );
    expect(find.byKey(const ValueKey('relation-target-kind-finite')), findsOneWidget);
    expect(find.byKey(const ValueKey('relation-target-ongoing-direction')), findsOneWidget);
    expect(find.byIcon(Icons.all_inclusive), findsOneWidget);
    expect(find.byKey(const Key('provider_icon_gmail')), findsOneWidget);
    expect(find.byKey(const Key('provider_icon_yandex_mail')), findsOneWidget);
    expect(find.byKey(const ValueKey('relation-target-bookmark-file')), findsOneWidget);
    expect(find.byKey(const ValueKey('relation-target-bookmark-finite')), findsNothing);
    final glyph = tester.widget<ObjectBookmarkGlyph>(
      find.byKey(const ValueKey('relation-target-bookmark-file')),
    );
    expect(
      glyph.fillColor,
      bookmarkTokenColor('red', Theme.of(tester.element(find.byType(AlertDialog))).colorScheme),
    );
    expect(
      tester.getSize(find.byKey(const ValueKey('relation-target-finite'))).height,
      lessThan(56),
    );
    expect(tester.getSize(find.byType(AlertDialog)).height, lessThanOrEqualTo(900));
  });

  testWidgets('case-different course tasks stay distinguishable in the picker', (
    tester,
  ) async {
    final harness = _harness(results: _courseResults(), profiles: true);
    harness.configure();
    await _openDialog(tester, harness);
    await _search(tester, 'курсы');

    expect(find.text('Создание курсов (Направление преподавания)'), findsOneWidget);
    expect(find.text('создание курсов (Samsung)'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('relation-target-samsung')));
    await tester.pumpAndSettle();
    final create = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'Создать'),
    );
    expect(create.onPressed, isNotNull);
  });

  testWidgets('a long relation picker scrolls inside the viewport', (tester) async {
    final harness = _harness(results: _manyResults(25));
    harness.configure();
    await _openDialog(tester, harness);
    await _search(tester, 'список');

    expect(tester.takeException(), isNull);
    expect(tester.getSize(find.byType(AlertDialog)).height, lessThanOrEqualTo(900));
    final list = find.byKey(const ValueKey('relation-target-list'));
    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('relation-target-hit-24')),
      80,
      scrollable: find.descendant(of: list, matching: find.byType(Scrollable)),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.tap(find.byKey(const ValueKey('relation-target-hit-24')));
    await tester.pumpAndSettle();
    expect(
      tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Создать')).onPressed,
      isNotNull,
    );
  });

  testWidgets('bookmark reconciliation is one batch and failure stays usable', (
    tester,
  ) async {
    final batches = <List<String>>[];
    final harness = _harness(
      results: _mixedResults(),
      onBookmarks: (ids) {
        batches.add(ids);
        return {'file': 'blue'};
      },
    );
    harness.configure();
    await _openDialog(tester, harness);
    await _search(tester, 'объект');
    final resultBatches = batches.where((ids) => ids.contains('file')).toList();
    expect(resultBatches, hasLength(1));
    expect(
      resultBatches.single,
      containsAll(['finite', 'direction', 'gmail', 'yandex', 'file']),
    );
    expect(find.byKey(const ValueKey('relation-target-bookmark-file')), findsOneWidget);
  });

  testWidgets('bookmark fetch failure leaves relation rows usable', (tester) async {
    final harness = _harness(results: _mixedResults(), bookmarksFail: true);
    harness.configure();
    await _openDialog(tester, harness);
    await _search(tester, 'объект');
    expect(tester.takeException(), isNull);
    await tester.tap(find.byKey(const ValueKey('relation-target-finite')));
    await tester.pumpAndSettle();
    expect(
      tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Создать')).onPressed,
      isNotNull,
    );
  });
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

List<Map<String, dynamic>> _mixedResults() {
  return [
    graphObjectJson(id: 'finite', title: 'Конечная задача'),
    graphObjectJson(
      id: 'direction',
      title: 'Направление',
      completionMode: 'ongoing',
    ),
    graphObjectJson(id: 'gmail', title: 'Письмо Google', kind: 'email', provider: 'gmail'),
    graphObjectJson(
      id: 'yandex',
      title: 'Письмо Яндекс',
      kind: 'email',
      provider: 'yandex_mail',
    ),
    graphObjectJson(id: 'file', title: 'Файл отчёта', kind: 'file'),
  ];
}

List<Map<String, dynamic>> _courseResults() {
  return [
    graphObjectJson(id: 'teaching', title: 'Создание курсов'),
    graphObjectJson(id: 'samsung', title: 'создание курсов'),
  ];
}

List<Map<String, dynamic>> _manyResults(int count) {
  return [
    for (var index = 0; index < count; index++)
      graphObjectJson(
        id: 'hit-$index',
        title: 'Кандидат ${(index + 1).toString().padLeft(2, '0')}',
      ),
  ];
}

GraphTestHarness _harness({
  required List<Map<String, dynamic>> results,
  bool profiles = false,
  bool bookmarksFail = false,
  Map<String, String> Function(List<String> ids)? onBookmarks,
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
      if (request.url.path == '/graph/workspace') {
        return jsonUtf8Response(
          graphWorkspaceJson(nodes: [graphObjectJson(id: 'source', title: 'Источник')]),
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
      if (request.url.path == '/search') {
        return jsonUtf8Response(results);
      }
      if (request.method == 'POST' && request.url.path == '/object-bookmarks/by-objects') {
        if (bookmarksFail) {
          return jsonUtf8Response({'detail': 'unavailable'}, statusCode: 500);
        }
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        final ids = (body['object_ids'] as List<dynamic>).cast<String>();
        final colors = onBookmarks?.call(ids) ?? const <String, String>{};
        return jsonUtf8Response({
          'objects': {
            for (final entry in colors.entries) entry.key: {'color': entry.value},
          },
        });
      }
      if (profiles && request.url.path == '/tasks/teaching/profile') {
        return jsonUtf8Response(_profile('teaching', 'Создание курсов', 'Направление преподавания'));
      }
      if (profiles && request.url.path == '/tasks/samsung/profile') {
        return jsonUtf8Response(_profile('samsung', 'создание курсов', 'Samsung'));
      }
      return jsonUtf8Response({}, statusCode: 404);
    }),
  );
}

Map<String, dynamic> _profile(String taskId, String title, String parentTitle) {
  return {
    'task': graphObjectJson(id: taskId, title: title),
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
    'parent_task': {
      'edge_id': 'edge-$taskId',
      'object_id': 'parent-$taskId',
      'title': parentTitle,
      'kind': 'task',
      'edge_state': 'confirmed',
      'edge_origin': 'user',
    },
    'child_tasks': const [],
    'evidence': const [],
  };
}
