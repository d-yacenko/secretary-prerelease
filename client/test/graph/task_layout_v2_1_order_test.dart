import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/task_map_hierarchy.dart';

void main() {
  test('opposite leaf siblings become adjacent when a confirmed edge asks', () {
    const count = 6;
    final plain = _star(count, const []);
    final far = _farthestPair(plain, _ids('c', count));
    final linked = _star(count, [_edge(far.$1, far.$2, 'depends_on')]);
    final plainDistance = _distance(plain, far.$1, far.$2);
    final linkedDistance = _distance(linked, far.$1, far.$2);

    expect(linkedDistance, lessThan(plainDistance - 40));
    expect(_pairGap(linked, far.$1, far.$2), lessThan(math.pi / 2));
    final radii = [
      for (final id in _ids('c', count)) _distance(linked, 'parent', id),
    ];
    expect(radii.reduce(math.max) - radii.reduce(math.min), lessThan(0.01));
    expect(radii.first, closeTo(_distance(plain, 'parent', 'c-1'), 0.01));
    expect(linked.taskRectOverlaps, 0);
    for (final id in _ids('c', count)) {
      expect(linked.placements[id]!.parentId, 'parent');
    }
    final again = _star(count, [_edge(far.$1, far.$2, 'depends_on')]);
    expect(again.positions, linked.positions);
    // ignore: avoid_print
    print(
      'TL21_A plain=${plainDistance.toStringAsFixed(1)} '
      'linked=${linkedDistance.toStringAsFixed(1)} '
      'gap=${_pairGap(linked, far.$1, far.$2).toStringAsFixed(2)}',
    );
  });

  test('two confirmed sibling links shorten the total without churn', () {
    const count = 6;
    final plain = _star(count, const []);
    final pairs = _disjointFarPairs(plain, _ids('c', count), 2);
    final edges = [
      for (final pair in pairs) _edge(pair.$1, pair.$2, 'related_to'),
    ];
    final linked = _star(count, edges);
    final plainTotal = pairs.fold<double>(
      0,
      (sum, pair) => sum + _distance(plain, pair.$1, pair.$2),
    );
    final linkedTotal = pairs.fold<double>(
      0,
      (sum, pair) => sum + _distance(linked, pair.$1, pair.$2),
    );
    expect(linkedTotal, lessThan(plainTotal - 40));
    expect(linked.taskRectOverlaps, 0);
    expect(_star(count, edges).positions, linked.positions);
    // ignore: avoid_print
    print(
      'TL21_B plain=${plainTotal.toStringAsFixed(1)} linked=${linkedTotal.toStringAsFixed(1)}',
    );
  });

  test('reordering leaves keeps a nested subtree intact', () {
    final plain = _mixed(linked: false);
    final linked = _mixed(linked: true);
    final alone = projectTaskMapHierarchy(
      nodes: [_task('nest'), _task('g-1'), _task('g-2'), _task('g-3')],
      edges: [
        _edge('g-1', 'nest', 'part_of'),
        _edge('g-2', 'nest', 'part_of'),
        _edge('g-3', 'nest', 'part_of'),
      ],
    );
    expect(linked.taskRectOverlaps, 0);
    expect(linked.placements['g-1']!.parentId, 'nest');
    expect(
      _distance(linked, 'nest', 'g-1'),
      closeTo(_distance(alone, 'nest', 'g-1'), 0.01),
    );
    expect(
      _distance(linked, 'nest', 'g-2'),
      closeTo(_distance(plain, 'nest', 'g-2'), 0.01),
    );
    expect(_bounds(linked, ['nest', 'g-1', 'g-2', 'g-3']).overlaps(_bounds(linked, ['c-1'])), isFalse);
  });

  test('five leaves without links stay spread around the parent', () {
    final laid = _star(5, const []);
    final gaps = _circularGaps(laid, _ids('c', 5));
    expect(gaps.reduce(math.max), lessThan(math.pi));
    expect(gaps.reduce(math.min), greaterThan(0.4));
    expect(laid.taskRectOverlaps, 0);
    final radii = [for (final id in _ids('c', 5)) _distance(laid, 'parent', id)];
    expect(radii.reduce(math.max) - radii.reduce(math.min), lessThan(0.01));
    // ignore: avoid_print
    print(
      'TL21_D maxGap=${gaps.reduce(math.max).toStringAsFixed(2)} '
      'radius=${radii.first.toStringAsFixed(1)}',
    );
  });
}

TaskMapHierarchyProjection _star(int count, List<SecretaryEdge> extra) {
  return projectTaskMapHierarchy(
    nodes: [_task('parent'), for (final id in _ids('c', count)) _task(id)],
    edges: [
      for (final id in _ids('c', count)) _edge(id, 'parent', 'part_of'),
      ...extra,
    ],
  );
}

TaskMapHierarchyProjection _mixed({required bool linked}) {
  final plainLeaves = _star(4, const []);
  final far = _farthestPair(plainLeaves, _ids('c', 4));
  return projectTaskMapHierarchy(
    nodes: [
      _task('parent'),
      _task('nest'),
      _task('g-1'),
      _task('g-2'),
      _task('g-3'),
      for (final id in _ids('c', 4)) _task(id),
    ],
    edges: [
      _edge('nest', 'parent', 'part_of'),
      _edge('g-1', 'nest', 'part_of'),
      _edge('g-2', 'nest', 'part_of'),
      _edge('g-3', 'nest', 'part_of'),
      for (final id in _ids('c', 4)) _edge(id, 'parent', 'part_of'),
      if (linked) _edge(far.$1, far.$2, 'depends_on'),
    ],
  );
}

(String, String) _farthestPair(TaskMapHierarchyProjection laid, List<String> ids) {
  return _disjointFarPairs(laid, ids, 1).single;
}

List<(String, String)> _disjointFarPairs(
  TaskMapHierarchyProjection laid,
  List<String> ids,
  int wanted,
) {
  final ranked = <(String, String, double)>[];
  for (var i = 0; i < ids.length; i++) {
    for (var j = i + 1; j < ids.length; j++) {
      ranked.add((ids[i], ids[j], _distance(laid, ids[i], ids[j])));
    }
  }
  ranked.sort((a, b) => b.$3.compareTo(a.$3));
  final chosen = <(String, String)>[];
  final used = <String>{};
  for (final pair in ranked) {
    if (used.contains(pair.$1) || used.contains(pair.$2)) {
      continue;
    }
    chosen.add((pair.$1, pair.$2));
    used.add(pair.$1);
    used.add(pair.$2);
    if (chosen.length == wanted) {
      break;
    }
  }
  return chosen;
}

double _pairGap(TaskMapHierarchyProjection laid, String a, String b) {
  final parent = _center(laid.positions['parent']!);
  final left = _center(laid.positions[a]!) - parent;
  final right = _center(laid.positions[b]!) - parent;
  return _gap(math.atan2(left.dy, left.dx), math.atan2(right.dy, right.dx));
}

List<double> _circularGaps(TaskMapHierarchyProjection laid, List<String> ids) {
  final parent = _center(laid.positions['parent']!);
  final angles = [
    for (final id in ids)
      math.atan2(
        (_center(laid.positions[id]!) - parent).dy,
        (_center(laid.positions[id]!) - parent).dx,
      ),
  ]..sort();
  final gaps = <double>[];
  for (var index = 0; index < angles.length; index++) {
    final next = angles[(index + 1) % angles.length];
    final current = angles[index];
    gaps.add(index == angles.length - 1 ? (next + math.pi * 2) - current : next - current);
  }
  return gaps;
}

double _gap(double a, double b) {
  var delta = (a - b).abs();
  if (delta > math.pi) {
    delta = math.pi * 2 - delta;
  }
  return delta;
}

double _distance(TaskMapHierarchyProjection laid, String a, String b) {
  return (_center(laid.positions[a]!) - _center(laid.positions[b]!)).distance;
}

Rect _bounds(TaskMapHierarchyProjection laid, List<String> ids) {
  Rect? bounds;
  for (final id in ids) {
    final rect = GraphLayout.nodeRectAt(laid.positions[id]!);
    bounds = bounds == null ? rect : bounds.expandToInclude(rect);
  }
  return bounds!;
}

Offset _center(Offset topLeft) {
  return topLeft + const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
}

List<String> _ids(String prefix, int count) {
  return [for (var i = 1; i <= count; i++) '$prefix-$i'];
}

SecretaryObject _task(String id) {
  return SecretaryObject(
    id: id,
    kind: 'task',
    title: id,
    completionMode: 'finite',
    metadata: const {},
    origin: 'user',
    state: 'confirmed',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

SecretaryEdge _edge(String sourceId, String targetId, String type, {String state = 'confirmed'}) {
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
