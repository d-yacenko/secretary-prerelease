import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/task_map_hierarchy.dart';

void main() {
  test('two-level branches keep compact local flowers', () {
    final laid = projectTaskMapHierarchy(
      nodes: _academic(publicationLeaves: 5, teachingLeaves: 5, courseLeaves: 2),
      edges: _academicEdges(publicationLeaves: 5, teachingLeaves: 5, courseLeaves: 2),
    );
    expect(laid.taskRectOverlaps, 0);
    expect(laid.positions.values.every((offset) => offset.dx.isFinite && offset.dy.isFinite), isTrue);

    final publicationsAlone = _flower('publications', 5, 'pub');
    final teachingAlone = _flower('teaching', 5, 'teach');
    expect(
      _maxChildDistance(laid, 'publications', _ids('pub', 5)),
      closeTo(_maxChildDistance(publicationsAlone, 'publications', _ids('pub', 5)), 0.01),
    );
    expect(
      _maxChildDistance(laid, 'teaching', _ids('teach', 5)),
      closeTo(_maxChildDistance(teachingAlone, 'teaching', _ids('teach', 5)), 0.01),
    );
    expect(
      _maxChildDistance(laid, 'publications', _ids('pub', 5)),
      lessThan(_distance(laid, 'publications', 'academic')),
    );
    expect(_bounds(laid, ['publications', ..._ids('pub', 5)]).overlaps(_bounds(laid, ['teaching', ..._ids('teach', 5)])), isFalse);
    // ignore: avoid_print
    print(
      'TL2_A pub=${_maxChildDistance(laid, 'publications', _ids('pub', 5)).toStringAsFixed(1)} '
      'teach=${_maxChildDistance(laid, 'teaching', _ids('teach', 5)).toStringAsFixed(1)} '
      'pubToRoot=${_distance(laid, 'publications', 'academic').toStringAsFixed(1)} '
      'overlaps=${laid.taskRectOverlaps}',
    );
  });

  test('growing one branch does not interleave its sibling flower', () {
    final before = projectTaskMapHierarchy(
      nodes: _academic(publicationLeaves: 5, teachingLeaves: 2, courseLeaves: 1),
      edges: _academicEdges(publicationLeaves: 5, teachingLeaves: 2, courseLeaves: 1),
    );
    final after = projectTaskMapHierarchy(
      nodes: _academic(publicationLeaves: 5, teachingLeaves: 6, courseLeaves: 1),
      edges: _academicEdges(publicationLeaves: 5, teachingLeaves: 6, courseLeaves: 1),
    );
    expect(after.taskRectOverlaps, 0);
    expect(
      _maxChildDistance(after, 'publications', _ids('pub', 5)),
      closeTo(_maxChildDistance(before, 'publications', _ids('pub', 5)), 0.01),
    );
    final teachingRadius = _maxChildDistance(after, 'teaching', _ids('teach', 6));
    final alone = _flower('teaching', 6, 'teach');
    expect(teachingRadius, closeTo(_maxChildDistance(alone, 'teaching', _ids('teach', 6)), 0.01));
    for (final pub in _ids('pub', 5)) {
      for (final teach in _ids('teach', 6)) {
        expect(_distance(after, pub, 'publications'), lessThan(_distance(after, pub, teach)));
      }
    }
    expect(
      _bounds(after, ['publications', ..._ids('pub', 5)]).overlaps(_bounds(after, ['teaching', ..._ids('teach', 6)])),
      isFalse,
    );
    // ignore: avoid_print
    print(
      'TL2_B teachBefore=${_maxChildDistance(before, 'teaching', _ids('teach', 2)).toStringAsFixed(1)} '
      'teachAfter=$teachingRadius '
      'pubStable=${_maxChildDistance(after, 'publications', _ids('pub', 5)).toStringAsFixed(1)}',
    );
  });

  test('a confirmed secondary edge turns sibling modules toward each other', () {
    final plain = _pair(linked: false);
    final linked = _pair(linked: true);
    final rejected = projectTaskMapHierarchy(
      nodes: _pairNodes(),
      edges: [
        ..._pairEdges(),
        _edge('a-1', 'b-1', 'depends_on', state: 'rejected'),
      ],
    );
    expect(rejected.positions, plain.positions);
    expect(_distance(linked, 'a-1', 'b-1'), lessThan(_distance(plain, 'a-1', 'b-1') - 40));
    expect(_distance(linked, 'a-1', 'alpha'), lessThan(_distance(linked, 'a-1', 'hub')));
    expect(_distance(linked, 'b-1', 'beta'), lessThan(_distance(linked, 'b-1', 'hub')));
    expect(linked.taskRectOverlaps, 0);
    expect(linked.placements['a-1']!.parentId, 'alpha');
    expect(linked.placements['b-1']!.parentId, 'beta');
    // ignore: avoid_print
    print(
      'TL2_C plain=${_distance(plain, 'a-1', 'b-1').toStringAsFixed(1)} '
      'linked=${_distance(linked, 'a-1', 'b-1').toStringAsFixed(1)}',
    );
  });

  test('deep branching stays on local clearance instead of root depth', () {
    final nodes = [
      _task('root'),
      _task('branch'),
      _task('mid'),
      _task('inner'),
      _task('leaf-a'),
      _task('leaf-b'),
      _task('side'),
    ];
    final edges = [
      _edge('branch', 'root', 'part_of'),
      _edge('mid', 'branch', 'part_of'),
      _edge('inner', 'mid', 'part_of'),
      _edge('leaf-a', 'inner', 'part_of'),
      _edge('leaf-b', 'inner', 'part_of'),
      _edge('side', 'root', 'part_of'),
    ];
    final laid = projectTaskMapHierarchy(nodes: nodes, edges: edges);
    final alone = projectTaskMapHierarchy(
      nodes: [_task('inner'), _task('leaf-a'), _task('leaf-b')],
      edges: [
        _edge('leaf-a', 'inner', 'part_of'),
        _edge('leaf-b', 'inner', 'part_of'),
      ],
    );
    expect(laid.taskRectOverlaps, 0);
    expect(laid.maxDepth, 4);
    expect(
      _maxChildDistance(laid, 'inner', const ['leaf-a', 'leaf-b']),
      closeTo(_maxChildDistance(alone, 'inner', const ['leaf-a', 'leaf-b']), 0.01),
    );
    expect(
      _distance(laid, 'leaf-a', 'root'),
      greaterThan(_distance(laid, 'leaf-a', 'inner') * 2),
    );
    expect(laid.positions.values.every((offset) => offset.dx.isFinite && offset.dy.isFinite), isTrue);
    // ignore: avoid_print
    print(
      'TL2_D local=${_distance(laid, 'leaf-a', 'inner').toStringAsFixed(1)} '
      'toRoot=${_distance(laid, 'leaf-a', 'root').toStringAsFixed(1)} '
      'depth=${laid.maxDepth}',
    );
  });
}

TaskMapHierarchyProjection _flower(String parent, int count, String prefix) {
  return projectTaskMapHierarchy(
    nodes: [_task(parent), for (var i = 1; i <= count; i++) _task('$prefix-$i')],
    edges: [for (var i = 1; i <= count; i++) _edge('$prefix-$i', parent, 'part_of')],
  );
}

List<SecretaryObject> _academic({
  required int publicationLeaves,
  required int teachingLeaves,
  required int courseLeaves,
}) {
  return [
    _task('academic'),
    _task('publications'),
    _task('teaching'),
    _task('courses'),
    for (final id in _ids('pub', publicationLeaves)) _task(id),
    for (final id in _ids('teach', teachingLeaves)) _task(id),
    for (final id in _ids('course', courseLeaves)) _task(id),
  ];
}

List<SecretaryEdge> _academicEdges({
  required int publicationLeaves,
  required int teachingLeaves,
  required int courseLeaves,
}) {
  return [
    _edge('publications', 'academic', 'part_of'),
    _edge('teaching', 'academic', 'part_of'),
    _edge('courses', 'academic', 'part_of'),
    for (final id in _ids('pub', publicationLeaves)) _edge(id, 'publications', 'part_of'),
    for (final id in _ids('teach', teachingLeaves)) _edge(id, 'teaching', 'part_of'),
    for (final id in _ids('course', courseLeaves)) _edge(id, 'courses', 'part_of'),
  ];
}

List<String> _ids(String prefix, int count) {
  return [for (var i = 1; i <= count; i++) '$prefix-$i'];
}

List<SecretaryObject> _pairNodes() {
  return [
    _task('hub'),
    _task('alpha'),
    _task('beta'),
    for (final id in _ids('a', 4)) _task(id),
    for (final id in _ids('b', 4)) _task(id),
  ];
}

List<SecretaryEdge> _pairEdges() {
  return [
    _edge('alpha', 'hub', 'part_of'),
    _edge('beta', 'hub', 'part_of'),
    for (final id in _ids('a', 4)) _edge(id, 'alpha', 'part_of'),
    for (final id in _ids('b', 4)) _edge(id, 'beta', 'part_of'),
  ];
}

TaskMapHierarchyProjection _pair({required bool linked}) {
  return projectTaskMapHierarchy(
    nodes: _pairNodes(),
    edges: [
      ..._pairEdges(),
      if (linked) _edge('a-1', 'b-1', 'depends_on'),
    ],
  );
}

double _maxChildDistance(TaskMapHierarchyProjection laid, String parent, List<String> children) {
  var maxDistance = 0.0;
  for (final child in children) {
    maxDistance = math.max(maxDistance, _distance(laid, parent, child));
  }
  return maxDistance;
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
