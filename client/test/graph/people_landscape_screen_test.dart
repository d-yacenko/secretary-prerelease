import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/graph_workspace_controller.dart';
import 'package:personal_secretary/graph/graph_workspace_screen.dart';
import 'package:personal_secretary/graph/people_landscape.dart';
import 'package:personal_secretary/graph/people_overview.dart';

import 'graph_test_harness.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('usable landscape replaces the People grid and keeps the shelf', (tester) async {
    await _pumpPeople(
      tester,
      _workspace(
        people: [
          _person('person-bea', anchors: const []),
          _person('person-ada', anchors: const ['task-a']),
        ],
        seedIds: const ['person-bea', 'person-ada'],
        tasks: [_task('task-a', 'Скрытая задача')],
      ),
    );

    expect(find.text('Скрытая задача'), findsNothing);
    expect(find.byKey(const Key('graph_node_task-a')), findsNothing);
    expect(find.text('Ada'), findsOneWidget);
    expect(find.text('Bea'), findsOneWidget);
    expect(
      tester.getSize(find.byKey(const Key('graph_node_person-ada'))),
      const Size(kPeopleLandscapeOverviewCardWidth, kPeopleLandscapeOverviewCardHeight),
    );
    expect(find.text('Связанные задачи'), findsNothing);

    final drawn = _delta(tester, 'person-ada', 'person-bea');
    final landscape = _landscape(_loaded(tester));
    final grid = _grid(_loaded(tester));
    expect(drawn, _offsetDelta(landscape.positions, 'person-ada', 'person-bea'));
    expect(drawn, isNot(_offsetDelta(grid, 'person-ada', 'person-bea')));
    expect(landscape.usable, isTrue);
    expect(landscape.unanchoredPersonIds, ['person-bea']);
    final shelf = landscape.positions['person-bea']!;
    expect(shelf.dx, greaterThanOrEqualTo(landscape.taskBounds!.right + kPeopleLandscapeShelfGap));
  });

  testWidgets('incomplete landscape falls back to the whole People grid', (tester) async {
    Future<void> expectGrid(
      Map<String, dynamic> workspace, {
      bool layoutUsable = true,
    }) async {
      await _pumpPeople(tester, workspace, layoutUsable: layoutUsable);
      final drawn = _delta(tester, 'person-ada', 'person-bea');
      final grid = _grid(_loaded(tester));
      expect(drawn, _offsetDelta(grid, 'person-ada', 'person-bea'));
      expect(_landscape(_loaded(tester)).usable, isFalse);
      expect(find.text('Скрытая задача'), findsNothing);
      await tester.pumpWidget(const SizedBox.shrink());
    }

    await expectGrid(
      _workspace(
        people: [
          _person('person-ada', anchors: const ['task-a']),
          _person('person-bea', anchors: const []),
        ],
        tasks: [_task('task-a', 'Скрытая задача')],
      ),
      layoutUsable: false,
    );
    await expectGrid(
      _workspace(
        people: [
          _person('person-ada', anchors: const ['task-a'], complete: false),
          _person('person-bea', anchors: const []),
        ],
        tasks: [_task('task-a', 'Скрытая задача')],
      ),
    );
    await expectGrid(
      _workspace(
        people: [
          _person('person-ada', anchors: const ['task-missing']),
          _person('person-bea', anchors: const []),
        ],
        tasks: [_task('task-a', 'Скрытая задача')],
      ),
    );
  });

  testWidgets('manual and automatic fit use landscape positions', (tester) async {
    final harness = await _pumpPeople(
      tester,
      _workspace(
        people: [
          _person('person-ada', anchors: const ['task-a']),
          _person('person-bea', anchors: const []),
        ],
        tasks: [_task('task-a', 'Скрытая задача')],
      ),
    );
    final viewer = tester.widget<InteractiveViewer>(find.byType(InteractiveViewer));
    final viewport = tester.getSize(find.byType(InteractiveViewer));
    final landscape = _landscape(harness.graph);
    final card = const Size(
      kPeopleLandscapeOverviewCardWidth,
      kPeopleLandscapeOverviewCardHeight,
    );
    final sizes = {for (final id in landscape.positions.keys) id: card};
    final landscapeFit = GraphLayout.fitTransform(
      positions: landscape.positions,
      viewportSize: viewport,
      nodeSizes: sizes,
    );
    final gridFit = GraphLayout.fitTransform(
      positions: _grid(harness.graph),
      viewportSize: viewport,
      nodeSizes: sizes,
    );
    final fullCardFit = GraphLayout.fitTransform(
      positions: landscape.positions,
      viewportSize: viewport,
    );
    expect(viewer.transformationController!.value.storage, landscapeFit.storage);
    expect(viewer.transformationController!.value.storage, isNot(gridFit.storage));
    expect(viewer.transformationController!.value.storage, isNot(fullCardFit.storage));

    viewer.transformationController!.value = Matrix4.identity();
    await tester.tap(find.byTooltip('Уместить граф'));
    await tester.pump();
    expect(viewer.transformationController!.value.storage, landscapeFit.storage);
  });

  testWidgets('rooted Person view ignores landscape positions', (tester) async {
    final harness = await _pumpPeople(
      tester,
      _workspace(
        people: [
          _person('person-ada', anchors: const ['task-a']),
          _person('person-bea', anchors: const []),
        ],
        tasks: [_task('task-a', 'Скрытая задача')],
      ),
      rooted: _workspace(
        rootId: 'person-ada',
        people: [
          _person('person-ada', anchors: const ['task-a']),
          _person('person-bea', anchors: const []),
        ],
        nodes: [
          graphObjectJson(id: 'person-ada', title: 'Ada', kind: 'person'),
          graphObjectJson(id: 'person-bea', title: 'Bea', kind: 'person'),
        ],
        edges: [
          {
            'id': 'edge-people',
            'source_id': 'person-ada',
            'target_id': 'person-bea',
            'type': 'related_to',
            'origin': 'user',
            'state': 'confirmed',
            'metadata': <String, dynamic>{},
            'created_at': '2026-01-01T00:00:00Z',
            'updated_at': '2026-01-01T00:00:00Z',
          },
        ],
        tasks: [_task('task-a', 'Скрытая задача')],
      ),
    );

    await harness.graph.reRoot('person-ada');
    await tester.pump();
    await tester.pump();

    expect(harness.graph.rootId, 'person-ada');
    expect(find.text('Скрытая задача'), findsNothing);
    final drawn = _delta(tester, 'person-ada', 'person-bea');
    expect(
      drawn,
      harness.graph.positions['person-bea']! - harness.graph.positions['person-ada']!,
    );
    final landscape = _landscape(harness.graph);
    expect(landscape.usable, isTrue);
    expect(drawn, isNot(_offsetDelta(landscape.positions, 'person-ada', 'person-bea')));
    expect(
      tester.getSize(find.byKey(const Key('graph_node_person-ada'))),
      const Size(kGraphNodeWidth, kGraphNodeHeight),
    );
  });

  testWidgets('a Person card keeps its own landscape position after rebuild', (tester) async {
    await _pumpPeople(
      tester,
      _workspace(
        people: [
          _person('person-bea', anchors: const ['task-b']),
          _person('person-ada', anchors: const ['task-a']),
        ],
        tasks: [
          _task('task-a', 'Левая задача'),
          _task('task-b', 'Правая задача'),
        ],
      ),
    );
    final controller = _loaded(tester);
    final landscape = _landscape(controller);
    final ada = _origin(tester, 'person-ada');
    final bea = _origin(tester, 'person-bea');
    expect(bea - ada, _offsetDelta(landscape.positions, 'person-ada', 'person-bea'));
    expect(find.text('Левая задача'), findsNothing);
    expect(find.text('Правая задача'), findsNothing);
    await controller.loadOverview();
    await tester.pump();
    expect(_origin(tester, 'person-ada'), ada);
    expect(_origin(tester, 'person-bea'), bea);
    expect(find.byKey(const ValueKey('drawn-person-ada')), findsOneWidget);
    expect(find.byKey(const ValueKey('drawn-person-bea')), findsOneWidget);
  });
}

GraphWorkspaceController _loaded(WidgetTester tester) {
  return tester.widget<GraphWorkspaceScreen>(find.byType(GraphWorkspaceScreen)).controller;
}

Offset _delta(WidgetTester tester, String from, String to) {
  return _origin(tester, to) - _origin(tester, from);
}

Offset _origin(WidgetTester tester, String id) {
  final positioned = tester.widget<Positioned>(
    find.ancestor(
      of: find.byKey(Key('graph_node_$id')),
      matching: find.byType(Positioned),
    ).first,
  );
  return Offset(positioned.left!, positioned.top!);
}

Offset _offsetDelta(Map<String, Offset> positions, String from, String to) {
  return positions[to]! - positions[from]!;
}

PeopleLandscapeOverview _landscape(GraphWorkspaceController controller) {
  final people = controller.nodes.where((node) => node.kind == 'person').toList();
  return projectPeopleLandscapeOverview(
    personIds: people.map((node) => node.id),
    people: [for (final node in people) controller.personFor(node.id)!],
    taskCenters: controller.canonicalTaskCenters,
    canonicalCentersActive: controller.canonicalTaskCentersActive,
  );
}

Map<String, Offset> _grid(GraphWorkspaceController controller) {
  return projectPeopleOverview(
    nodes: controller.nodes,
    seedIds: controller.seedIds,
    rootId: null,
  );
}

Future<GraphTestHarness> _pumpPeople(
  WidgetTester tester,
  Map<String, dynamic> overview, {
  Map<String, dynamic>? rooted,
  bool layoutUsable = true,
}) async {
  tester.view.physicalSize = const Size(1400, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final harness = GraphTestHarness(
    MockClient((request) async {
      if (request.method == 'GET' && request.url.path == '/graph/task-layout') {
        if (!layoutUsable) {
          return http.Response('missing', 404);
        }
        final tasks = (overview['landscape_tasks'] as List?) ?? const [];
        return jsonUtf8Response({
          'topology_revision': 1,
          'snapshot_revision': 1,
          'algorithm_version': 'task-map-v1',
          'usable': true,
          'centers': [
            for (var index = 0; index < tasks.length; index++)
              {
                'task_id': (tasks[index] as Map)['id'],
                'world_x': 500.0 + index * 800,
                'world_y': 240.0,
              },
          ],
        });
      }
      if (request.url.path == '/graph/people-workspace') {
        final rootId = request.url.queryParameters['root_id'];
        return jsonUtf8Response(rootId == null ? overview : rooted ?? overview);
      }
      if (request.url.path == '/search/facets') {
        return jsonUtf8Response({'kinds': [], 'providers': []});
      }
      return http.Response('not found', 404);
    }),
  );
  harness.configure();
  await harness.graph.setMode(GraphWorkspaceMode.people);
  await tester.pumpWidget(
    MaterialApp(
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
    ),
  );
  await tester.pump();
  return harness;
}

Map<String, dynamic> _person(
  String id, {
  List<String> anchors = const [],
  bool complete = true,
}) {
  final title = id == 'person-ada' ? 'Ada' : 'Bea';
  return {
    'person_id': id,
    'title': title,
    'landscape_task_ids': anchors,
    'landscape_task_ids_complete': complete,
  };
}

Map<String, dynamic> _task(String id, String title) {
  return graphObjectJson(id: id, title: title);
}

Map<String, dynamic> _workspace({
  required List<Map<String, dynamic>> people,
  String? rootId,
  List<String>? seedIds,
  List<Map<String, dynamic>>? nodes,
  List<Map<String, dynamic>> edges = const [],
  List<Map<String, dynamic>> tasks = const [],
  bool contextComplete = true,
}) {
  final personNodes = nodes ??
      [
        for (final person in people)
          graphObjectJson(
            id: person['person_id'] as String,
            title: person['title'] as String,
            kind: 'person',
          ),
      ];
  final body = graphWorkspaceJson(
    rootId: rootId,
    nodes: personNodes,
    edges: edges,
  );
  body['seed_ids'] = seedIds ?? [for (final person in people) person['person_id']];
  body['people'] = people;
  body['landscape_tasks'] = tasks;
  body['landscape_task_edges'] = <Map<String, dynamic>>[];
  body['landscape_task_context_complete'] = contextComplete;
  return body;
}
