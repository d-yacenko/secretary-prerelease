import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/focus_lod.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/graph_workspace_screen.dart';
import 'package:personal_secretary/ui/provider_icon.dart';

import 'graph_test_harness.dart';

void main() {
  test('focus lod does not import a layout engine', () {
    final source = File('lib/graph/focus_lod.dart').readAsStringSync();
    expect(source.contains('package:elk'), isFalse);
    expect(source.contains('package:fcose'), isFalse);
    expect(source.contains('package:graphview'), isFalse);
    expect(
      File('pubspec.yaml').readAsStringSync().contains('focus_lod'),
      isFalse,
    );
  });

  test('fixtures keep task geography and compact each flow once', () {
    final overview = _overview();
    final overviewProjection = _project(overview);
    _expectStableTasks(overview);
    expect(_fullFlow(overview, overviewProjection), 0);
    expect(overviewProjection.satellites, hasLength(8));
    expect(overviewProjection.overflows, isEmpty);
    expect(_duplicates(overview, overviewProjection), 0);
    expect(_taskOverlaps(overview, overviewProjection), 0);
    expect(focusLodSameHaloOverlaps(overviewProjection.satellites), 0);
    _expectRepeatable(overview);

    final flower = _flower();
    final before = Map<String, Offset>.from(flower.positions);
    final focused = _project(flower, selectedObjectId: 'task-s');
    _expectStableTasks(flower, selectedObjectId: 'task-s');
    for (final id in flower.taskIds) {
      expect(flower.positions[id], before[id]);
    }
    expect(_fullFlow(flower, focused), 10);
    expect(focused.satellites, hasLength(4));
    expect(
      focused.satellites.every((item) => item.anchorTaskId == 'task-o'),
      isTrue,
    );
    expect(focused.fullCardIds.containsAll(flower.taskIds), isTrue);
    expect(_duplicates(flower, focused), 0);
    expect(_taskOverlaps(flower, focused), 0);
    expect(focusLodSameHaloOverlaps(focused.satellites), 0);
    final again = _project(flower, selectedObjectId: 'task-o');
    for (final id in flower.taskIds) {
      expect(flower.positions[id], before[id]);
    }
    expect(_fullFlow(flower, again), 4);
    expect(again.satellites, hasLength(10));
    // ignore: avoid_print
    print(
      'FOCUS_LOD_DENSITY currentFullNonTask=${flower.nodes.where((node) => node.kind != 'task').length} '
      'lodFullNonTask=${_fullFlow(flower, focused)} satellites=${focused.satellites.length} '
      'overflow=${focused.overflows.fold<int>(0, (sum, item) => sum + item.remainder)}',
    );

    final shared = _shared();
    final compactShared = _project(shared);
    expect(compactShared.satellites, hasLength(1));
    expect(compactShared.satellites.single.anchorTaskId, 'task-near');
    expect(compactShared.satellites.single.objectId, 'mail-shared');
    final expandedShared = _project(shared, selectedObjectId: 'task-far');
    expect(expandedShared.satellites, isEmpty);
    expect(expandedShared.fullCardIds, contains('mail-shared'));
    expect(_duplicates(shared, expandedShared), 0);

    final crowded = _crowded();
    final halo = _project(crowded);
    expect(halo.satellites, hasLength(20));
    expect(halo.overflows, hasLength(1));
    expect(halo.overflows.single.remainder, 15);
    expect(halo.satellites.map((item) => item.objectId), contains('mail-book'));
    expect(
      halo.satellites.map((item) => item.objectId),
      isNot(contains('mail-old')),
    );
    expect(_duplicates(crowded, halo), 0);
    expect(_taskOverlaps(crowded, halo), 0);
    expect(focusLodSameHaloOverlaps(halo.satellites), 0);

    final close = _close();
    final closeProjection = _project(close);
    expect(closeProjection.satellites, hasLength(8));
    expect(_taskOverlaps(close, closeProjection), 0);
    expect(focusLodSameHaloOverlaps(closeProjection.satellites), 0);
    expect(close.positions['task-a'], const Offset(0, 0));
    expect(close.positions['task-b'], const Offset(200, 0));

    final kept = _keptKinds();
    final keptProjection = _project(kept);
    expect(keptProjection.satellites, isEmpty);
    expect(
      keptProjection.fullCardIds,
      containsAll(kept.nodes.map((node) => node.id)),
    );
    expect(
      focusLodEdgeIsVisible(
        edge: kept.edges.single,
        fullCardIds: keptProjection.fullCardIds,
      ),
      isTrue,
    );

    final hidden = flower.edges.where(
      (edge) => edge.sourceId == 'task-o' || edge.targetId == 'task-o',
    );
    expect(
      hidden
          .where(
            (edge) => edge.sourceId != 'task-s' && edge.targetId != 'task-s',
          )
          .every(
            (edge) => !focusLodEdgeIsVisible(
              edge: edge,
              fullCardIds: focused.fullCardIds,
            ),
          ),
      isTrue,
    );
    expect(
      focusLodEdgeIsVisible(
        edge: flower.edges.firstWhere((edge) => edge.id == 'edge-tasks'),
        fullCardIds: focused.fullCardIds,
      ),
      isTrue,
    );

    // ignore: avoid_print
    print(
      'FOCUS_LOD_A tasks=${overview.taskIds.length} fullFlow=${_fullFlow(overview, overviewProjection)} '
      'satellites=${overviewProjection.satellites.length} overflow=0 '
      'taskOverlaps=${_taskOverlaps(overview, overviewProjection)} '
      'haloOverlaps=${focusLodSameHaloOverlaps(overviewProjection.satellites)} duplicates=0',
    );
    // ignore: avoid_print
    print(
      'FOCUS_LOD_B tasks=${flower.taskIds.length} fullFlow=${_fullFlow(flower, focused)} '
      'satellites=${focused.satellites.length} drift=0 '
      'taskOverlaps=${_taskOverlaps(flower, focused)} '
      'haloOverlaps=${focusLodSameHaloOverlaps(focused.satellites)} duplicates=0',
    );
    // ignore: avoid_print
    print(
      'FOCUS_LOD_D satellites=${halo.satellites.length} overflow=${halo.overflows.single.remainder} '
      'taskOverlaps=${_taskOverlaps(crowded, halo)} haloOverlaps=0',
    );
    final both = _closeBoth();
    final bothProjection = _project(both);
    // ignore: avoid_print
    print(
      'FOCUS_LOD_E satellites=${closeProjection.satellites.length} '
      'taskOverlaps=${_taskOverlaps(close, closeProjection)} '
      'haloOverlaps=${focusLodSameHaloOverlaps(closeProjection.satellites)} '
      'maxRing=${_maxRing(close, closeProjection).toStringAsFixed(1)} '
      'crossHalo=${_crossHaloOverlaps(bothProjection)}',
    );
  });

  testWidgets('satellite shows provider and bookmark without title text', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: FocusLodSatelliteMark(
            objectId: 'mail-1',
            kind: 'email',
            title: 'Скрытое письмо',
            provider: 'gmail',
            bookmarkColor: 'blue',
            onTap: () {},
          ),
        ),
      ),
    );
    expect(find.text('Скрытое письмо'), findsNothing);
    expect(find.byType(ProviderSourceIcon), findsOneWidget);
    expect(
      find.byKey(const ValueKey('focus-lod-bookmark-mail-1')),
      findsOneWidget,
    );
  });

  testWidgets('focus lod is an explicit task lens and does not move tasks', (
    tester,
  ) async {
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
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Фокус LOD'), findsNothing);
    expect(find.text('Текущий'), findsNothing);
    expect(find.text('Preserve'), findsOneWidget);
    expect(find.byKey(const ValueKey('hybrid-glyph-email-1')), findsOneWidget);
    expect(harness.graph.positions['task-a'], isNotNull);

    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    expect(harness.graph.mode.name, 'people');
    expect(find.text('Фокус LOD'), findsNothing);
    expect(find.text('Анна'), findsOneWidget);
  });
}

class _Fixture {
  _Fixture({required this.nodes, required this.edges, required this.positions});

  final List<SecretaryObject> nodes;
  final List<SecretaryEdge> edges;
  final Map<String, Offset> positions;

  List<String> get taskIds => nodes
      .where((node) => node.kind == 'task')
      .map((node) => node.id)
      .toList();
}

FocusLodProjection _project(_Fixture fixture, {String? selectedObjectId}) {
  final beforeNodes = fixture.nodes.map((node) => node.id).toList();
  final beforeEdges = fixture.edges.map((edge) => edge.id).toList();
  final beforePositions = Map<String, Offset>.from(fixture.positions);
  final projection = projectFocusLod(
    nodes: fixture.nodes,
    edges: fixture.edges,
    positions: fixture.positions,
    selectedObjectId: selectedObjectId,
    isBookmarked: (objectId) => objectId == 'mail-book',
  );
  expect(fixture.nodes.map((node) => node.id).toList(), beforeNodes);
  expect(fixture.edges.map((edge) => edge.id).toList(), beforeEdges);
  expect(fixture.positions, beforePositions);
  return projection;
}

void _expectStableTasks(_Fixture fixture, {String? selectedObjectId}) {
  final projection = _project(fixture, selectedObjectId: selectedObjectId);
  for (final id in fixture.taskIds) {
    expect(projection.fullCardIds, contains(id));
    expect(fixture.positions.containsKey(id), isTrue);
  }
}

void _expectRepeatable(_Fixture fixture) {
  final left = _project(fixture);
  final right = _project(fixture);
  expect(
    left.satellites.map(
      (item) => (item.objectId, item.anchorTaskId, item.topLeft),
    ),
    right.satellites.map(
      (item) => (item.objectId, item.anchorTaskId, item.topLeft),
    ),
  );
}

int _fullFlow(_Fixture fixture, FocusLodProjection projection) {
  return fixture.nodes
      .where(
        (node) =>
            node.kind != 'task' && projection.fullCardIds.contains(node.id),
      )
      .length;
}

int _duplicates(_Fixture fixture, FocusLodProjection projection) {
  final seen = <String, int>{};
  for (final node in fixture.nodes) {
    if (!focusLodKindIsCompactable(node.kind)) {
      continue;
    }
    var count = 0;
    if (projection.fullCardIds.contains(node.id)) {
      count += 1;
    }
    count += projection.satellites
        .where((item) => item.objectId == node.id)
        .length;
    seen[node.id] = count;
  }
  return seen.values.where((count) => count > 1).length;
}

int _taskOverlaps(_Fixture fixture, FocusLodProjection projection) {
  final tasks = fixture.taskIds.map(
    (id) => GraphLayout.nodeRectAt(fixture.positions[id]!),
  );
  return focusLodTaskOverlaps(
    marks: [
      ...projection.satellites.map((item) => item.rect),
      ...projection.overflows.map((item) => item.rect),
    ],
    taskRects: tasks,
  );
}

int _crossHaloOverlaps(FocusLodProjection projection) {
  final satellites = projection.satellites;
  var count = 0;
  for (var i = 0; i < satellites.length; i++) {
    for (var j = i + 1; j < satellites.length; j++) {
      if (satellites[i].anchorTaskId == satellites[j].anchorTaskId) {
        continue;
      }
      final left = satellites[i].rect;
      final right = satellites[j].rect;
      final overlapLeft = left.left > right.left ? left.left : right.left;
      final overlapRight = left.right < right.right ? left.right : right.right;
      final overlapTop = left.top > right.top ? left.top : right.top;
      final overlapBottom = left.bottom < right.bottom
          ? left.bottom
          : right.bottom;
      if (overlapRight - overlapLeft > 0.5 &&
          overlapBottom - overlapTop > 0.5) {
        count += 1;
      }
    }
  }
  return count;
}

_Fixture _closeBoth() {
  final nodes = <SecretaryObject>[
    _object('task-a', 'А'),
    _object('task-b', 'Б'),
    for (var i = 0; i < 8; i++)
      _object('mail-a-$i', 'Рядом A $i', kind: 'web_page'),
    for (var i = 0; i < 8; i++)
      _object('mail-b-$i', 'Рядом B $i', kind: 'note'),
  ];
  return _Fixture(
    nodes: nodes,
    edges: [
      for (var i = 0; i < 8; i++) _edge('task-a', 'mail-a-$i'),
      for (var i = 0; i < 8; i++) _edge('task-b', 'mail-b-$i'),
    ],
    positions: {
      'task-a': const Offset(0, 0),
      'task-b': const Offset(200, 0),
      for (var i = 0; i < 8; i++) 'mail-a-$i': Offset(40, 300.0 + i),
      for (var i = 0; i < 8; i++) 'mail-b-$i': Offset(240, 300.0 + i),
    },
  );
}

double _maxRing(_Fixture fixture, FocusLodProjection projection) {
  var maxDistance = 0.0;
  for (final satellite in projection.satellites) {
    final task = fixture.positions[satellite.anchorTaskId]!;
    final taskCenter =
        task + const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
    final satelliteCenter =
        satellite.topLeft +
        const Offset(kFocusLodSatelliteSize / 2, kFocusLodSatelliteSize / 2);
    final distance = (satelliteCenter - taskCenter).distance;
    if (distance > maxDistance) {
      maxDistance = distance;
    }
  }
  return maxDistance;
}

_Fixture _overview() {
  final nodes = <SecretaryObject>[
    for (var i = 0; i < 5; i++) _object('task-$i', 'Задача $i'),
    for (var i = 0; i < 8; i++)
      _object('mail-$i', 'Письмо $i', kind: 'email', provider: 'gmail'),
  ];
  final edges = <SecretaryEdge>[
    for (var i = 0; i < 8; i++) _edge('task-${i % 4}', 'mail-$i'),
  ];
  return _Fixture(
    nodes: nodes,
    edges: edges,
    positions: GraphLayout.computePositions(
      nodes: nodes,
      edges: edges,
      rootId: 'task-0',
      existing: const {},
      freshRoot: true,
    ),
  );
}

_Fixture _flower() {
  final nodes = <SecretaryObject>[
    _object('task-s', 'Выбранная'),
    _object('task-o', 'Соседняя'),
    for (var i = 0; i < 10; i++)
      _object('mail-s-$i', 'Письмо $i', kind: 'note'),
    for (var i = 0; i < 4; i++) _object('mail-o-$i', 'Файл $i', kind: 'file'),
  ];
  final edges = <SecretaryEdge>[
    _edge('task-s', 'task-o', id: 'edge-tasks', type: 'depends_on'),
    for (var i = 0; i < 10; i++) _edge('task-s', 'mail-s-$i'),
    for (var i = 0; i < 4; i++) _edge('task-o', 'mail-o-$i'),
  ];
  return _Fixture(
    nodes: nodes,
    edges: edges,
    positions: GraphLayout.computePositions(
      nodes: nodes,
      edges: edges,
      rootId: 'task-s',
      existing: const {},
      freshRoot: true,
    ),
  );
}

_Fixture _shared() {
  return _Fixture(
    nodes: [
      _object('task-near', 'Ближняя'),
      _object('task-far', 'Дальняя'),
      _object('mail-shared', 'Общее письмо', kind: 'email'),
    ],
    edges: [
      _edge('task-near', 'mail-shared'),
      _edge('task-far', 'mail-shared'),
    ],
    positions: {
      'task-near': const Offset(0, 0),
      'task-far': const Offset(800, 0),
      'mail-shared': const Offset(40, 220),
    },
  );
}

_Fixture _crowded() {
  final nodes = <SecretaryObject>[
    _object('task-h', 'Плотная'),
    _object(
      'mail-book',
      'Закладка',
      kind: 'email',
      updatedAt: '2026-01-01T00:00:00Z',
    ),
    _object(
      'mail-old',
      'Старое',
      kind: 'email',
      updatedAt: '2020-01-01T00:00:00Z',
    ),
    for (var i = 0; i < 33; i++)
      _object(
        'mail-$i',
        'Поток $i',
        kind: 'email',
        updatedAt: '2026-02-${(i % 27) + 1}T00:00:00Z',
      ),
  ];
  return _Fixture(
    nodes: nodes,
    edges: [
      for (final node in nodes)
        if (node.kind != 'task') _edge('task-h', node.id),
    ],
    positions: {
      'task-h': const Offset(0, 0),
      for (final node in nodes)
        if (node.kind != 'task') node.id: const Offset(900, 900),
    },
  );
}

_Fixture _close() {
  final nodes = <SecretaryObject>[
    _object('task-a', 'А'),
    _object('task-b', 'Б'),
    for (var i = 0; i < 8; i++)
      _object('mail-$i', 'Рядом $i', kind: 'web_page'),
  ];
  return _Fixture(
    nodes: nodes,
    edges: [for (var i = 0; i < 8; i++) _edge('task-a', 'mail-$i')],
    positions: {
      'task-a': const Offset(0, 0),
      'task-b': const Offset(200, 0),
      for (var i = 0; i < 8; i++) 'mail-$i': Offset(40, 300.0 + i),
    },
  );
}

_Fixture _keptKinds() {
  final nodes = [
    _object('task-k', 'Задача'),
    _object('person-1', 'Анна', kind: 'person'),
    _object('project-1', 'Проект', kind: 'project'),
    _object('label-1', 'Метка', kind: 'label'),
    _object('activity-1', 'План', kind: 'scheduled_activity'),
    _object('hint-1', 'Подсказка', kind: 'temporal_hint'),
    _object('mystery-1', 'Неизвестно', kind: 'mystery'),
  ];
  return _Fixture(
    nodes: nodes,
    edges: [_edge('task-k', 'person-1')],
    positions: {
      for (var i = 0; i < nodes.length; i++) nodes[i].id: Offset(i * 240, 0),
    },
  );
}

SecretaryObject _object(
  String id,
  String title, {
  String kind = 'task',
  String? provider,
  String updatedAt = '2026-01-01T00:00:00Z',
}) {
  return SecretaryObject(
    id: id,
    kind: kind,
    title: title,
    provider: provider,
    metadata: const {},
    origin: 'user',
    state: 'confirmed',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: updatedAt,
  );
}

SecretaryEdge _edge(
  String sourceId,
  String targetId, {
  String? id,
  String type = 'references',
}) {
  return SecretaryEdge(
    id: id ?? '$sourceId-$targetId',
    sourceId: sourceId,
    targetId: targetId,
    type: type,
    origin: 'user',
    state: 'confirmed',
    metadata: const {},
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
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
              provider: 'gmail',
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
