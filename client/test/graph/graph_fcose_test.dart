import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/fcose_graph_refiner.dart';
import 'package:personal_secretary/graph/graph_geometry.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/graph_workspace_screen.dart';
import 'package:personal_secretary/graph/task_map_scene.dart';

import 'graph_test_harness.dart';

void main() {
  test('fcose stays behind the geometry adapter', () {
    final files = Directory('lib')
        .listSync(recursive: true)
        .whereType<File>()
        .where((file) => file.path.endsWith('.dart'));
    final importers = [
      for (final file in files)
        if (file.readAsStringSync().contains('package:fcose/fcose.dart'))
          file.path,
    ];
    expect(importers, ['lib/graph/fcose_graph_refiner.dart']);
    expect(
      File('lib/api/api_models.dart')
          .readAsStringSync()
          .contains('package:fcose'),
      isFalse,
    );
    expect(
      File('lib/graph/graph_geometry.dart')
          .readAsStringSync()
          .contains('package:fcose'),
      isFalse,
    );
  });

  test(
    'local scene is the selected task, direct neighbors, and band obstacles',
    () {
      final fixture = taskMapFlowerFixture();
      final positions = _positions(fixture);
      final scene = buildGraphGeometryScene(
        nodes: fixture.nodes,
        edges: fixture.edges,
        positions: positions,
        selectedObjectId: fixture.rootId,
      );
      expect(scene, isNotNull);
      final ids = scene!.nodes.map((node) => node.id).toSet();
      expect(ids, contains(fixture.rootId));
      expect(ids, contains('flower-neighbor-0'));
      expect(ids, contains('flower-evidence-0'));
      expect(scene.nodeById(fixture.rootId)!.fixed, isTrue);
      expect(scene.nodeById('flower-neighbor-0')!.fixed, isFalse);
      expect(scene.nodeById('flower-evidence-0')!.fixed, isFalse);
      expect(
        scene.edges.every(
          (edge) =>
              edge.sourceId == fixture.rootId ||
              edge.targetId == fixture.rootId,
        ),
        isTrue,
      );
      expect(
        applyGraphGeometry(
          positions: positions,
          scene: null,
          refiner: const FcoseGraphRefiner(),
        ),
        same(positions),
      );
    },
  );

  test('preserve and relax metrics on shared fixtures', () {
    final cases = <String, TaskMapFixture>{
      'flower': taskMapFlowerFixture(),
      'cluster': taskMapClusterFixture(),
      'overlap': _overlapStressFixture(),
    };
    for (final mode in FcoseRefinementMode.values) {
      for (final entry in cases.entries) {
        final observation = _observe(
          mode,
          entry.value,
          overlapStress: entry.key == 'overlap',
        );
        // ignore: avoid_print
        print('FCOSE_${mode.name}_${entry.key} $observation');
        expect(observation.completed, isTrue, reason: observation.error);
        expect(observation.repeatable, isTrue);
        expect(observation.routes, 0);
      }
    }
  });

  testWidgets('fcose failure leaves workspace nodes in place', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final harness = GraphTestHarness(_workspaceMock());
    harness.configure();
    await harness.graph.loadOverview();
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
            geometryRefiner: _FailingRefiner(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('fCoSE'), findsNothing);
    expect(find.text('Текущий'), findsNothing);
    expect(find.text('Preserve'), findsOneWidget);
    expect(find.text('Relax'), findsOneWidget);
    expect(find.byKey(const ValueKey('graph-hybrid-fallback')), findsOneWidget);
    final before = harness.graph.nodes.map((node) => node.id).toList();
    expect(harness.graph.nodes.map((node) => node.id).toList(), before);

    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    expect(harness.graph.mode.name, 'people');
    expect(find.text('fCoSE'), findsNothing);
    expect(find.text('Анна'), findsOneWidget);
  });
}

class _Observation {
  const _Observation({
    required this.completed,
    required this.error,
    required this.fixedCount,
    required this.maxFixed,
    required this.movableCount,
    required this.movableChanged,
    required this.maxMovable,
    required this.overlapsBefore,
    required this.overlapsAfter,
    required this.maxOverlapBefore,
    required this.maxOverlapAfter,
    required this.intersectionsBefore,
    required this.intersectionsAfter,
    required this.repeatable,
    required this.leafMoved,
    required this.routes,
    required this.millis,
  });

  final bool completed;
  final String? error;
  final int fixedCount;
  final double maxFixed;
  final int movableCount;
  final int movableChanged;
  final double maxMovable;
  final int overlapsBefore;
  final int overlapsAfter;
  final double maxOverlapBefore;
  final double maxOverlapAfter;
  final int intersectionsBefore;
  final int intersectionsAfter;
  final bool repeatable;
  final int leafMoved;
  final int routes;
  final int millis;

  @override
  String toString() {
    return 'completed=$completed error=$error fixed=$fixedCount maxFixed=${maxFixed.toStringAsFixed(2)} '
        'movable=$movableCount movableChanged=$movableChanged maxMovable=${maxMovable.toStringAsFixed(2)} '
        'overlaps=$overlapsBefore->$overlapsAfter maxOverlap=${maxOverlapBefore.toStringAsFixed(1)}->${maxOverlapAfter.toStringAsFixed(1)} '
        'intersections=$intersectionsBefore->$intersectionsAfter repeatable=$repeatable '
        'leafMoved=$leafMoved routes=$routes ms=$millis';
  }
}

_Observation _observe(
  FcoseRefinementMode mode,
  TaskMapFixture fixture, {
  required bool overlapStress,
}) {
  final refiner = FcoseGraphRefiner(mode: mode);
  final positions = _positions(fixture, overlapStress: overlapStress);
  final scene = buildGraphGeometryScene(
    nodes: fixture.nodes,
    edges: fixture.edges,
    positions: positions,
    selectedObjectId: fixture.rootId,
  )!;
  final watch = Stopwatch()..start();
  final first = refiner.refine(scene);
  watch.stop();
  final second = refiner.refine(scene);
  final leafFixture = taskMapFixtureWithEvidenceLeaf(fixture);
  final leafPositions = GraphLayout.computePositions(
    nodes: leafFixture.nodes,
    edges: leafFixture.edges,
    rootId: fixture.rootId,
    existing: positions,
    freshRoot: false,
  );
  final leafScene = buildGraphGeometryScene(
    nodes: leafFixture.nodes,
    edges: leafFixture.edges,
    positions: leafPositions,
    selectedObjectId: fixture.rootId,
  )!;
  final leaf = refiner.refine(leafScene);
  final beforeRects = {for (final node in scene.nodes) node.id: node.rect};
  final afterRects = first.nodes;
  final beforeTop = graphGeometryInputTopLefts(scene);
  final afterTop = graphGeometryTopLefts(first);
  final fixed = [
    for (final node in scene.nodes)
      if (node.fixed) node.id,
  ];
  final movable = [
    for (final node in scene.nodes)
      if (!node.fixed) node.id,
  ];
  final beforeOverlap = graphGeometryOverlaps(beforeRects.values);
  final afterOverlap = graphGeometryOverlaps(afterRects.values);
  final leafMovable = [
    for (final node in leafScene.nodes)
      if (!node.fixed && movable.contains(node.id)) node.id,
  ];
  return _Observation(
    completed: first.completed,
    error: first.error,
    fixedCount: fixed.length,
    maxFixed: graphGeometryMaxDisplacement(beforeTop, afterTop, fixed),
    movableCount: movable.length,
    movableChanged: graphGeometryChangedCount(beforeTop, afterTop, movable),
    maxMovable: graphGeometryMaxDisplacement(beforeTop, afterTop, movable),
    overlapsBefore: beforeOverlap.count,
    overlapsAfter: afterOverlap.count,
    maxOverlapBefore: beforeOverlap.maxArea,
    maxOverlapAfter: afterOverlap.maxArea,
    intersectionsBefore: graphGeometryStraightIntersections(
      rects: beforeRects,
      edges: scene.edges,
    ),
    intersectionsAfter: graphGeometryStraightIntersections(
      rects: afterRects,
      edges: scene.edges,
    ),
    repeatable: _same(first, second),
    leafMoved: graphGeometryChangedCount(
      afterTop,
      graphGeometryTopLefts(leaf),
      leafMovable,
    ),
    routes: first.routes.length,
    millis: watch.elapsedMilliseconds,
  );
}

bool _same(GraphGeometryResult left, GraphGeometryResult right) {
  if (!left.completed ||
      !right.completed ||
      left.nodes.length != right.nodes.length) {
    return false;
  }
  for (final entry in left.nodes.entries) {
    final other = right.nodes[entry.key];
    if (other == null ||
        (entry.value.topLeft - other.topLeft).distance > 0.01) {
      return false;
    }
  }
  return true;
}

Map<String, Offset> _positions(
  TaskMapFixture fixture, {
  bool overlapStress = false,
}) {
  final positions = GraphLayout.computePositions(
    nodes: fixture.nodes,
    edges: fixture.edges,
    rootId: fixture.rootId,
    existing: const {},
    freshRoot: true,
  );
  if (overlapStress) {
    final root = positions[fixture.rootId]!;
    positions['stress-neighbor'] = root + const Offset(40, 24);
  }
  return positions;
}

TaskMapFixture _overlapStressFixture() {
  SecretaryObject object(String id, String title) {
    return SecretaryObject(
      id: id,
      kind: 'task',
      title: title,
      metadata: const {},
      origin: 'user',
      state: 'confirmed',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
  }

  SecretaryEdge edge(String sourceId, String targetId) {
    return SecretaryEdge(
      id: '$sourceId-$targetId',
      sourceId: sourceId,
      targetId: targetId,
      type: 'depends_on',
      origin: 'user',
      state: 'confirmed',
      metadata: const {},
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    );
  }

  return TaskMapFixture(
    nodes: [
      object('stress-task', 'Наложенная задача'),
      object('stress-neighbor', 'Наложенный сосед'),
      object('stress-other', 'Второй сосед'),
      object('stress-far', 'Дальний узел'),
    ],
    edges: [
      edge('stress-task', 'stress-neighbor'),
      edge('stress-task', 'stress-other'),
    ],
    rootId: 'stress-task',
  );
}

class _FailingRefiner implements GraphGeometryRefiner {
  @override
  GraphGeometryResult refine(GraphGeometryScene scene) {
    return const GraphGeometryResult.failure('fcose probe failed');
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
          nodes: [
            graphObjectJson(id: 'person-1', title: 'Анна', kind: 'person'),
          ],
        ),
      );
    }
    if (request.url.path == '/graph/workspace') {
      return jsonUtf8Response(
        graphWorkspaceJson(
          nodes: [
            graphObjectJson(id: 'task-a', title: 'Задача А'),
            graphObjectJson(id: 'task-b', title: 'Задача Б'),
            graphObjectJson(
              id: 'email-1',
              title: 'Письмо контекста',
              kind: 'email',
            ),
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
