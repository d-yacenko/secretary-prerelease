import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/fcose_graph_refiner.dart';
import 'package:personal_secretary/graph/graph_geometry.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/graph_map_edge_presentation.dart';
import 'package:personal_secretary/graph/hybrid_focus_lod.dart';
import 'package:personal_secretary/graph/task_map_hierarchy.dart';

void main() {
  test('distant Flow does not move Tasks or inflate task geography', () {
    final near = _project(
      tasks: [_task('a'), _task('b')],
      flow: [_flow('mail', const Offset(8000, -4000))],
      edges: [_edge('a', 'mail', 'references'), _edge('b', 'mail', 'references')],
    );
    final moved = _project(
      tasks: [_task('a'), _task('b')],
      flow: [_flow('mail', const Offset(-9000, 12000))],
      edges: [_edge('a', 'mail', 'references'), _edge('b', 'mail', 'references')],
    );
    final tasksOnly = projectTaskMapHierarchy(
      nodes: [_task('a'), _task('b')],
      edges: const [],
    );
    expect(near.positions, moved.positions);
    expect(near.positions, tasksOnly.positions);
    expect(near.hierarchyTreeCount, 0);
    expect(near.freeComponentCount, 2);
    final canonical = GraphLayout.computeBounds({
      'a': Offset.zero,
      'b': const Offset(186, 0),
      'mail': const Offset(8000, -4000),
    });
    expect(near.taskBounds.width, lessThan(1200));
    expect(canonical.width, greaterThan(7000));
    final hybrid = _hybrid(near, selected: null, flowAt: const Offset(8000, -4000));
    final shown = hybridPresentationBounds(hybrid);
    expect(shown.width, lessThan(canonical.width / 4));
    expect(shown.height, lessThan(canonical.height / 4));
    _printMetrics('A', near, canonical, shown);
  });

  test('a non-hierarchy link uses Tasks only', () {
    final linked = projectTaskMapHierarchy(
      nodes: [_task('a'), _task('b'), _flow('mail', const Offset(9000, 0))],
      edges: [
        _edge('a', 'b', 'related_to'),
        _edge('a', 'mail', 'references'),
      ],
    );
    expect(linked.freeComponentCount, 1);
    expect(linked.hierarchyTreeCount, 0);
    expect(linked.taskCount, 2);
    expect(linked.components.single.taskIds, ['a', 'b']);
    final separate = projectTaskMapHierarchy(
      nodes: [_task('a'), _task('b'), _flow('mail', const Offset(9000, 0))],
      edges: [_edge('a', 'mail', 'references'), _edge('b', 'mail', 'references')],
    );
    expect(separate.freeComponentCount, 2);
    final linkedDistance =
        (_center(linked.positions['a']!) - _center(linked.positions['b']!)).distance;
    final separateDistance =
        (_center(separate.positions['a']!) - _center(separate.positions['b']!)).distance;
    expect(linkedDistance, lessThan(separateDistance));
  });

  test('independent clusters pack across columns', () {
    final tasks = [for (var i = 0; i < 5; i++) _task('t$i')];
    final first = projectTaskMapHierarchy(nodes: tasks, edges: const []);
    final second = projectTaskMapHierarchy(nodes: tasks.reversed.toList(), edges: const []);
    expect(first.positions, second.positions);
    expect(first.freeComponentCount, 5);
    expect(first.hierarchyTreeCount, 0);
    expect(first.maxColumns, greaterThanOrEqualTo(2));
    expect(first.occupiedRows, greaterThanOrEqualTo(1));
    expect(first.maxColumns == 1 && first.occupiedRows == 5, isFalse);
    expect(first.envelopeOverlaps, 0);
    expect(first.taskRectOverlaps, 0);
    _printMetrics('B', first, first.taskBounds, first.taskBounds);
  });

  test('confirmed part_of places children around an inward parent', () {
    final tasks = [
      _task('parent'),
      _task('c1'),
      _task('c2'),
      _task('c3'),
      _task('c4'),
    ];
    final edges = [
      for (final id in ['c1', 'c2', 'c3', 'c4'])
        _edge(id, 'parent', 'part_of', state: 'confirmed'),
    ];
    final laid = projectTaskMapHierarchy(nodes: tasks, edges: edges);
    expect(laid.hierarchyTreeCount, 1);
    expect(laid.freeComponentCount, 0);
    expect(laid.maxDepth, 1);
    expect(laid.taskRectOverlaps, 0);
    final root = laid.placements['parent']!;
    expect(root.radius, 0);
    final parent = _center(laid.positions['parent']!);
    final angles = <double>[];
    for (final id in ['c1', 'c2', 'c3', 'c4']) {
      final child = _center(laid.positions[id]!);
      final inward = parent - child;
      final towardRoot = parent - child;
      expect(inward.dx * towardRoot.dx + inward.dy * towardRoot.dy, greaterThan(0));
      angles.add(math.atan2(child.dy - parent.dy, child.dx - parent.dx));
      expect(
        presentGraphMapEdge(edge: edges.firstWhere((edge) => edge.sourceId == id)).directed,
        isTrue,
      );
    }
    angles.sort();
    expect(angles.last - angles.first, greaterThan(math.pi));
    _printMetrics('C', laid, laid.taskBounds, laid.taskBounds);
  });

  test('grandchildren stay farther out inside the parent sector', () {
    final tasks = [
      _task('root'),
      _task('wide'),
      _task('leaf-a'),
      _task('leaf-b'),
      _task('g1'),
      _task('g2'),
      _task('g3'),
    ];
    final edges = [
      _edge('wide', 'root', 'part_of'),
      _edge('leaf-a', 'root', 'part_of'),
      _edge('leaf-b', 'root', 'part_of'),
      _edge('g1', 'wide', 'part_of'),
      _edge('g2', 'wide', 'part_of'),
      _edge('g3', 'wide', 'part_of'),
    ];
    final laid = projectTaskMapHierarchy(nodes: tasks, edges: edges);
    final wide = laid.placements['wide']!;
    expect(laid.maxDepth, 2);
    expect(wide.sectorEnd - wide.sectorStart, greaterThan(laid.placements['leaf-a']!.sectorEnd - laid.placements['leaf-a']!.sectorStart));
    for (final id in ['g1', 'g2', 'g3']) {
      final grand = laid.placements[id]!;
      expect(grand.radius, greaterThan(wide.radius));
      expect(grand.sectorStart, greaterThanOrEqualTo(wide.sectorStart - 1e-9));
      expect(grand.sectorEnd, lessThanOrEqualTo(wide.sectorEnd + 1e-9));
    }
    expect(laid.taskRectOverlaps, 0);
    _printMetrics('D', laid, laid.taskBounds, laid.taskBounds);
  });

  test('ongoing root clearance uses the 144 circle', () {
    final laid = projectTaskMapHierarchy(
      nodes: [
        _task('root', ongoing: true),
        _task('child'),
      ],
      edges: [_edge('child', 'root', 'part_of')],
    );
    final rootRect = hybridOngoingRect(laid.positions['root']!);
    expect(rootRect.width, 144);
    expect(rootRect.height, 144);
    expect(rootRect.center, _center(laid.positions['root']!));
    final distance = (rootRect.center - _center(laid.positions['child']!)).distance;
    expect(distance, closeTo(72 + kTaskMapHierarchyGap + taskCircumradius(_task('child')), 0.01));
    expect(laid.taskRectOverlaps, 0);
    _printMetrics('E', laid, laid.taskBounds, laid.taskBounds);
  });

  test('proposed part_of does not move geography until confirmed', () {
    final tasks = [_task('child'), _task('parent')];
    final absent = projectTaskMapHierarchy(nodes: tasks, edges: const []);
    final proposed = projectTaskMapHierarchy(
      nodes: tasks,
      edges: [_edge('child', 'parent', 'part_of', state: 'proposed')],
    );
    final confirmed = projectTaskMapHierarchy(
      nodes: tasks,
      edges: [_edge('child', 'parent', 'part_of')],
    );
    expect(proposed.positions, absent.positions);
    expect(proposed.hierarchyTreeCount, 0);
    expect(confirmed.hierarchyTreeCount, 1);
    expect(confirmed.positions, isNot(absent.positions));
    final moved = (_center(confirmed.positions['child']!) - _center(absent.positions['child']!)).distance;
    expect(moved, greaterThan(1));
    expect(
      presentGraphMapEdge(
        edge: _edge('child', 'parent', 'part_of', state: 'proposed'),
      ).proposed,
      isTrue,
    );
    _printMetrics('F', confirmed, absent.taskBounds, confirmed.taskBounds);
  });

  test('cross-links do not become hierarchy parentage', () {
    final tasks = [
      _task('left'),
      _task('left-child'),
      _task('right'),
      _task('right-child'),
    ];
    final hierarchy = [
      _edge('left-child', 'left', 'part_of'),
      _edge('right-child', 'right', 'part_of'),
    ];
    final plain = projectTaskMapHierarchy(nodes: tasks, edges: hierarchy);
    final linked = projectTaskMapHierarchy(
      nodes: tasks,
      edges: [...hierarchy, _edge('left', 'right', 'depends_on')],
    );
    expect(plain.components, hasLength(2));
    expect(linked.components, hasLength(1));
    expect(linked.components.single.structuralTreeCount, 2);
    expect(linked.placements['left-child']!.parentId, 'left');
    expect(linked.placements['right-child']!.parentId, 'right');
    expect(linked.placements['left']!.parentId, isNull);
    expect(linked.placements['right']!.parentId, isNull);
    expect(linked.placements['left']!.rootId, plain.placements['left']!.rootId);
    expect(linked.placements['right-child']!.depth, plain.placements['right-child']!.depth);
    expect(linked.hierarchyTreeCount, 2);
    expect(linked.taskRectOverlaps, 0);
    final presentation = presentGraphMapEdge(edge: _edge('left', 'right', 'depends_on'));
    expect(presentation.visibleOnTasksMap, isTrue);
    expect(presentation.dashed, isTrue);
    expect(presentation.directed, isTrue);
    _printMetrics('G', linked, linked.taskBounds, linked.taskBounds);
  });

  test('focus, preserve, and relax keep the same Task centers', () {
    final tasks = [_task('parent'), _task('child'), _task('other')];
    final edges = [
      _edge('child', 'parent', 'part_of'),
      _edge('parent', 'mail', 'references'),
    ];
    final nodes = [...tasks, _flow('mail', const Offset(5000, 5000))];
    final laid = projectTaskMapHierarchy(nodes: nodes, edges: edges);
    final positions = {
      'mail': const Offset(5000, 5000),
      ...laid.positions,
    };
    final focusA = presentHybridFocus(
      nodes: nodes,
      edges: edges,
      positions: positions,
      selectedObjectId: 'parent',
      refiner: _IdentityRefiner(),
    );
    final focusB = presentHybridFocus(
      nodes: nodes,
      edges: edges,
      positions: positions,
      selectedObjectId: 'other',
      refiner: _IdentityRefiner(),
    );
    final cleared = presentHybridFocus(
      nodes: nodes,
      edges: edges,
      positions: positions,
      selectedObjectId: null,
      refiner: _IdentityRefiner(),
    );
    for (final id in ['parent', 'child', 'other']) {
      expect(focusA.displayTopLeft[id], laid.positions[id]);
      expect(focusB.displayTopLeft[id], laid.positions[id]);
      expect(cleared.displayTopLeft[id], laid.positions[id]);
    }
    expect(
      focusA.scene.nodes.any((node) => node.width == kHybridFocusedCardWidth),
      isTrue,
    );
    final ongoingNodes = [
      _task('direction', ongoing: true),
      _flow('note', const Offset(4000, 0)),
    ];
    final ongoingEdges = [_edge('direction', 'note', 'references')];
    final ongoingLaid = projectTaskMapHierarchy(nodes: ongoingNodes, edges: ongoingEdges);
    final ongoing = presentHybridFocus(
      nodes: ongoingNodes,
      edges: ongoingEdges,
      positions: {'note': const Offset(4000, 0), ...ongoingLaid.positions},
      selectedObjectId: 'direction',
      refiner: _IdentityRefiner(),
    );
    expect(
      ongoing.scene.nodes.any((node) => node.width == kHybridFocusedCardWidth),
      isFalse,
    );
    expect(ongoing.displayTopLeft['direction']!.dx, isNot(closeTo(4000, 500)));

    final preserve = presentHybridFocus(
      nodes: nodes,
      edges: edges,
      positions: positions,
      selectedObjectId: 'parent',
      refiner: FcoseGraphRefiner(mode: FcoseRefinementMode.preserve),
    );
    final relax = presentHybridFocus(
      nodes: nodes,
      edges: edges,
      positions: positions,
      selectedObjectId: 'parent',
      refiner: FcoseGraphRefiner(mode: FcoseRefinementMode.relax),
    );
    var preserveShift = 0.0;
    var relaxShift = 0.0;
    for (final id in laid.positions.keys) {
      preserveShift = math.max(
        preserveShift,
        (preserve.displayTopLeft[id]! - laid.positions[id]!).distance,
      );
      relaxShift = math.max(
        relaxShift,
        (relax.displayTopLeft[id]! - laid.positions[id]!).distance,
      );
    }
    expect(preserveShift, 0);
    expect(relaxShift, 0);
    final repeat = projectTaskMapHierarchy(nodes: nodes, edges: edges);
    var repeatShift = 0.0;
    for (final id in laid.positions.keys) {
      repeatShift = math.max(
        repeatShift,
        (_center(repeat.positions[id]!) - _center(laid.positions[id]!)).distance,
      );
    }
    expect(repeatShift, 0);
    // ignore: avoid_print
    print(
      'STABILITY repeat=$repeatShift focus=${(focusA.displayTopLeft['parent']! - focusB.displayTopLeft['parent']!).distance} '
      'preserve=$preserveShift relax=$relaxShift',
    );
  });

  test('confirmed part_of keeps an existing Task daisy with its Direction', () {
    final publications = _task('publications', ongoing: true);
    final petals = [
      _task('paper-a'),
      _task('paper-b'),
      _task('paper-c'),
      _task('paper-d'),
    ];
    final academy = _task('academy', ongoing: true);
    final daisyEdges = [
      for (final petal in petals) _edge(petal.id, 'publications', 'related_to'),
    ];
    final openDaisy = projectTaskMapHierarchy(
      nodes: [publications, ...petals],
      edges: daisyEdges,
    );
    final attached = projectTaskMapHierarchy(
      nodes: [academy, publications, ...petals],
      edges: [...daisyEdges, _edge('publications', 'academy', 'part_of')],
    );
    final removed = projectTaskMapHierarchy(
      nodes: [academy, publications, ...petals],
      edges: daisyEdges,
    );

    expect(attached.components, hasLength(1));
    expect(attached.components.single.taskIds, containsAll(['academy', 'publications', ...petals.map((task) => task.id)]));
    expect(attached.hierarchyTreeCount, 1);
    expect(attached.placements['publications']!.parentId, 'academy');
    expect(attached.placements['paper-a'], isNull);
    expect(attached.taskRectOverlaps, 0);
    expect(attached.envelopeOverlaps, 0);

    final openSpan = _span(openDaisy, 'publications', petals.map((task) => task.id));
    final attachedSpan = _span(attached, 'publications', petals.map((task) => task.id));
    final removedSpan = _span(removed, 'publications', petals.map((task) => task.id));
    expect(openSpan, lessThan(900));
    expect(attachedSpan, lessThan(openSpan + 280));
    expect(removedSpan, lessThan(900));
    expect(removed.components.length, greaterThan(1));
    expect(
      removed.components.any((component) => component.taskIds.contains('publications') && component.taskIds.contains('paper-a')),
      isTrue,
    );

    final ongoing = hybridOngoingRect(attached.positions['publications']!);
    expect(ongoing.width, 144);
    expect(ongoing.height, 144);
    for (final petal in petals) {
      final card = GraphLayout.nodeRectAt(attached.positions[petal.id]!);
      expect(ongoing.overlaps(card), isFalse);
    }

    final reversed = projectTaskMapHierarchy(
      nodes: [academy, publications, ...petals].reversed.toList(),
      edges: [...daisyEdges, _edge('publications', 'academy', 'part_of')].reversed.toList(),
    );
    expect(reversed.positions, attached.positions);

    final controllerPositions = {
      'academy': const Offset(0, 0),
      'publications': const Offset(2400, 0),
      for (final petal in petals) petal.id: const Offset(4800, 400),
    };
    final shown = Map<String, Offset>.from(controllerPositions)
      ..addAll(attached.positions);
    final shownSpan = _span(
      attached,
      'publications',
      petals.map((task) => task.id),
      positions: shown,
    );
    expect(shownSpan, attachedSpan);
    expect(shown['paper-a'], isNot(controllerPositions['paper-a']));
  });

  test('two disconnected part_of trees stay separate visual components', () {
    final laid = projectTaskMapHierarchy(
      nodes: [
        _task('left'),
        _task('left-child'),
        _task('right'),
        _task('right-child'),
      ],
      edges: [
        _edge('left-child', 'left', 'part_of'),
        _edge('right-child', 'right', 'part_of'),
      ],
    );
    expect(laid.components, hasLength(2));
    expect(laid.hierarchyTreeCount, 2);
    expect(laid.freeComponentCount, 0);
    expect(laid.taskRectOverlaps, 0);
  });

  test('Task to Flow evidence does not join Task packing', () {
    final withFlow = projectTaskMapHierarchy(
      nodes: [
        _task('publications', ongoing: true),
        _task('paper'),
        _flow('mail', const Offset(9000, 4000)),
      ],
      edges: [
        _edge('paper', 'publications', 'references'),
        _edge('publications', 'mail', 'references'),
      ],
    );
    final tasksOnly = projectTaskMapHierarchy(
      nodes: [
        _task('publications', ongoing: true),
        _task('paper'),
      ],
      edges: [_edge('paper', 'publications', 'references')],
    );
    expect(withFlow.positions, tasksOnly.positions);
    expect(withFlow.components.single.taskIds, ['paper', 'publications']);
    expect(withFlow.taskBounds.width, lessThan(2000));
  });
}

double _span(
  TaskMapHierarchyProjection laid,
  String anchorId,
  Iterable<String> ids, {
  Map<String, Offset>? positions,
}) {
  final source = positions ?? laid.positions;
  final anchor = _center(source[anchorId]!);
  var span = 0.0;
  for (final id in ids) {
    span = math.max(span, (_center(source[id]!) - anchor).distance);
  }
  return span;
}

void _printMetrics(
  String name,
  TaskMapHierarchyProjection laid,
  Rect oldBounds,
  Rect shown,
) {
  final oldArea = oldBounds.width * oldBounds.height;
  final nextArea = laid.taskBounds.width * laid.taskBounds.height;
  // ignore: avoid_print
  print(
    'V8B2_$name tasks=${laid.taskCount} trees=${laid.hierarchyTreeCount} '
    'free=${laid.freeComponentCount} depth=${laid.maxDepth} '
    'taskOverlaps=${laid.taskRectOverlaps} envelopeOverlaps=${laid.envelopeOverlaps} '
    'old=${oldBounds.width.toStringAsFixed(0)}x${oldBounds.height.toStringAsFixed(0)} '
    'task=${laid.taskBounds.width.toStringAsFixed(0)}x${laid.taskBounds.height.toStringAsFixed(0)} '
    'shown=${shown.width.toStringAsFixed(0)}x${shown.height.toStringAsFixed(0)} '
    'areaRatio=${oldArea == 0 ? 0 : (nextArea / oldArea).toStringAsFixed(3)} '
    'rows=${laid.occupiedRows} cols=${laid.maxColumns}',
  );
}

HybridFocusPresentation _hybrid(
  TaskMapHierarchyProjection laid, {
  required String? selected,
  required Offset flowAt,
}) {
  return presentHybridFocus(
    nodes: [_task('a'), _task('b'), _flow('mail', flowAt)],
    edges: [_edge('a', 'mail', 'references'), _edge('b', 'mail', 'references')],
    positions: {'mail': flowAt, ...laid.positions},
    selectedObjectId: selected,
    refiner: _IdentityRefiner(),
  );
}

TaskMapHierarchyProjection _project({
  required List<SecretaryObject> tasks,
  required List<SecretaryObject> flow,
  required List<SecretaryEdge> edges,
}) {
  return projectTaskMapHierarchy(nodes: [...tasks, ...flow], edges: edges);
}

Offset _center(Offset topLeft) {
  return topLeft + const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
}

SecretaryObject _task(String id, {bool ongoing = false}) {
  return SecretaryObject(
    id: id,
    kind: 'task',
    title: id,
    completionMode: ongoing ? 'ongoing' : 'finite',
    metadata: const {},
    origin: 'user',
    state: 'confirmed',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

SecretaryObject _flow(String id, Offset canonical) {
  return SecretaryObject(
    id: id,
    kind: 'email',
    title: id,
    metadata: {'canonical': '${canonical.dx},${canonical.dy}'},
    origin: 'user',
    state: 'confirmed',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

SecretaryEdge _edge(
  String sourceId,
  String targetId,
  String type, {
  String state = 'confirmed',
}) {
  return SecretaryEdge(
    id: '$sourceId-$targetId-$type-$state',
    sourceId: sourceId,
    targetId: targetId,
    type: type,
    origin: 'user',
    state: state,
    metadata: const {},
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

class _IdentityRefiner implements GraphGeometryRefiner {
  @override
  GraphGeometryResult refine(GraphGeometryScene scene) {
    return GraphGeometryResult.success(
      nodes: {for (final node in scene.nodes) node.id: node.rect},
    );
  }
}
