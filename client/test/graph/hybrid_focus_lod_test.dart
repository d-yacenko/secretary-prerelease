import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/fcose_graph_refiner.dart';
import 'package:personal_secretary/graph/focus_lod.dart';
import 'package:personal_secretary/graph/graph_geometry.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/graph_workspace_screen.dart';
import 'package:personal_secretary/graph/hybrid_focus_lod.dart';
import 'package:personal_secretary/ui/provider_icon.dart';

import 'graph_test_harness.dart';

void main() {
  test('hybrid presentation does not import fcose directly', () {
    final source = File('lib/graph/hybrid_focus_lod.dart').readAsStringSync();
    expect(source.contains('package:fcose'), isFalse);
    expect(source.contains('drawLine'), isTrue);
    expect(source.contains('arrowAtMark'), isTrue);
  });

  test('preserve and relax metrics on hybrid fixtures', () {
    final cases = <String, _Fixture>{
      'overview': _overview(),
      'flower': _flower(),
      'close': _close(),
      'mixed': _mixed(),
      'high': _high(),
    };
    for (final mode in FcoseRefinementMode.values) {
      for (final entry in cases.entries) {
        final selected = entry.key == 'flower' || entry.key == 'mixed'
            ? 'task-s'
            : null;
        final observation = _observe(
          mode,
          entry.value,
          selectedObjectId: selected,
        );
        // ignore: avoid_print
        print('HYBRID_${mode.name}_${entry.key} $observation');
        expect(observation.completed, isTrue, reason: observation.error);
        expect(observation.taskDrift <= 1, isTrue);
        expect(observation.displayedTaskDrift, 0);
        expect(observation.duplicates, 0);
        if (entry.key == 'high') {
          expect(observation.compact, lessThanOrEqualTo(20));
          expect(observation.overflow, 16);
        }
        if (entry.key == 'flower') {
          expect(observation.fullFlow, 10);
          expect(observation.compact, 8);
        }
      }
    }

    final close = _close();
    final raw = projectFocusLod(
      nodes: close.nodes,
      edges: close.edges,
      positions: close.positions,
      selectedObjectId: null,
    );
    final rawCross = _crossOverlaps(raw.satellites.map((item) => item.rect));
    final hybrid = _present(FcoseRefinementMode.preserve, close);
    final hybridCross = _crossOverlaps(_compactRects(hybrid));
    expect(
      hybrid.hairlines,
      hasLength(close.nodes.where((node) => node.kind != 'task').length),
    );
    final startCross = _crossOverlaps(_startCompactRects(hybrid));
    // ignore: avoid_print
    print(
      'HYBRID_CLOSE rawV4=$rawCross start32=$startCross '
      'preserve=$hybridCross relax=${_crossOverlaps(_compactRects(_present(FcoseRefinementMode.relax, close)))}',
    );

    final focus = _focusChange();
    final beforePositions = Map<String, Offset>.from(focus.positions);
    final fromA = _present(
      FcoseRefinementMode.preserve,
      focus,
      selectedObjectId: 'task-a',
    );
    final toB = _present(
      FcoseRefinementMode.preserve,
      focus,
      selectedObjectId: 'task-b',
    );
    expect(focus.positions, beforePositions);
    var moved = 0;
    var maxMove = 0.0;
    final still = fromA.lod.satellites
        .map((item) => item.objectId)
        .toSet()
        .intersection(toB.lod.satellites.map((item) => item.objectId).toSet());
    for (final id in still) {
      final distance =
          (fromA.displayTopLeft[id]! - toB.displayTopLeft[id]!).distance;
      if (distance > 1) {
        moved += 1;
      }
      if (distance > maxMove) {
        maxMove = distance;
      }
    }
    var taskDrift = 0.0;
    for (final id in focus.taskIds) {
      final distance = (focus.positions[id]! - beforePositions[id]!).distance;
      if (distance > taskDrift) {
        taskDrift = distance;
      }
    }
    // ignore: avoid_print
    print(
      'HYBRID_FOCUS stillCompact=${still.length} moved=$moved '
      'max=$maxMove taskDrift=$taskDrift',
    );
    expect(taskDrift, 0);
    expect(still, isNotEmpty);

    final shared = _shared();
    final once = _present(FcoseRefinementMode.preserve, shared);
    expect(once.lod.satellites, hasLength(1));
    expect(
      once.scene.nodes.where((node) => node.id == 'mail-shared'),
      hasLength(1),
    );

    final flower = _flower();
    final scene = _present(
      FcoseRefinementMode.preserve,
      flower,
      selectedObjectId: 'task-s',
    ).scene;
    expect(scene.nodeById('task-s')!.fixed, isTrue);
    expect(scene.nodeById('task-s')!.width, kGraphNodeWidth);
    expect(scene.nodeById('mail-s-0')!.fixed, isFalse);
    expect(scene.nodeById('mail-s-0')!.width, kHybridFocusedCardWidth);
    expect(scene.nodeById('mail-s-0')!.height, kHybridFocusedCardHeight);
    expect(scene.nodeById('mail-o-0')!.width, kHybridGlyphSize);
    expect(scene.nodeById('mail-o-0')!.fixed, isFalse);
    expect(
      scene.edges.any(
        (edge) =>
            edge.sourceId.startsWith('task-') &&
            edge.targetId.startsWith('task-'),
      ),
      isFalse,
    );
    final start = projectFocusLod(
      nodes: flower.nodes,
      edges: flower.edges,
      positions: flower.positions,
      selectedObjectId: 'task-s',
    );
    final compact = start.satellites.first;
    final glyph = scene.nodeById(compact.objectId)!;
    final anchorEdge = scene.edges.firstWhere(
      (edge) => edge.targetId == compact.objectId,
    );
    expect(glyph.width, kHybridGlyphSize);
    expect(glyph.height, kHybridGlyphSize);
    expect(
      glyph.rect.overlaps(scene.nodeById(anchorEdge.sourceId)!.rect),
      isFalse,
    );
    expect(glyph.width, isNot(kFocusLodSatelliteSize));

    final failed = presentHybridFocus(
      nodes: flower.nodes,
      edges: flower.edges,
      positions: flower.positions,
      selectedObjectId: 'task-s',
      refiner: _FailingRefiner(),
    );
    expect(failed.warning, isNotNull);
    expect(failed.displayTopLeft['task-s'], flower.positions['task-s']);
    expect(
      failed.displayTopLeft['mail-o-0'],
      failed.scene.nodeById('mail-o-0')!.topLeft,
    );
  });

  testWidgets('hybrid glyph shows kind and bookmark without title text', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: HybridFlowGlyph(
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
    expect(find.byIcon(Icons.email_outlined), findsOneWidget);
    expect(find.byType(ProviderSourceIcon), findsOneWidget);
    expect(
      find.byKey(const ValueKey('hybrid-bookmark-mail-1')),
      findsOneWidget,
    );
  });

  testWidgets('LOD+fCoSE is explicit and falls back without moving tasks', (
    tester,
  ) async {
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

    for (final label in [
      'Текущий',
      'Эксперимент',
      'ELK',
      'fCoSE',
      'Фокус LOD',
      'LOD+fCoSE',
    ]) {
      expect(find.text(label), findsNothing);
    }
    expect(find.text('Preserve'), findsOneWidget);
    expect(find.text('Relax'), findsOneWidget);

    final positions = Map<String, Offset>.from(harness.graph.positions);
    final nodeIds = harness.graph.nodes.map((node) => node.id).toList();
    expect(find.byKey(const ValueKey('graph-hybrid-fallback')), findsOneWidget);
    expect(find.byKey(const ValueKey('hybrid-glyph-email-1')), findsOneWidget);
    expect(find.text('Письмо контекста'), findsNothing);
    expect(
      find.byWidgetPredicate(
        (widget) =>
            widget is CustomPaint && widget.painter is HybridHairlinePainter,
      ),
      findsOneWidget,
    );
    expect(harness.graph.positions['task-a'], positions['task-a']);
    expect(harness.graph.nodes.map((node) => node.id).toList(), nodeIds);

    await tester.tap(find.byKey(const ValueKey('hybrid-glyph-email-1')));
    await tester.pumpAndSettle();
    expect(harness.graph.selectedObjectId, 'task-a');
    expect(find.text('Письмо контекста'), findsWidgets);
    expect(
      find.text('Этот объект —[Ссылается на]→ Письмо контекста'),
      findsOneWidget,
    );
    expect(find.text('Этот объект —[Зависит от]→ Задача Б'), findsOneWidget);
    expect(harness.graph.positions['task-a'], positions['task-a']);
    expect(find.byKey(const Key('graph_node_task-a')), findsOneWidget);

    await tester.tap(find.text('Люди'));
    await tester.pumpAndSettle();
    expect(find.text('Preserve'), findsNothing);
    expect(find.text('Анна'), findsOneWidget);
  });
}

class _Observation {
  const _Observation({
    required this.completed,
    required this.error,
    required this.taskDrift,
    required this.displayedTaskDrift,
    required this.flowMoved,
    required this.maxFlow,
    required this.fullFlow,
    required this.compact,
    required this.overflow,
    required this.compactTask,
    required this.compactCompact,
    required this.fullTask,
    required this.fullCompact,
    required this.repeatable,
    required this.duplicates,
  });

  final bool completed;
  final String? error;
  final double taskDrift;
  final double displayedTaskDrift;
  final int flowMoved;
  final double maxFlow;
  final int fullFlow;
  final int compact;
  final int overflow;
  final int compactTask;
  final int compactCompact;
  final int fullTask;
  final int fullCompact;
  final bool repeatable;
  final int duplicates;

  @override
  String toString() {
    return 'completed=$completed error=$error taskDrift=${taskDrift.toStringAsFixed(2)} '
        'shownDrift=${displayedTaskDrift.toStringAsFixed(2)} flowMoved=$flowMoved '
        'maxFlow=${maxFlow.toStringAsFixed(1)} fullFlow=$fullFlow compact=$compact '
        'overflow=$overflow compactTask=$compactTask compactCompact=$compactCompact '
        'fullTask=$fullTask fullCompact=$fullCompact repeatable=$repeatable duplicates=$duplicates';
  }
}

_Observation _observe(
  FcoseRefinementMode mode,
  _Fixture fixture, {
  String? selectedObjectId,
}) {
  final first = _present(mode, fixture, selectedObjectId: selectedObjectId);
  final second = _present(mode, fixture, selectedObjectId: selectedObjectId);
  var flowMoved = 0;
  var maxFlow = 0.0;
  for (final node in first.scene.nodes) {
    if (node.fixed) {
      continue;
    }
    final distance = (first.displayTopLeft[node.id]! - node.topLeft).distance;
    if (distance > 1) {
      flowMoved += 1;
    }
    if (distance > maxFlow) {
      maxFlow = distance;
    }
  }
  var shownDrift = 0.0;
  for (final id in fixture.taskIds) {
    final distance =
        (first.displayTopLeft[id]! - fixture.positions[id]!).distance;
    if (distance > shownDrift) {
      shownDrift = distance;
    }
  }
  final compactRects = _compactRects(first);
  final fullRects = _fullFlowRects(first, fixture);
  final taskRects = fixture.taskIds.map(
    (id) => GraphLayout.nodeRectAt(fixture.positions[id]!),
  );
  return _Observation(
    completed: first.result.completed,
    error: first.result.error,
    taskDrift: hybridFixedDrift(first),
    displayedTaskDrift: shownDrift,
    flowMoved: flowMoved,
    maxFlow: maxFlow,
    fullFlow: fullRects.length,
    compact: first.lod.satellites.length,
    overflow: first.lod.overflows.fold<int>(
      0,
      (sum, item) => sum + item.remainder,
    ),
    compactTask: _pairOverlaps(compactRects, taskRects),
    compactCompact: _selfOverlaps(compactRects),
    fullTask: _pairOverlaps(fullRects, taskRects),
    fullCompact: _pairOverlaps(fullRects, compactRects),
    repeatable: _same(first, second),
    duplicates: _duplicates(fixture, first),
  );
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

List<Rect> _compactRects(HybridFocusPresentation presentation) {
  return [
    for (final node in presentation.scene.nodes)
      if (node.width == kHybridGlyphSize)
        Rect.fromLTWH(
          presentation.displayTopLeft[node.id]!.dx,
          presentation.displayTopLeft[node.id]!.dy,
          node.width,
          node.height,
        ),
  ];
}

List<Rect> _startCompactRects(HybridFocusPresentation presentation) {
  return [
    for (final node in presentation.scene.nodes)
      if (node.width == kHybridGlyphSize) node.rect,
  ];
}

List<Rect> _fullFlowRects(
  HybridFocusPresentation presentation,
  _Fixture fixture,
) {
  final compactIds = presentation.lod.satellites
      .map((item) => item.objectId)
      .toSet();
  return [
    for (final node in fixture.nodes)
      if (node.kind != 'task' &&
          presentation.lod.fullCardIds.contains(node.id) &&
          !compactIds.contains(node.id))
        Rect.fromLTWH(
          presentation.displayTopLeft[node.id]!.dx,
          presentation.displayTopLeft[node.id]!.dy,
          presentation.scene.nodeById(node.id)?.width ??
              kHybridFocusedCardWidth,
          presentation.scene.nodeById(node.id)?.height ??
              kHybridFocusedCardHeight,
        ),
  ];
}

int _pairOverlaps(Iterable<Rect> left, Iterable<Rect> right) {
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

int _crossOverlaps(Iterable<Rect> rects) {
  return _selfOverlaps(rects.toList());
}

double _area(Rect a, Rect b) {
  final left = a.left > b.left ? a.left : b.left;
  final right = a.right < b.right ? a.right : b.right;
  final top = a.top > b.top ? a.top : b.top;
  final bottom = a.bottom < b.bottom ? a.bottom : b.bottom;
  if (right - left <= 0.5 || bottom - top <= 0.5) {
    return 0;
  }
  return (right - left) * (bottom - top);
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

bool _same(HybridFocusPresentation left, HybridFocusPresentation right) {
  for (final entry in left.displayTopLeft.entries) {
    final other = right.displayTopLeft[entry.key];
    if (other == null || (entry.value - other).distance > 0.01) {
      return false;
    }
  }
  return left.displayTopLeft.length == right.displayTopLeft.length;
}

class _FailingRefiner implements GraphGeometryRefiner {
  @override
  GraphGeometryResult refine(GraphGeometryScene scene) {
    return const GraphGeometryResult.failure('fcose probe failed');
  }
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
    _object('task-p', 'Дальняя'),
    for (var i = 0; i < 10; i++)
      _object('mail-s-$i', 'Письмо $i', kind: 'note'),
    for (var i = 0; i < 4; i++) _object('mail-o-$i', 'Файл $i', kind: 'file'),
    for (var i = 0; i < 4; i++) _object('mail-p-$i', 'Чат $i', kind: 'chat'),
  ];
  final edges = <SecretaryEdge>[
    _edge('task-s', 'task-o', id: 'edge-tasks', type: 'depends_on'),
    for (var i = 0; i < 10; i++) _edge('task-s', 'mail-s-$i'),
    for (var i = 0; i < 4; i++) _edge('task-o', 'mail-o-$i'),
    for (var i = 0; i < 4; i++) _edge('task-p', 'mail-p-$i'),
  ];
  return _Fixture(
    nodes: nodes,
    edges: edges,
    positions: {
      'task-s': const Offset(0, 0),
      'task-o': const Offset(420, 0),
      'task-p': const Offset(840, 40),
      for (var i = 0; i < 10; i++) 'mail-s-$i': Offset(40.0, 220.0 + i * 16),
      for (var i = 0; i < 4; i++) 'mail-o-$i': Offset(460.0, 240.0 + i * 20),
      for (var i = 0; i < 4; i++) 'mail-p-$i': Offset(880.0, 240.0 + i * 20),
    },
  );
}

_Fixture _close() {
  final nodes = <SecretaryObject>[
    _object('task-a', 'А'),
    _object('task-b', 'Б'),
    for (var i = 0; i < 8; i++) _object('mail-a-$i', 'A $i', kind: 'email'),
    for (var i = 0; i < 8; i++) _object('mail-b-$i', 'B $i', kind: 'web_page'),
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

_Fixture _mixed() {
  final nodes = <SecretaryObject>[
    _object('task-s', 'Выбранная'),
    _object('task-n', 'Рядом'),
    for (var i = 0; i < 4; i++)
      _object('mail-s-$i', 'Полное $i', kind: 'document'),
    for (var i = 0; i < 8; i++)
      _object('mail-n-$i', 'Компакт $i', kind: 'calendar_event'),
  ];
  return _Fixture(
    nodes: nodes,
    edges: [
      for (var i = 0; i < 4; i++) _edge('task-s', 'mail-s-$i'),
      for (var i = 0; i < 8; i++) _edge('task-n', 'mail-n-$i'),
    ],
    positions: {
      'task-s': const Offset(0, 0),
      'task-n': const Offset(220, 0),
      for (var i = 0; i < 4; i++) 'mail-s-$i': Offset(20.0, 180.0 + i * 30),
      for (var i = 0; i < 8; i++) 'mail-n-$i': Offset(250.0, 180.0 + i),
    },
  );
}

_Fixture _high() {
  final nodes = <SecretaryObject>[
    _object('task-h', 'Плотная'),
    for (var i = 0; i < 36; i++) _object('mail-$i', 'Поток $i', kind: 'email'),
  ];
  return _Fixture(
    nodes: nodes,
    edges: [for (var i = 0; i < 36; i++) _edge('task-h', 'mail-$i')],
    positions: {
      'task-h': const Offset(0, 0),
      for (var i = 0; i < 36; i++) 'mail-$i': const Offset(900, 900),
    },
  );
}

_Fixture _focusChange() {
  final nodes = <SecretaryObject>[
    _object('task-a', 'A'),
    _object('task-b', 'B'),
    _object('task-c', 'C'),
    for (var i = 0; i < 4; i++) _object('mail-a-$i', 'A $i', kind: 'email'),
    for (var i = 0; i < 4; i++) _object('mail-b-$i', 'B $i', kind: 'file'),
    for (var i = 0; i < 4; i++) _object('mail-c-$i', 'C $i', kind: 'note'),
  ];
  return _Fixture(
    nodes: nodes,
    edges: [
      for (var i = 0; i < 4; i++) _edge('task-a', 'mail-a-$i'),
      for (var i = 0; i < 4; i++) _edge('task-b', 'mail-b-$i'),
      for (var i = 0; i < 4; i++) _edge('task-c', 'mail-c-$i'),
    ],
    positions: {
      'task-a': const Offset(0, 0),
      'task-b': const Offset(500, 0),
      'task-c': const Offset(1000, 0),
      for (var i = 0; i < 4; i++) 'mail-a-$i': Offset(30.0, 240.0 + i * 20),
      for (var i = 0; i < 4; i++) 'mail-b-$i': Offset(530.0, 240.0 + i * 20),
      for (var i = 0; i < 4; i++) 'mail-c-$i': Offset(1030.0, 240.0 + i * 20),
    },
  );
}

_Fixture _shared() {
  return _Fixture(
    nodes: [
      _object('task-near', 'Ближняя'),
      _object('task-far', 'Дальняя'),
      _object('mail-shared', 'Общее', kind: 'email'),
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

SecretaryObject _object(
  String id,
  String title, {
  String kind = 'task',
  String? provider,
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
    updatedAt: '2026-01-01T00:00:00Z',
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
