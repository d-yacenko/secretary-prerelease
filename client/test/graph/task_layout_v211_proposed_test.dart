import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_secretary/api/api_models.dart';
import 'package:personal_secretary/graph/graph_layout.dart';
import 'package:personal_secretary/graph/task_map_hierarchy.dart';

void main() {
  test('proposed secondary edges do not move canonical Task geography', () {
    final absent = _pair();
    for (final type in ['depends_on', 'references', 'related_to']) {
      final proposed = _pair(type: type, state: 'proposed');
      final rejected = _pair(type: type, state: 'rejected');
      expect(proposed.positions, absent.positions, reason: type);
      expect(rejected.positions, absent.positions, reason: type);
      expect(proposed.components.length, absent.components.length, reason: type);
      expect(proposed.components.length, 2, reason: type);
    }
  });

  test('a confirmed depends_on can still shorten opposite siblings', () {
    final plain = _star(const []);
    final far = _farthest(plain);
    final proposed = _star([_edge(far.$1, far.$2, 'depends_on', state: 'proposed')]);
    final confirmed = _star([_edge(far.$1, far.$2, 'depends_on')]);
    expect(proposed.positions, plain.positions);
    expect(
      _distance(confirmed, far.$1, far.$2),
      lessThan(_distance(plain, far.$1, far.$2) - 40),
    );
    expect(confirmed.taskRectOverlaps, 0);
  });

  test('only a confirmed secondary edge merges separate Task components', () {
    final absent = _pair();
    final proposed = _pair(type: 'related_to', state: 'proposed');
    final confirmed = _pair(type: 'related_to');
    expect(proposed.components, hasLength(2));
    expect(absent.components, hasLength(2));
    expect(confirmed.components, hasLength(1));
    expect(confirmed.taskRectOverlaps, 0);
  });
}

TaskMapHierarchyProjection _pair({String? type, String state = 'confirmed'}) {
  return projectTaskMapHierarchy(
    nodes: [_task('left'), _task('right')],
    edges: [
      if (type != null) _edge('left', 'right', type, state: state),
    ],
  );
}

TaskMapHierarchyProjection _star(List<SecretaryEdge> extra) {
  return projectTaskMapHierarchy(
    nodes: [_task('parent'), for (final id in _ids()) _task(id)],
    edges: [
      for (final id in _ids()) _edge(id, 'parent', 'part_of'),
      ...extra,
    ],
  );
}

(String, String) _farthest(TaskMapHierarchyProjection laid) {
  final ids = _ids();
  var best = (ids[0], ids[1]);
  var bestDistance = -1.0;
  for (var i = 0; i < ids.length; i++) {
    for (var j = i + 1; j < ids.length; j++) {
      final distance = _distance(laid, ids[i], ids[j]);
      if (distance > bestDistance) {
        bestDistance = distance;
        best = (ids[i], ids[j]);
      }
    }
  }
  return best;
}

double _distance(TaskMapHierarchyProjection laid, String a, String b) {
  return (_center(laid.positions[a]!) - _center(laid.positions[b]!)).distance;
}

Offset _center(Offset topLeft) {
  return topLeft + const Offset(kGraphNodeWidth / 2, kGraphNodeHeight / 2);
}

List<String> _ids() => [for (var i = 1; i <= 6; i++) 'c-$i'];

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
