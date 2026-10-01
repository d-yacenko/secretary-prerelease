import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/task_map_hierarchy.dart';

void main() {
  test('six mixed secondary leaves form a full halo around a structural anchor', () {
    final plain = _anchored(const []);
    final laid = _anchored(_mixedSpokes());
    final leaves = _ids('leaf', 6);
    final gaps = _gaps(laid, 'anchor', leaves);
    final radii = [for (final id in leaves) _distance(laid, 'anchor', id)];
    expect(laid.taskRectOverlaps, 0);
    expect(gaps.reduce(math.max), lessThan(1.3));
    expect(gaps.reduce(math.min), greaterThan(0.8));
    expect(radii.reduce(math.max) - radii.reduce(math.min), lessThan(0.01));
    expect(_sides(laid, 'anchor', leaves).$1, greaterThan(0));
    expect(_sides(laid, 'anchor', leaves).$2, greaterThan(0));
    expect(_delta(laid, 'root', 'anchor'), _closeDelta(_delta(plain, 'root', 'anchor')));
    for (final id in leaves) {
      expect(laid.placements[id], isNull);
    }
    expect(laid.placements['anchor']!.parentId, 'root');
    final related = _anchored([
      for (final id in leaves) _edge('anchor', id, 'related_to'),
    ]);
    expect(_gaps(related, 'anchor', leaves).reduce(math.max), lessThan(1.3));
    // ignore: avoid_print
    print(
      'TL22_A maxGap=${gaps.reduce(math.max).toStringAsFixed(2)} '
      'minGap=${gaps.reduce(math.min).toStringAsFixed(2)} '
      'radius=${radii.first.toStringAsFixed(1)} '
      'left=${_sides(laid, 'anchor', leaves).$1} '
      'right=${_sides(laid, 'anchor', leaves).$2}',
    );
  });

  test('a halo uses both sides when the anchor is at the structural edge', () {
    final laid = _anchored(_mixedSpokes());
    final leaves = _ids('leaf', 6);
    final sides = _sides(laid, 'anchor', leaves);
    expect(sides.$1, greaterThan(0));
    expect(sides.$2, greaterThan(0));
    expect(laid.taskRectOverlaps, 0);
    final anchor = _center(laid.positions['anchor']!);
    final root = _center(laid.positions['root']!);
    expect((anchor - root).distance, greaterThan(100));
  });

  test('an occupied structural side does not dump the halo opposite', () {
    final laid = _anchored(_mixedSpokes());
    final leaves = _ids('leaf', 6);
    final sides = _sides(laid, 'anchor', leaves);
    expect(sides.$1, greaterThanOrEqualTo(2));
    expect(sides.$2, greaterThanOrEqualTo(2));
    expect(_gaps(laid, 'anchor', leaves).reduce(math.max), lessThan(1.3));
    expect(laid.taskRectOverlaps, 0);
  });

  test('proposed rejected and hidden edges do not join the halo', () {
    const states = ['proposed', 'rejected'];
    const types = ['related_to', 'depends_on', 'references'];
    for (final type in types) {
      for (final state in states) {
        final laid = _withOutsider(type, state);
        expect(_componentOf(laid, 'out'), isNot(contains('anchor')));
      }
    }
    for (final type in ['requested_by', 'temporal_evidence']) {
      final laid = _withOutsider(type, 'confirmed');
      expect(_componentOf(laid, 'out'), isNot(contains('anchor')));
    }
  });

  test('a multi-anchor free task stays off the halo', () {
    final laid = projectTaskMapHierarchy(
      nodes: [
        _task('root'),
        _task('child'),
        _task('shared'),
        for (final id in _ids('leaf', 3)) _task(id),
      ],
      edges: [
        _edge('child', 'root', 'part_of'),
        _edge('shared', 'root', 'related_to'),
        _edge('shared', 'child', 'depends_on'),
        for (final id in _ids('leaf', 3)) _edge('child', id, 'references'),
      ],
    );
    final leaves = _ids('leaf', 3);
    final radii = [for (final id in leaves) _distance(laid, 'child', id)];
    expect(radii.reduce(math.max) - radii.reduce(math.min), lessThan(0.01));
    expect(_gaps(laid, 'child', leaves).reduce(math.max), lessThan(2.4));
    expect(laid.placements['shared'], isNull);
    expect(
      (_distance(laid, 'child', 'shared') - radii.first).abs(),
      greaterThan(20),
    );
    expect(laid.taskRectOverlaps, 0);
  });

  test('a leaf link shortens inside the halo without stretching spokes', () {
    final leaves = _ids('leaf', 6);
    final plain = _anchored([
      for (final id in leaves) _edge('anchor', id, 'related_to'),
    ]);
    final far = _farthest(plain, leaves);
    final linked = _anchored([
      for (final id in leaves) _edge('anchor', id, _spokeType(id)),
      _edge(far.$1, far.$2, 'depends_on'),
    ]);
    final plainRadii = [for (final id in leaves) _distance(plain, 'anchor', id)];
    final linkedRadii = [for (final id in leaves) _distance(linked, 'anchor', id)];
    expect(
      _distance(linked, far.$1, far.$2),
      lessThan(_distance(plain, far.$1, far.$2) - 40),
    );
    expect(linkedRadii.reduce(math.max) - linkedRadii.reduce(math.min), lessThan(0.01));
    expect(linkedRadii.first, closeTo(plainRadii.first, 1));
    expect(_gaps(linked, 'anchor', leaves).reduce(math.max), lessThan(1.3));
    expect(linked.taskRectOverlaps, 0);
    // ignore: avoid_print
    print(
      'TL22_F plain=${_distance(plain, far.$1, far.$2).toStringAsFixed(1)} '
      'linked=${_distance(linked, far.$1, far.$2).toStringAsFixed(1)} '
      'radius=${linkedRadii.first.toStringAsFixed(1)}',
    );
  });
}

TaskMapHierarchyProjection _anchored(List<SecretaryEdge> secondary) {
  return projectTaskMapHierarchy(
    nodes: [
      _task('root'),
      _task('anchor'),
      for (final id in _ids('leaf', 6)) _task(id),
    ],
    edges: [
      _edge('anchor', 'root', 'part_of'),
      ...secondary,
    ],
  );
}

List<SecretaryEdge> _mixedSpokes() {
  return [
    for (final id in _ids('leaf', 6)) _edge('anchor', id, _spokeType(id)),
  ];
}

String _spokeType(String id) {
  const types = ['related_to', 'depends_on', 'references'];
  return types[int.parse(id.split('-').last) % types.length];
}

TaskMapHierarchyProjection _withOutsider(String type, String state) {
  return projectTaskMapHierarchy(
    nodes: [
      _task('root'),
      _task('anchor'),
      _task('out'),
      for (final id in _ids('leaf', 3)) _task(id),
    ],
    edges: [
      _edge('anchor', 'root', 'part_of'),
      for (final id in _ids('leaf', 3)) _edge('anchor', id, 'related_to'),
      _edge('anchor', 'out', type, state: state),
    ],
  );
}

List<String> _componentOf(TaskMapHierarchyProjection laid, String id) {
  return laid.components.singleWhere((component) => component.taskIds.contains(id)).taskIds;
}

(int, int) _sides(TaskMapHierarchyProjection laid, String anchorId, List<String> leaves) {
  final anchor = _center(laid.positions[anchorId]!).dx;
  var left = 0;
  var right = 0;
  for (final id in leaves) {
    final dx = _center(laid.positions[id]!).dx - anchor;
    if (dx < -20) {
      left += 1;
    } else if (dx > 20) {
      right += 1;
    }
  }
  return (left, right);
}

List<double> _gaps(TaskMapHierarchyProjection laid, String anchorId, List<String> leaves) {
  final anchor = _center(laid.positions[anchorId]!);
  final angles = [
    for (final id in leaves)
      math.atan2(
        _center(laid.positions[id]!).dy - anchor.dy,
        _center(laid.positions[id]!).dx - anchor.dx,
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

(String, String) _farthest(TaskMapHierarchyProjection laid, List<String> ids) {
  var best = (ids[0], ids[1]);
  var bestDistance = -1.0;
  for (var left = 0; left < ids.length; left++) {
    for (var right = left + 1; right < ids.length; right++) {
      final distance = _distance(laid, ids[left], ids[right]);
      if (distance > bestDistance) {
        bestDistance = distance;
        best = (ids[left], ids[right]);
      }
    }
  }
  return best;
}

double _distance(TaskMapHierarchyProjection laid, String a, String b) {
  return (_center(laid.positions[a]!) - _center(laid.positions[b]!)).distance;
}

Offset _delta(TaskMapHierarchyProjection laid, String a, String b) {
  return _center(laid.positions[a]!) - _center(laid.positions[b]!);
}

Matcher _closeDelta(Offset expected) {
  return predicate<Offset>(
    (actual) => (actual - expected).distance < 0.01,
    'delta within 0.01 of $expected',
  );
}

Offset _center(Offset topLeft) {
  return topLeft + const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
}

List<String> _ids(String prefix, int count) {
  return [for (var index = 1; index <= count; index++) '$prefix-$index'];
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
