import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/graph/graph_workspace_screen.dart';

import 'graph_test_harness.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('healthy Tasks and People keep one world point and scale', (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = _harness(
      taskWindows: [
        [graphObjectJson(id: 'task-a', title: 'Task A')],
        [graphObjectJson(id: 'task-a', title: 'Task A')],
      ],
    );
    harness.configure();
    await harness.graph.loadOverview();
    await tester.pumpWidget(_screen(harness));
    await tester.pumpAndSettle();

    final scale = _scale(tester);
    final taskPoint = tester.getCenter(find.byKey(const Key('graph_node_task-a')));
    expect(harness.graph.shouldFitAfterLayout, isFalse);

    await harness.graph.setMode(GraphWorkspaceMode.people);
    await tester.pumpAndSettle();

    expect(harness.graph.shouldFitAfterLayout, isFalse);
    expect(_scale(tester), closeTo(scale, 0.001));
    expect(find.byKey(const Key('graph_node_task-a')), findsNothing);
    expect(
      tester.getCenter(find.byKey(const Key('graph_node_person-ada'))),
      offsetMoreOrLessEquals(taskPoint, epsilon: 1.5),
    );

    await harness.graph.setMode(GraphWorkspaceMode.tasks);
    await tester.pumpAndSettle();
    expect(_scale(tester), closeTo(scale, 0.001));
    expect(
      tester.getCenter(find.byKey(const Key('graph_node_task-a'))),
      offsetMoreOrLessEquals(taskPoint, epsilon: 1.5),
    );
  });

  testWidgets('mode switch keeps the Task overview window', (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = _harness(
      taskWindows: [
        [graphObjectJson(id: 'task-a', title: 'Task A')],
        [graphObjectJson(id: 'task-b', title: 'Task B')],
      ],
    );
    harness.configure();
    await harness.graph.loadOverview();
    await tester.pumpWidget(_screen(harness));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('graph-overview-window-next')));
    await tester.pumpAndSettle();
    expect(find.text('Область 2 из 2'), findsOneWidget);

    await harness.graph.setMode(GraphWorkspaceMode.people);
    await tester.pumpAndSettle();
    await harness.graph.setMode(GraphWorkspaceMode.tasks);
    await tester.pumpAndSettle();
    expect(find.text('Область 2 из 2'), findsOneWidget);
    expect(find.text('Task B'), findsOneWidget);
  });

  testWidgets('manual Fit stays the shared camera after the next layer switch', (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = _harness(
      taskWindows: [
        [graphObjectJson(id: 'task-a', title: 'Task A')],
      ],
    );
    harness.configure();
    await harness.graph.loadOverview();
    await tester.pumpWidget(_screen(harness));
    await tester.pumpAndSettle();
    await harness.graph.setMode(GraphWorkspaceMode.people);
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Уместить граф'));
    await tester.pumpAndSettle();
    final scale = _scale(tester);
    final personPoint = tester.getCenter(find.byKey(const Key('graph_node_person-ada')));

    await harness.graph.setMode(GraphWorkspaceMode.tasks);
    await tester.pumpAndSettle();
    expect(harness.graph.shouldFitAfterLayout, isFalse);
    expect(_scale(tester), closeTo(scale, 0.001));
    expect(
      tester.getCenter(find.byKey(const Key('graph_node_task-a'))),
      offsetMoreOrLessEquals(personPoint, epsilon: 1.5),
    );
  });

  testWidgets('a failed canonical layout falls back without partial People geography', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = _harness(
      taskWindows: [
        [graphObjectJson(id: 'task-a', title: 'Task A')],
      ],
      layoutUsable: false,
    );
    harness.configure();
    await harness.graph.setMode(GraphWorkspaceMode.people);
    await tester.pumpWidget(_screen(harness));
    await tester.pumpAndSettle();

    expect(harness.graph.canonicalTaskCentersActive, isFalse);
    expect(find.text('Ada'), findsOneWidget);
    expect(find.byKey(const Key('graph_node_task-a')), findsNothing);
    expect(find.byKey(const ValueKey('task-layout-warning')), findsNothing);
  });

  testWidgets('windowed Tasks and People keep the same global screen pixels', (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = _parityHarness();
    harness.configure();
    await harness.graph.loadOverview();
    await tester.pumpWidget(_screen(harness));
    await tester.pumpAndSettle();

    expect(find.textContaining('Показана часть пространства графа'), findsOneWidget);
    expect(find.text('Область 1 из 2'), findsOneWidget);
    await tester.tap(find.byTooltip('Уместить граф'));
    await tester.pumpAndSettle();

    final scale = _scale(tester);
    final east = tester.getCenter(find.byKey(const Key('graph_node_task-east')));
    final shared = tester.getCenter(find.byKey(const Key('graph_node_task-shared')));
    expect(harness.graph.shouldFitAfterLayout, isFalse);

    await harness.graph.setMode(GraphWorkspaceMode.people);
    await tester.pumpAndSettle();

    expect(harness.graph.shouldFitAfterLayout, isFalse);
    expect(_scale(tester), closeTo(scale, 0.001));
    expect(find.textContaining('Показана часть пространства графа'), findsNothing);
    expect(find.byKey(const Key('graph_node_task-east')), findsNothing);
    expect(find.byKey(const Key('graph_node_task-shared')), findsNothing);
    expect(find.byKey(const Key('graph_node_task-west')), findsNothing);
    expect(
      tester.getCenter(find.byKey(const Key('graph_node_person-east'))),
      offsetMoreOrLessEquals(east, epsilon: 1.5),
    );
    final pairA = tester.getCenter(find.byKey(const Key('graph_node_person-a')));
    final pairB = tester.getCenter(find.byKey(const Key('graph_node_person-b')));
    expect(
      Offset((pairA.dx + pairB.dx) / 2, (pairA.dy + pairB.dy) / 2),
      offsetMoreOrLessEquals(shared, epsilon: 1.5),
    );

    await harness.graph.setMode(GraphWorkspaceMode.tasks);
    await tester.pumpAndSettle();
    expect(_scale(tester), closeTo(scale, 0.001));
    expect(
      tester.getCenter(find.byKey(const Key('graph_node_task-east'))),
      offsetMoreOrLessEquals(east, epsilon: 1.5),
    );
    expect(
      tester.getCenter(find.byKey(const Key('graph_node_task-shared'))),
      offsetMoreOrLessEquals(shared, epsilon: 1.5),
    );

    await tester.tap(find.byKey(const ValueKey('graph-overview-window-next')));
    await tester.pumpAndSettle();
    expect(find.text('Область 2 из 2'), findsOneWidget);
    await tester.tap(find.byTooltip('Уместить граф'));
    await tester.pumpAndSettle();
    final westScale = _scale(tester);
    final west = tester.getCenter(find.byKey(const Key('graph_node_task-west')));

    await harness.graph.setMode(GraphWorkspaceMode.people);
    await tester.pumpAndSettle();
    expect(harness.graph.shouldFitAfterLayout, isFalse);
    expect(_scale(tester), closeTo(westScale, 0.001));
    expect(
      tester.getCenter(find.byKey(const Key('graph_node_person-west'))),
      offsetMoreOrLessEquals(west, epsilon: 1.5),
    );

    await harness.graph.setMode(GraphWorkspaceMode.tasks);
    await tester.pumpAndSettle();
    expect(_scale(tester), closeTo(westScale, 0.001));
    expect(find.text('Область 2 из 2'), findsOneWidget);
    expect(
      tester.getCenter(find.byKey(const Key('graph_node_task-west'))),
      offsetMoreOrLessEquals(west, epsilon: 1.5),
    );
  });
}

double _scale(WidgetTester tester) {
  return tester
      .widget<InteractiveViewer>(find.byType(InteractiveViewer))
      .transformationController!
      .value
      .getMaxScaleOnAxis();
}

Widget _screen(GraphTestHarness harness) {
  return MaterialApp(
    home: Scaffold(
      body: GraphWorkspaceScreen(
        controller: harness.graph,
        apiClient: harness.auth.apiClient,
        authController: harness.auth,
        captureController: harness.capture,
        assistantController: harness.assistant,
        onAskSecretary: (_) {},
      ),
    ),
  );
}

GraphTestHarness _harness({
  required List<List<Map<String, dynamic>>> taskWindows,
  bool layoutUsable = true,
}) {
  return GraphTestHarness(
    MockClient((request) async {
      if (request.url.path == '/search/facets') {
        return jsonUtf8Response({'kinds': [], 'providers': []});
      }
      if (request.url.path == '/graph/workspace') {
        final index = int.parse(request.url.queryParameters['window_index'] ?? '0');
        final nodes = taskWindows[index];
        return jsonUtf8Response({
          ...graphWorkspaceJson(nodes: nodes),
          'window_index': index,
          'window_count': taskWindows.length,
          'has_next_window': index + 1 < taskWindows.length,
          'has_previous_window': index > 0,
          'semantic_window_complete': true,
        });
      }
      if (request.url.path == '/graph/people-workspace') {
        return jsonUtf8Response({
          ...graphWorkspaceJson(
            nodes: [graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person')],
          ),
          'seed_ids': ['person-ada'],
          'people': [
            {
              'person_id': 'person-ada',
              'title': 'Ada',
              'landscape_task_ids': ['task-a'],
              'landscape_task_ids_complete': true,
            },
          ],
        });
      }
      if (request.method == 'GET' && request.url.path == '/graph/task-layout') {
        if (!layoutUsable) {
          return http.Response('missing', 404);
        }
        return jsonUtf8Response({
          'topology_revision': 1,
          'snapshot_revision': 1,
          'algorithm_version': kTaskLayoutAlgorithmVersion,
          'usable': true,
          'centers': [
            {'task_id': 'task-a', 'world_x': 800, 'world_y': 400},
            {'task_id': 'task-b', 'world_x': 1600, 'world_y': 400},
          ],
        });
      }
      return http.Response('missing', 404);
    }),
  );
}

GraphTestHarness _parityHarness() {
  const people = [
    ('person-west', 'West', 'task-west'),
    ('person-east', 'East', 'task-east'),
    ('person-a', 'Ada', 'task-shared'),
    ('person-b', 'Bea', 'task-shared'),
  ];
  return GraphTestHarness(
    MockClient((request) async {
      if (request.url.path == '/search/facets') {
        return jsonUtf8Response({'kinds': [], 'providers': []});
      }
      if (request.url.path == '/graph/workspace') {
        final index = int.parse(request.url.queryParameters['window_index'] ?? '0');
        final nodes = index == 0
            ? [
                graphObjectJson(id: 'task-east', title: 'East task'),
                graphObjectJson(id: 'task-shared', title: 'Shared task'),
              ]
            : [graphObjectJson(id: 'task-west', title: 'West task')];
        return jsonUtf8Response({
          ...graphWorkspaceJson(nodes: nodes, truncated: true),
          'window_index': index,
          'window_count': 2,
          'has_next_window': index == 0,
          'has_previous_window': index == 1,
          'semantic_window_complete': true,
        });
      }
      if (request.url.path == '/graph/people-workspace') {
        return jsonUtf8Response({
          ...graphWorkspaceJson(
            nodes: [
              for (final person in people)
                graphObjectJson(id: person.$1, title: person.$2, kind: 'person'),
            ],
          ),
          'seed_ids': [for (final person in people) person.$1],
          'people': [
            for (final person in people)
              {
                'person_id': person.$1,
                'title': person.$2,
                'landscape_task_ids': [person.$3],
                'landscape_task_ids_complete': true,
              },
          ],
        });
      }
      if (request.method == 'GET' && request.url.path == '/graph/task-layout') {
        return jsonUtf8Response({
          'topology_revision': 1,
          'snapshot_revision': 1,
          'algorithm_version': kTaskLayoutAlgorithmVersion,
          'usable': true,
          'centers': [
            {'task_id': 'task-west', 'world_x': 200, 'world_y': 320},
            {'task_id': 'task-east', 'world_x': 1600, 'world_y': 280},
            {'task_id': 'task-shared', 'world_x': 1680, 'world_y': 860},
          ],
        });
      }
      return http.Response('missing', 404);
    }),
  );
}
