import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';

import 'graph_test_harness.dart';

void main() {
  testWidgets('single-page People overview omits window controls', (tester) async {
    final calls = <String>[];
    final harness = await _openPeople(tester, (request) async {
      calls.add(request.url.query);
      return _peoplePage(
        nodes: [_personNode('person-a', 'Ada')],
        windowIndex: 0,
        windowCount: 1,
      );
    });

    expect(harness.graph.windowCount, 1);
    expect(find.byKey(const ValueKey('graph-overview-window-status')), findsNothing);
    expect(find.byKey(const ValueKey('graph-overview-window-next')), findsNothing);
    expect(calls.any((query) => query.contains('window_index=0') || !query.contains('window_index')), isTrue);
  });

  testWidgets('multi-window People overview navigates with People wording', (tester) async {
    final calls = <String>[];
    final harness = await _openPeople(tester, (request) async {
      calls.add(request.url.query);
      final root = request.url.queryParameters['root_id'];
      if (root != null) {
        return _peoplePage(
          rootId: root,
          nodes: [_personNode(root, root == 'person-a' ? 'Ada' : 'Other')],
          windowIndex: 0,
          windowCount: 1,
        );
      }
      final window = int.parse(request.url.queryParameters['window_index'] ?? '0');
      if (window == 1) {
        return _peoplePage(
          nodes: [_personNode('person-b', 'Bob'), _personNode('person-c', 'Cara')],
          windowIndex: 1,
          windowCount: 3,
          hasPrevious: true,
          hasNext: true,
        );
      }
      if (window == 2) {
        return _peoplePage(
          nodes: [_personNode('person-manual', 'Manual Person')],
          windowIndex: 2,
          windowCount: 3,
          hasPrevious: true,
        );
      }
      return _peoplePage(
        nodes: [_personNode('person-a', 'Ada')],
        windowIndex: 0,
        windowCount: 3,
        hasNext: true,
      );
    });

    expect(find.text('Люди · страница 1 из 3'), findsOneWidget);
    expect(find.byTooltip('Следующие люди'), findsOneWidget);
    expect(find.byTooltip('Предыдущие люди'), findsOneWidget);
    expect(find.text('Ada'), findsWidgets);
    expect(harness.graph.rootId, isNull);

    harness.graph.selectObject('person-a');
    await tester.pumpAndSettle();
    expect(harness.graph.selectedObjectId, 'person-a');

    await tester.tap(find.byKey(const ValueKey('graph-overview-window-next')));
    await tester.pumpAndSettle();
    expect(calls.where((query) => query.contains('window_index=1')), isNotEmpty);
    expect(find.text('Люди · страница 2 из 3'), findsOneWidget);
    expect(find.text('Bob'), findsWidgets);
    expect(find.text('Ada'), findsNothing);
    expect(harness.graph.rootId, isNull);
    expect(harness.graph.selectedObjectId, isNull);

    await tester.tap(find.byKey(const ValueKey('graph-overview-window-previous')));
    await tester.pumpAndSettle();
    expect(calls.where((query) => query.contains('window_index=0')).length, greaterThan(1));
    expect(find.text('Люди · страница 1 из 3'), findsOneWidget);
    expect(find.text('Ada'), findsWidgets);

    await tester.tap(find.byKey(const ValueKey('graph-overview-window-next')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('graph-overview-window-next')));
    await tester.pumpAndSettle();
    expect(find.text('Люди · страница 3 из 3'), findsOneWidget);
    expect(find.text('Manual Person'), findsWidgets);
    expect(harness.graph.rootId, isNull);
  });

  testWidgets('Tasks and People remember independent overview windows', (tester) async {
    tester.view.physicalSize = const Size(1280, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final peopleWindows = <String?>[];
    final taskWindows = <String?>[];
    final harness = GraphTestHarness(
      MockClient((request) async {
        if (request.url.path == '/graph/workspace') {
          taskWindows.add(request.url.queryParameters['window_index']);
          final window = int.parse(request.url.queryParameters['window_index'] ?? '0');
          return jsonUtf8Response({
            ...graphWorkspaceJson(
              nodes: [
                graphObjectJson(
                  id: window == 0 ? 'task-a' : 'task-b',
                  title: window == 0 ? 'Task A' : 'Task B',
                ),
              ],
              truncated: true,
            ),
            'window_index': window,
            'window_count': 2,
            'has_previous_window': window > 0,
            'has_next_window': window < 1,
            'semantic_window_complete': true,
          });
        }
        if (request.url.path == '/graph/people-workspace') {
          peopleWindows.add(request.url.queryParameters['window_index']);
          final window = int.parse(request.url.queryParameters['window_index'] ?? '0');
          return _peoplePage(
            nodes: [
              _personNode(
                window == 0 ? 'person-a' : 'person-b',
                window == 0 ? 'Ada' : 'Bob',
              ),
            ],
            windowIndex: window,
            windowCount: 2,
            hasPrevious: window > 0,
            hasNext: window < 1,
          );
        }
        final common = await _common(request, includeWorkspace: false);
        if (common != null) {
          return common;
        }
        if (request.url.path == '/graph/task-layout') {
          return jsonUtf8Response({
            'algorithm_version': 1,
            'revision': 1,
            'centers': <Map<String, dynamic>>[],
          });
        }
        if (request.url.path == '/graph/task-layout/topology') {
          return jsonUtf8Response({
            'algorithm_version': 1,
            'active_task_ids': <String>[],
          });
        }
        return http.Response('{}', 404);
      }),
    );
    harness.configure();
    await openGraph(tester, harness);
    expect(harness.graph.windowCount, 2);
    expect(find.text('Область 1 из 2'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('graph-overview-window-next')));
    await tester.pumpAndSettle();
    expect(find.text('Область 2 из 2'), findsOneWidget);

    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    expect(find.text('Люди · страница 1 из 2'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('graph-overview-window-next')));
    await tester.pumpAndSettle();
    expect(find.text('Люди · страница 2 из 2'), findsOneWidget);

    await tester.tap(find.text('Задачи'));
    await tester.pumpAndSettle();
    expect(find.text('Область 2 из 2'), findsOneWidget);
    expect(find.text('Task B'), findsWidgets);

    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    expect(find.text('Люди · страница 2 из 2'), findsOneWidget);
    expect(find.text('Bob'), findsWidgets);
    expect(peopleWindows.where((value) => value == '1').length, greaterThanOrEqualTo(2));
    expect(taskWindows.where((value) => value == '1').length, greaterThanOrEqualTo(2));
  });

  testWidgets('People refresh keeps the current page and OOR falls back to page 0', (
    tester,
  ) async {
    var allowPageTwo = true;
    final harness = await _openPeople(tester, (request) async {
      final window = int.parse(request.url.queryParameters['window_index'] ?? '0');
      if (window == 2 && !allowPageTwo) {
        return jsonUtf8Response(
          {'detail': 'people window index is out of range'},
          statusCode: 422,
        );
      }
      if (window == 1 || window == 2) {
        return _peoplePage(
          nodes: [_personNode('person-b', 'Bob')],
          windowIndex: allowPageTwo ? window : 0,
          windowCount: allowPageTwo ? 3 : 1,
          hasPrevious: allowPageTwo && window > 0,
          hasNext: allowPageTwo && window < 2,
        );
      }
      return _peoplePage(
        nodes: [_personNode('person-a', 'Ada')],
        windowIndex: 0,
        windowCount: allowPageTwo ? 3 : 1,
        hasNext: allowPageTwo,
      );
    });

    await tester.tap(find.byKey(const ValueKey('graph-overview-window-next')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('graph-overview-window-next')));
    await tester.pumpAndSettle();
    expect(harness.graph.windowIndex, 2);

    await harness.graph.refreshCurrentWorkspace();
    await tester.pumpAndSettle();
    expect(harness.graph.windowIndex, 2);
    expect(find.text('Bob'), findsWidgets);

    allowPageTwo = false;
    await harness.graph.refreshCurrentWorkspace();
    await tester.pumpAndSettle();
    expect(harness.graph.windowIndex, 0);
    expect(find.text('Ada'), findsWidgets);
    expect(harness.graph.errorMessage, isNull);
  });

  testWidgets('People search still finds a Person outside the current overview page', (
    tester,
  ) async {
    final harness = await _openPeople(tester, (request) async {
      final query = request.url.queryParameters['q'];
      final root = request.url.queryParameters['root_id'];
      final window = request.url.queryParameters['window_index'];
      if (query == 'Manual Person') {
        expect(window, isNull);
        return _peoplePage(
          nodes: [_personNode('person-manual', 'Manual Person')],
          windowIndex: 0,
          windowCount: 1,
        );
      }
      if (root == 'person-manual') {
        expect(window, isNull);
        return _peoplePage(
          rootId: 'person-manual',
          nodes: [_personNode('person-manual', 'Manual Person')],
          windowIndex: 0,
          windowCount: 1,
        );
      }
      return _peoplePage(
        nodes: [_personNode('person-a', 'Ada')],
        windowIndex: 0,
        windowCount: 2,
        hasNext: true,
      );
    });

    await tester.enterText(find.byType(TextField).first, 'Manual Person');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Manual Person').last);
    await tester.pumpAndSettle();
    expect(harness.graph.rootId, 'person-manual');
    expect(find.text('Manual Person'), findsWidgets);
  });
}

Future<GraphTestHarness> _openPeople(
  WidgetTester tester,
  Future<http.Response> Function(http.Request request) peopleHandler,
) async {
  tester.view.physicalSize = const Size(1280, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final harness = GraphTestHarness(
    MockClient((request) async {
      final common = await _common(request);
      if (common != null) {
        return common;
      }
      if (request.url.path == '/graph/people-workspace') {
        return peopleHandler(request);
      }
      if (request.url.path == '/graph/task-layout') {
        return jsonUtf8Response({
          'algorithm_version': 1,
          'revision': 1,
          'centers': <Map<String, dynamic>>[],
        });
      }
      if (request.url.path == '/graph/task-layout/topology') {
        return jsonUtf8Response({
          'algorithm_version': 1,
          'active_task_ids': <String>[],
        });
      }
      return http.Response('{}', 404);
    }),
  );
  harness.configure();
  await openGraph(tester, harness);
  await tester.tap(find.text('Люди'));
  await tester.pumpAndSettle();
  return harness;
}

Future<http.Response?> _common(
  http.Request request, {
  bool includeWorkspace = true,
}) async {
  if (request.url.path == '/notifications') {
    return jsonUtf8Response({'notifications': []});
  }
  if (request.url.path == '/today') {
    return jsonUtf8Response({
      'date': '2026-08-28',
      'timezone': 'Europe/Amsterdam',
      'day_start': '2026-08-28T00:00:00+02:00',
      'tasks': [],
      'calendar_events': [],
      'notifications': [],
    });
  }
  if (request.url.path == '/search/facets') {
    return jsonUtf8Response({'kinds': [], 'providers': []});
  }
  if (includeWorkspace && request.url.path == '/graph/workspace') {
    return jsonUtf8Response(
      graphWorkspaceJson(nodes: [graphObjectJson(id: 'task-1', title: 'Graph task')]),
    );
  }
  return null;
}

Map<String, dynamic> _personNode(String id, String title) {
  return graphObjectJson(id: id, title: title, kind: 'person');
}

http.Response _peoplePage({
  required List<Map<String, dynamic>> nodes,
  required int windowIndex,
  required int windowCount,
  bool hasPrevious = false,
  bool hasNext = false,
  String? rootId,
}) {
  return jsonUtf8Response({
    ...graphWorkspaceJson(
      rootId: rootId,
      nodes: nodes,
      truncated: windowCount > 1,
    ),
    'window_index': windowIndex,
    'window_count': windowCount,
    'has_previous_window': hasPrevious,
    'has_next_window': hasNext,
    'people': [
      for (final node in nodes)
        {
          'person_id': node['id'],
          'title': node['title'],
          'salience_score': 1,
          'identities': const [],
          'routes': const [],
          'identity_conflict': false,
          'open_task_count': 0,
          'recent_communication_count': 0,
          'task_involvement': const [],
          'recent_communications': const [],
        },
    ],
  });
}
