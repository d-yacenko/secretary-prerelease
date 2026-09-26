import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/graph/elk_task_map_engine.dart';
import 'package:personal_secretary/graph/task_map_elk_view.dart';
import 'package:personal_secretary/graph/task_map_scene.dart';
import 'package:personal_secretary/graph/task_profile_section.dart';

import 'graph_test_harness.dart';

void main() {
  test('elk stays behind the layout adapter', () {
    final files = Directory('lib')
        .listSync(recursive: true)
        .whereType<File>()
        .where((file) => file.path.endsWith('.dart'));
    final importers = [
      for (final file in files)
        if (file.readAsStringSync().contains('package:elk/elk.dart')) file.path,
    ];
    expect(importers, ['lib/graph/elk_task_map_engine.dart']);
    expect(
      File('lib/api/api_models.dart').readAsStringSync().contains('package:elk'),
      isFalse,
    );
  });

  test('flower keeps the center, direct neighbors, and existing edges', () {
    final fixture = taskMapFlowerFixture();
    final scene = buildTaskMapScene(
      nodes: fixture.nodes,
      edges: fixture.edges,
      selectedObjectId: fixture.rootId,
    );
    expect(scene.groupIds, isEmpty);
    expect(scene.nodes.map((node) => node.id), contains(fixture.rootId));
    expect(scene.nodes.map((node) => node.id), contains('flower-neighbor-2'));
    expect(scene.nodes.map((node) => node.id), contains('flower-evidence-11'));
    expect(scene.nodes.map((node) => node.id), isNot(contains('flower-unrelated')));
    expect(scene.nodes, hasLength(16));
    expect(scene.edges, hasLength(15));
    expect(
      scene.edges.every(
        (edge) =>
            scene.nodes.any((node) => node.id == edge.sourceId) &&
            scene.nodes.any((node) => node.id == edge.targetId),
      ),
      isTrue,
    );
  });

  test('overview without a selected task is a bounded task set', () {
    final fixture = taskMapFlowerFixture();
    final scene = buildTaskMapScene(
      nodes: fixture.nodes,
      edges: fixture.edges,
      selectedObjectId: null,
    );
    expect(scene.nodes, hasLength(4));
    expect(scene.nodes.every((node) => node.id.contains('task') || node.id.contains('neighbor')), isTrue);
    expect(scene.nodes.map((node) => node.id), isNot(contains('flower-evidence-0')));
  });

  test('flower and cluster geometry probes', () {
    const engine = ElkTaskMapEngine();
    const priorEngine = ElkTaskMapEngine(usePriorPositions: true);
    final flower = _observe(engine, priorEngine, taskMapFlowerFixture(), flower: true);
    final cluster = _observe(engine, priorEngine, taskMapClusterFixture(), flower: false);
    // Captured in PROJECT_STATE from this line.
    // ignore: avoid_print
    print('ELK_FLOWER $flower');
    // ignore: avoid_print
    print('ELK_CLUSTER $cluster');
    expect(flower.completed, isTrue, reason: flower.error);
    expect(cluster.completed, isTrue, reason: cluster.error);
    expect(flower.repeatable, isTrue);
    expect(cluster.repeatable, isTrue);
    expect(flower.nodeCount, 16);
    expect(cluster.nodeCount, 28);
    expect(flower.routedEdges, flower.edgeCount);
    expect(cluster.routedEdges, cluster.edgeCount);
  });

  testWidgets('elk cards use normalized positions', (tester) async {
    tester.view.physicalSize = const Size(900, 700);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final fixture = taskMapFlowerFixture();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TaskMapElkView(
            nodes: fixture.nodes,
            edges: fixture.edges,
            selectedObjectId: fixture.rootId,
            onSelect: (_) {},
            engine: _FixedEngine(),
          ),
        ),
      ),
    );
    await tester.pump();

    final positioned = tester.widget<Positioned>(
      find.byKey(const ValueKey('task-map-elk-pos-flower-task')),
    );
    expect(positioned.left, 20);
    expect(positioned.top, 30);
    expect(find.byKey(const ValueKey('task-map-node-flower-task')), findsOneWidget);
    expect(find.byKey(const ValueKey('task-map-elk-pos-flower-unrelated')), findsNothing);
  });

  testWidgets('elk failure leaves the supplied nodes in place', (tester) async {
    final nodes = taskMapFlowerFixture().nodes;
    final before = nodes.map((node) => node.id).toList();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TaskMapElkView(
            nodes: nodes,
            edges: taskMapFlowerFixture().edges,
            selectedObjectId: 'flower-task',
            onSelect: (_) {},
            engine: _FailingEngine(),
          ),
        ),
      ),
    );
    await tester.pump();
    expect(find.byKey(const ValueKey('task-map-elk-fallback')), findsOneWidget);
    expect(nodes.map((node) => node.id).toList(), before);
  });

  testWidgets('elk is a third task renderer and people mode stays current', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(_workspaceMock());
    harness.configure();
    await openGraph(tester, harness);

    expect(find.text('Текущий'), findsOneWidget);
    expect(find.text('Эксперимент'), findsOneWidget);
    expect(find.text('ELK'), findsOneWidget);
    expect(find.byKey(const ValueKey('task-map-elk-label')), findsNothing);
    expect(find.text('Экспериментальная карта'), findsNothing);

    final nodeIds = harness.graph.nodes.map((node) => node.id).toList();
    await tester.tap(find.text('ELK'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('task-map-elk-label')), findsOneWidget);
    expect(find.text('Mind map'), findsNothing);
    expect(find.byKey(const ValueKey('task-map-node-task-a')), findsOneWidget);
    expect(find.byKey(const ValueKey('task-map-node-email-1')), findsNothing);
    expect(harness.graph.nodes.map((node) => node.id).toList(), nodeIds);

    await tester.tap(find.byKey(const ValueKey('task-map-node-task-a')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(harness.graph.selectedObjectId, 'task-a');
    expect(harness.graph.nodes.map((node) => node.id).toList(), nodeIds);
    expect(find.byKey(const ValueKey('task-map-node-email-1')), findsOneWidget);
    expect(find.byKey(const ValueKey('task-map-node-file-1')), findsNothing);
    expect(find.text('Спросить секретаря'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byType(TaskProfileSection),
      200,
      scrollable: find
          .ancestor(
            of: find.text('Спросить секретаря'),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    expect(find.byType(TaskProfileSection), findsOneWidget);

    await tester.tap(find.text('Текущий'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('task-map-elk-label')), findsNothing);
    expect(find.text('Чужой файл'), findsWidgets);

    await tester.tap(find.text('Эксперимент'));
    await tester.pumpAndSettle();
    expect(find.text('Экспериментальная карта'), findsOneWidget);
    expect(find.text('Mind map'), findsOneWidget);

    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    expect(harness.graph.mode.name, 'people');
    expect(find.text('ELK'), findsNothing);
    expect(find.byKey(const ValueKey('task-map-elk-label')), findsNothing);
    expect(find.text('Анна'), findsOneWidget);
  });
}

class _Geometry {
  const _Geometry({
    required this.completed,
    required this.error,
    required this.nodeCount,
    required this.edgeCount,
    required this.overlaps,
    required this.bendEdges,
    required this.routedEdges,
    required this.intersections,
    required this.repeatable,
    required this.movedAfterLeaf,
    required this.priorMoved,
    required this.shiftedPriorMoved,
  });

  final bool completed;
  final String? error;
  final int nodeCount;
  final int edgeCount;
  final int overlaps;
  final int bendEdges;
  final int routedEdges;
  final int intersections;
  final bool repeatable;
  final int movedAfterLeaf;
  final int priorMoved;
  final int shiftedPriorMoved;

  @override
  String toString() {
    return 'completed=$completed error=$error nodes=$nodeCount edges=$edgeCount '
        'overlaps=$overlaps bends=$bendEdges routed=$routedEdges '
        'intersections=$intersections repeatable=$repeatable '
        'movedAfterLeaf=$movedAfterLeaf priorMoved=$priorMoved '
        'shiftedPriorMoved=$shiftedPriorMoved';
  }
}

_Geometry _observe(
  TaskMapLayoutEngine engine,
  TaskMapLayoutEngine priorEngine,
  TaskMapFixture fixture, {
  required bool flower,
}) {
  TaskMapScene sceneFor(TaskMapFixture source) {
    if (flower) {
      return buildTaskMapScene(
        nodes: source.nodes,
        edges: source.edges,
        selectedObjectId: source.rootId,
      );
    }
    return taskMapFullScene(source);
  }

  final scene = sceneFor(fixture);
  final first = engine.layout(scene);
  final second = engine.layout(scene);
  final added = engine.layout(sceneFor(taskMapFixtureWithEvidenceLeaf(fixture)));
  final hinted = priorEngine.layout(sceneWithPriors(scene, first));
  final shifted = priorEngine.layout(
    TaskMapScene(
      nodes: [
        for (final node in scene.nodes)
          TaskMapSceneNode(
            id: node.id,
            width: node.width,
            height: node.height,
            prior: const Offset(4000, 4000),
          ),
      ],
      edges: scene.edges,
    ),
  );
  return _Geometry(
    completed: first.completed,
    error: first.error,
    nodeCount: first.nodes.length,
    edgeCount: first.edges.length,
    overlaps: taskMapOverlapCount(first.nodes),
    bendEdges: taskMapBendEdgeCount(first.edges),
    routedEdges: taskMapRoutedEdgeCount(first.edges),
    intersections: taskMapEdgeNodeIntersectionCount(first),
    repeatable: taskMapLayoutsMatch(first, second),
    movedAfterLeaf: taskMapSceneMovedNodeCount(first, added),
    priorMoved: taskMapSceneMovedNodeCount(first, hinted),
    shiftedPriorMoved: taskMapSceneMovedNodeCount(first, shifted),
  );
}

class _FixedEngine implements TaskMapLayoutEngine {
  @override
  TaskMapSceneLayout layout(TaskMapScene scene) {
    return TaskMapSceneLayout.success(
      nodes: {
        for (var index = 0; index < scene.nodes.length; index++)
          scene.nodes[index].id: Rect.fromLTWH(20.0 + index * 200, 30, 168, 104),
      },
      edges: [
        if (scene.edges.isNotEmpty)
          TaskMapRoutedEdge(
            id: scene.edges.first.id,
            sourceId: scene.edges.first.sourceId,
            targetId: scene.edges.first.targetId,
            sections: const [
              [Offset(180, 62), Offset(180, 90), Offset(200, 90)],
            ],
          ),
      ],
    );
  }
}

class _FailingEngine implements TaskMapLayoutEngine {
  @override
  TaskMapSceneLayout layout(TaskMapScene scene) {
    return const TaskMapSceneLayout.failure('elk probe failed');
  }
}

MockClient _workspaceMock() {
  return MockClient((request) async {
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
    if (request.url.path == '/graph/people-workspace') {
      return jsonUtf8Response(
        graphWorkspaceJson(
          nodes: [graphObjectJson(id: 'person-1', title: 'Анна', kind: 'person')],
        ),
      );
    }
    if (request.url.path == '/graph/workspace') {
      return jsonUtf8Response(
        graphWorkspaceJson(
          nodes: [
            graphObjectJson(id: 'task-a', title: 'Задача А'),
            graphObjectJson(id: 'task-b', title: 'Задача Б'),
            graphObjectJson(id: 'email-1', title: 'Письмо контекста', kind: 'email'),
            graphObjectJson(id: 'file-1', title: 'Чужой файл', kind: 'file'),
          ],
          edges: [
            {
              'id': 'edge-tasks',
              'source_id': 'task-a',
              'target_id': 'task-b',
              'type': 'depends_on',
              'origin': 'user',
              'state': 'confirmed',
              'metadata': {},
              'created_at': '2026-01-01T00:00:00Z',
              'updated_at': '2026-01-01T00:00:00Z',
            },
            {
              'id': 'edge-email',
              'source_id': 'task-a',
              'target_id': 'email-1',
              'type': 'references',
              'origin': 'user',
              'state': 'confirmed',
              'metadata': {},
              'created_at': '2026-01-01T00:00:00Z',
              'updated_at': '2026-01-01T00:00:00Z',
            },
            {
              'id': 'edge-file',
              'source_id': 'task-b',
              'target_id': 'file-1',
              'type': 'references',
              'origin': 'user',
              'state': 'confirmed',
              'metadata': {},
              'created_at': '2026-01-01T00:00:00Z',
              'updated_at': '2026-01-01T00:00:00Z',
            },
          ],
        ),
      );
    }
    return http.Response('{}', 404);
  });
}
