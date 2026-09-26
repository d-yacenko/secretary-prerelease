import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/focus_lod.dart';
import 'package:personal_secretary/graph/fcose_graph_refiner.dart';
import 'package:personal_secretary/graph/graph_geometry.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/graph_workspace_screen.dart';
import 'package:personal_secretary/graph/hybrid_focus_lod.dart';

import 'graph_test_harness.dart';

void main() {
  test('focused card stays inside the medium-card range and glyphs stay 32', () {
    expect(kHybridFocusedCardWidth, inInclusiveRange(150, 160));
    expect(kHybridFocusedCardHeight, inInclusiveRange(72, 80));
    expect(kHybridGlyphSize, 32);
  });

  test('preserve and relax local flower metrics', () {
    final cases = <String, _Case>{
      'distant': _Case(_distant(), 'task-a'),
      'flower': _Case(_flower(12), 'task-a'),
      'obstacle': _Case(_obstacle(), 'task-a'),
      'mixed': _Case(_mixed(), 'task-a'),
      'overview': _Case(_distant(), null),
    };
    for (final mode in FcoseRefinementMode.values) {
      for (final entry in cases.entries) {
        final metrics = _metrics(
          mode,
          entry.value.fixture,
          selectedObjectId: entry.value.selectedObjectId,
        );
        // ignore: avoid_print
        print('V6_${mode.name}_${entry.key} $metrics');
        expect(metrics.taskDrift, 0);
        expect(metrics.duplicates, 0);
        expect(metrics.repeatable, isTrue);
        if (entry.key != 'overview') {
          expect(metrics.focused, greaterThan(0));
          expect(metrics.maxFocusedRadius, lessThanOrEqualTo(metrics.limit));
          expect(metrics.focusedTaskOverlaps, 0);
          expect(metrics.focusedFocusedOverlaps, 0);
          final starts = _present(
            mode,
            entry.value.fixture,
            selectedObjectId: entry.value.selectedObjectId,
          );
          final startRects = [
            for (final node in starts.scene.nodes)
              if (node.width == kHybridFocusedCardWidth) node.rect,
          ];
          final taskRects = [
            for (final id in entry.value.fixture.taskIds)
              GraphLayout.nodeRectAt(entry.value.fixture.positions[id]!),
          ];
          expect(_pairOverlaps(startRects, taskRects), 0);
          expect(_selfOverlaps(startRects), 0);
        } else {
          expect(metrics.focused, 0);
          expect(metrics.compact, greaterThan(0));
          expect(metrics.presentationBounds.width, lessThan(1000));
          expect(
            metrics.canonicalBounds.width,
            greaterThan(metrics.presentationBounds.width * 4),
          );
        }
      }
    }

    final distant = _metrics(
      FcoseRefinementMode.preserve,
      _distant(),
      selectedObjectId: 'task-a',
    );
    expect(distant.focused, 1);
    expect(distant.maxStartDistanceFromCanonical, greaterThan(1000));
    expect(distant.maxFocusedRadius, lessThan(hybridFocusedLocalityLimit(1)));
    expect(
      distant.canonicalBounds.width,
      greaterThan(distant.presentationBounds.width * 4),
    );
    final canonicalFit = GraphLayout.fitTransform(
      positions: _distant().positions,
      viewportSize: const Size(1280, 800),
    );
    final presentationFit = hybridFitTransform(
      graphBounds: distant.presentationBounds,
      viewportSize: const Size(1280, 800),
    );
    expect(presentationFit.getMaxScaleOnAxis(), greaterThan(0.2));
    expect(
      canonicalFit.getMaxScaleOnAxis(),
      lessThan(presentationFit.getMaxScaleOnAxis()),
    );
  });

  test('focus change keeps tasks and opens the next flower locally', () {
    final fixture = _focusChange();
    final before = Map<String, Offset>.from(fixture.positions);
    final fromA = _present(
      FcoseRefinementMode.preserve,
      fixture,
      selectedObjectId: 'task-a',
    );
    final toB = _present(
      FcoseRefinementMode.preserve,
      fixture,
      selectedObjectId: 'task-b',
    );
    expect(fixture.positions, before);
    for (final id in ['task-a', 'task-b']) {
      expect(fromA.displayTopLeft[id], before[id]);
      expect(toB.displayTopLeft[id], before[id]);
    }
    expect(
      fromA.lod.satellites.map((item) => item.objectId),
      isNot(contains('mail-a-0')),
    );
    expect(
      toB.lod.satellites.map((item) => item.objectId),
      containsAll(['mail-a-0', 'mail-a-1']),
    );
    expect(
      toB.scene.nodeById('mail-b-0')!.width,
      kHybridFocusedCardWidth,
    );
    final taskCenter = before['task-b']! +
        const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
    final card = toB.displayTopLeft['mail-b-0']! +
        const Offset(kHybridFocusedCardWidth / 2, kHybridFocusedCardHeight / 2);
    expect(
      (card - taskCenter).distance,
      lessThanOrEqualTo(hybridFocusedLocalityLimit(2)),
    );
    final peripheral = fromA.lod.satellites
        .map((item) => item.objectId)
        .toSet()
        .intersection(toB.lod.satellites.map((item) => item.objectId).toSet());
    var moved = 0;
    var maxMove = 0.0;
    for (final id in peripheral) {
      final distance =
          (fromA.displayTopLeft[id]! - toB.displayTopLeft[id]!).distance;
      if (distance > 1) {
        moved += 1;
      }
      if (distance > maxMove) {
        maxMove = distance;
      }
    }
    // ignore: avoid_print
    print(
      'V6_FOCUS peripheral=${peripheral.length} moved=$moved max=$maxMove '
      'boundsA=${hybridPresentationBounds(fromA).size} '
      'boundsB=${hybridPresentationBounds(toB).size}',
    );
    expect(peripheral, contains('mail-c'));
    expect(hybridPresentationBounds(fromA).width, lessThan(4000));
    expect(hybridPresentationBounds(toB).width, lessThan(4000));
  });

  test('non-local refinement returns the whole flower to its rings', () {
    final fixture = _flower(4);
    final dispersed = presentHybridFocus(
      nodes: fixture.nodes,
      edges: fixture.edges,
      positions: fixture.positions,
      selectedObjectId: 'task-a',
      refiner: _DispersingRefiner(),
    );
    expect(dispersed.warning, isNotNull);
    for (final node in dispersed.scene.nodes) {
      if (node.width != kHybridFocusedCardWidth) {
        continue;
      }
      expect(dispersed.displayTopLeft[node.id], node.topLeft);
      expect(
        (node.topLeft - fixture.positions[node.id]!).distance,
        greaterThan(1000),
      );
    }
    expect(dispersed.displayTopLeft['task-a'], fixture.positions['task-a']);
  });

  test('selected edge border uses the focused card size', () {
    final fixture = _distant();
    final presentation = _present(
      FcoseRefinementMode.preserve,
      fixture,
      selectedObjectId: 'task-a',
    );
    final flow = presentation.scene.nodeById('mail-far')!;
    final task = presentation.scene.nodeById('task-a')!;
    final flowTop = presentation.displayTopLeft['mail-far']!;
    final flowCenter = flowTop + Offset(flow.width / 2, flow.height / 2);
    final taskCenter = task.center;
    final focusedEnd = GraphLayout.computeEdgeEndpoints(
      sourceCenter: flowCenter,
      targetCenter: taskCenter,
      nodeWidth: flow.width,
      nodeHeight: flow.height,
    ).start;
    final fullCardEnd = GraphLayout.computeEdgeEndpoints(
      sourceCenter: flowCenter,
      targetCenter: taskCenter,
    ).start;
    expect(flow.width, kHybridFocusedCardWidth);
    expect(flow.height, kHybridFocusedCardHeight);
    expect(focusedEnd, isNot(fullCardEnd));
  });

  testWidgets('current renderer stays default and hybrid does not persist', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final harness = GraphTestHarness(_workspaceMock());
    harness.configure();
    await harness.graph.loadOverview();
    final positions = Map<String, Offset>.from(harness.graph.positions);
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
    expect(find.text('Preserve'), findsNothing);
    await tester.tap(find.text('LOD+fCoSE'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('hybrid-glyph-email-1')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('graph_node_email-1')), findsOneWidget);
    expect(find.byType(HybridFocusedFlowCard), findsOneWidget);
    await tester.tap(find.byType(HybridFocusedFlowCard));
    await tester.pumpAndSettle();
    expect(harness.graph.selectedObjectId, 'email-1');
    await tester.tap(find.text('Текущий'));
    await tester.pumpAndSettle();
    expect(harness.graph.positions, positions);
    expect(find.byType(HybridFocusedFlowCard), findsNothing);
  });
}

class _DispersingRefiner implements GraphGeometryRefiner {
  @override
  GraphGeometryResult refine(GraphGeometryScene scene) {
    return GraphGeometryResult.success(
      nodes: {
        for (final node in scene.nodes)
          node.id: node.fixed
              ? node.rect
              : node.rect.shift(const Offset(4000, 4000)),
      },
    );
  }
}

class _Case {
  const _Case(this.fixture, this.selectedObjectId);

  final _Fixture fixture;
  final String? selectedObjectId;
}

class _Metrics {
  const _Metrics({
    required this.taskDrift,
    required this.focused,
    required this.compact,
    required this.focusedMoved,
    required this.maxFocusedDisplacement,
    required this.medianFocusedRadius,
    required this.maxFocusedRadius,
    required this.limit,
    required this.focusedTaskOverlaps,
    required this.focusedFocusedOverlaps,
    required this.focusedCompactOverlaps,
    required this.compactTaskOverlaps,
    required this.compactCompactOverlaps,
    required this.repeatable,
    required this.duplicates,
    required this.presentationBounds,
    required this.canonicalBounds,
    required this.maxStartDistanceFromCanonical,
  });

  final double taskDrift;
  final int focused;
  final int compact;
  final int focusedMoved;
  final double maxFocusedDisplacement;
  final double medianFocusedRadius;
  final double maxFocusedRadius;
  final double limit;
  final int focusedTaskOverlaps;
  final int focusedFocusedOverlaps;
  final int focusedCompactOverlaps;
  final int compactTaskOverlaps;
  final int compactCompactOverlaps;
  final bool repeatable;
  final int duplicates;
  final Rect presentationBounds;
  final Rect canonicalBounds;
  final double maxStartDistanceFromCanonical;

  @override
  String toString() {
    return 'taskDrift=$taskDrift focused=$focused compact=$compact '
        'focusedMoved=$focusedMoved maxDisp=${maxFocusedDisplacement.toStringAsFixed(1)} '
        'medianR=${medianFocusedRadius.toStringAsFixed(1)} '
        'maxR=${maxFocusedRadius.toStringAsFixed(1)} limit=${limit.toStringAsFixed(1)} '
        'fTask=$focusedTaskOverlaps fFocus=$focusedFocusedOverlaps '
        'fCompact=$focusedCompactOverlaps cTask=$compactTaskOverlaps '
        'cCompact=$compactCompactOverlaps repeatable=$repeatable '
        'duplicates=$duplicates '
        'presentation=${presentationBounds.width.toStringAsFixed(0)}x${presentationBounds.height.toStringAsFixed(0)} '
        'canonical=${canonicalBounds.width.toStringAsFixed(0)}x${canonicalBounds.height.toStringAsFixed(0)}';
  }
}

_Metrics _metrics(
  FcoseRefinementMode mode,
  _Fixture fixture, {
  String? selectedObjectId,
}) {
  final first = _present(mode, fixture, selectedObjectId: selectedObjectId);
  final second = _present(mode, fixture, selectedObjectId: selectedObjectId);
  final taskCenter = selectedObjectId == null
      ? null
      : fixture.positions[selectedObjectId]! +
            const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
  final focused = [
    for (final node in first.scene.nodes)
      if (node.width == kHybridFocusedCardWidth) node,
  ];
  final radii = <double>[];
  var moved = 0;
  var maxDisp = 0.0;
  var maxCanonical = 0.0;
  for (final node in focused) {
    final shown = first.displayTopLeft[node.id]!;
    final displacement = (shown - node.topLeft).distance;
    if (displacement > 1) {
      moved += 1;
    }
    if (displacement > maxDisp) {
      maxDisp = displacement;
    }
    final canonical = (node.topLeft - fixture.positions[node.id]!).distance;
    if (canonical > maxCanonical) {
      maxCanonical = canonical;
    }
    if (taskCenter != null) {
      final center = shown +
          const Offset(
            kHybridFocusedCardWidth / 2,
            kHybridFocusedCardHeight / 2,
          );
      radii.add((center - taskCenter).distance);
    }
  }
  radii.sort();
  final focusedRects = [
    for (final node in focused)
      Rect.fromLTWH(
        first.displayTopLeft[node.id]!.dx,
        first.displayTopLeft[node.id]!.dy,
        node.width,
        node.height,
      ),
  ];
  final compactRects = [
    for (final node in first.scene.nodes)
      if (node.width == kHybridGlyphSize)
        Rect.fromLTWH(
          first.displayTopLeft[node.id]!.dx,
          first.displayTopLeft[node.id]!.dy,
          node.width,
          node.height,
        ),
  ];
  final taskRects = [
    for (final id in fixture.taskIds)
      GraphLayout.nodeRectAt(fixture.positions[id]!),
  ];
  return _Metrics(
    taskDrift: _taskDrift(first, fixture),
    focused: focused.length,
    compact: first.lod.satellites.length,
    focusedMoved: moved,
    maxFocusedDisplacement: maxDisp,
    medianFocusedRadius: radii.isEmpty ? 0 : radii[radii.length ~/ 2],
    maxFocusedRadius: radii.isEmpty ? 0 : radii.last,
    limit: hybridFocusedLocalityLimit(focused.length),
    focusedTaskOverlaps: _pairOverlaps(focusedRects, taskRects),
    focusedFocusedOverlaps: _selfOverlaps(focusedRects),
    focusedCompactOverlaps: _pairOverlaps(focusedRects, compactRects),
    compactTaskOverlaps: _pairOverlaps(compactRects, taskRects),
    compactCompactOverlaps: _selfOverlaps(compactRects),
    repeatable: _same(first, second),
    duplicates: _duplicates(fixture, first),
    presentationBounds: hybridPresentationBounds(first),
    canonicalBounds: GraphLayout.computeBounds(fixture.positions),
    maxStartDistanceFromCanonical: maxCanonical,
  );
}

double _taskDrift(HybridFocusPresentation presentation, _Fixture fixture) {
  var drift = 0.0;
  for (final id in fixture.taskIds) {
    final shown = presentation.displayTopLeft[id];
    final canonical = fixture.positions[id];
    if (shown == null || canonical == null) {
      continue;
    }
    drift = math.max(drift, (shown - canonical).distance);
  }
  return drift;
}

HybridFocusPresentation _present(
  FcoseRefinementMode mode,
  _Fixture fixture, {
  String? selectedObjectId,
}) {
  final before = Map<String, Offset>.from(fixture.positions);
  final presentation = presentHybridFocus(
    nodes: fixture.nodes,
    edges: fixture.edges,
    positions: fixture.positions,
    selectedObjectId: selectedObjectId,
    refiner: FcoseGraphRefiner(mode: mode),
  );
  expect(fixture.positions, before);
  return presentation;
}

bool _same(HybridFocusPresentation left, HybridFocusPresentation right) {
  if (left.displayTopLeft.length != right.displayTopLeft.length) {
    return false;
  }
  for (final entry in left.displayTopLeft.entries) {
    final other = right.displayTopLeft[entry.key];
    if (other == null || (other - entry.value).distance > 0.01) {
      return false;
    }
  }
  return true;
}

int _duplicates(_Fixture fixture, HybridFocusPresentation presentation) {
  var bad = 0;
  for (final node in fixture.nodes.where(
    (item) => focusLodKindIsCompactable(item.kind),
  )) {
    var count = 0;
    if (presentation.lod.fullCardIds.contains(node.id)) {
      count += 1;
    }
    count += presentation.lod.satellites
        .where((item) => item.objectId == node.id)
        .length;
    if (count > 1) {
      bad += 1;
    }
  }
  return bad;
}

int _pairOverlaps(List<Rect> left, List<Rect> right) {
  var count = 0;
  for (final a in left) {
    for (final b in right) {
      if (_area(a, b) > 0.5) {
        count += 1;
      }
    }
  }
  return count;
}

int _selfOverlaps(List<Rect> rects) {
  var count = 0;
  for (var i = 0; i < rects.length; i++) {
    for (var j = i + 1; j < rects.length; j++) {
      if (_area(rects[i], rects[j]) > 0.5) {
        count += 1;
      }
    }
  }
  return count;
}

double _area(Rect left, Rect right) {
  final overlap = left.intersect(right);
  if (overlap.isEmpty) {
    return 0;
  }
  return overlap.width * overlap.height;
}

class _Fixture {
  const _Fixture({
    required this.nodes,
    required this.edges,
    required this.positions,
  });

  final List<SecretaryObject> nodes;
  final List<SecretaryEdge> edges;
  final Map<String, Offset> positions;

  Iterable<String> get taskIds => [
    for (final node in nodes)
      if (node.kind == 'task') node.id,
  ];
}

_Fixture _distant() {
  return _Fixture(
    nodes: [
      _object('task-a', 'Задача'),
      _object('task-b', 'Сосед'),
      _object('mail-far', 'Далёкое письмо', kind: 'email', provider: 'gmail'),
    ],
    edges: [_edge('task-a', 'mail-far')],
    positions: {
      'task-a': const Offset(0, 0),
      'task-b': const Offset(420, 0),
      'mail-far': const Offset(8000, 6000),
    },
  );
}

_Fixture _flower(int count) {
  return _Fixture(
    nodes: [
      _object('task-a', 'Задача'),
      for (var i = 0; i < count; i++)
        _object(
          'mail-$i',
          'Письмо $i',
          kind: 'email',
          updatedAt: '2026-02-${(i + 1).toString().padLeft(2, '0')}T00:00:00Z',
        ),
    ],
    edges: [for (var i = 0; i < count; i++) _edge('task-a', 'mail-$i')],
    positions: {
      'task-a': const Offset(0, 0),
      for (var i = 0; i < count; i++) 'mail-$i': Offset(5000, 4000 + i * 20),
    },
  );
}

_Fixture _obstacle() {
  return _Fixture(
    nodes: [
      _object('task-a', 'Задача'),
      _object('task-b', 'Рядом'),
      for (var i = 0; i < 6; i++)
        _object('mail-$i', 'Письмо $i', kind: 'email'),
    ],
    edges: [for (var i = 0; i < 6; i++) _edge('task-a', 'mail-$i')],
    positions: {
      'task-a': const Offset(0, 0),
      'task-b': const Offset(220, 0),
      for (var i = 0; i < 6; i++) 'mail-$i': const Offset(9000, 1000),
    },
  );
}

_Fixture _mixed() {
  return _Fixture(
    nodes: [
      _object('task-a', 'Выбранная'),
      _object('task-b', 'Соседняя'),
      for (var i = 0; i < 4; i++)
        _object('focus-$i', 'Фокус $i', kind: 'email'),
      for (var i = 0; i < 6; i++)
        _object('halo-$i', 'Гало $i', kind: 'file'),
    ],
    edges: [
      for (var i = 0; i < 4; i++) _edge('task-a', 'focus-$i'),
      for (var i = 0; i < 6; i++) _edge('task-b', 'halo-$i'),
    ],
    positions: {
      'task-a': const Offset(0, 0),
      'task-b': const Offset(640, 40),
      for (var i = 0; i < 4; i++) 'focus-$i': const Offset(7000, 2000),
      for (var i = 0; i < 6; i++) 'halo-$i': Offset(900, 800 + i * 16),
    },
  );
}

_Fixture _focusChange() {
  return _Fixture(
    nodes: [
      _object('task-a', 'A'),
      _object('task-b', 'B'),
      _object('task-c', 'C'),
      _object('mail-a-0', 'A0', kind: 'email'),
      _object('mail-a-1', 'A1', kind: 'email'),
      _object('mail-b-0', 'B0', kind: 'file'),
      _object('mail-b-1', 'B1', kind: 'file'),
      _object('mail-c', 'Периферия', kind: 'note'),
    ],
    edges: [
      _edge('task-a', 'mail-a-0'),
      _edge('task-a', 'mail-a-1'),
      _edge('task-b', 'mail-b-0'),
      _edge('task-b', 'mail-b-1'),
      _edge('task-c', 'mail-c'),
    ],
    positions: {
      'task-a': const Offset(0, 0),
      'task-b': const Offset(520, 0),
      'task-c': const Offset(1040, 0),
      'mail-a-0': const Offset(6000, 1000),
      'mail-a-1': const Offset(6200, 1000),
      'mail-b-0': const Offset(6400, 1000),
      'mail-b-1': const Offset(6600, 1000),
      'mail-c': const Offset(9000, 240),
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
    occurredAt: updatedAt,
  );
}

SecretaryEdge _edge(String sourceId, String targetId) {
  return SecretaryEdge(
    id: '$sourceId-$targetId',
    sourceId: sourceId,
    targetId: targetId,
    type: 'references',
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
            graphObjectJson(
              id: 'email-1',
              title: 'Письмо контекста',
              kind: 'email',
              provider: 'gmail',
            ),
          ],
          edges: [
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
          ],
        ),
      );
    }
    return http.Response('{}', 404);
  });
}
