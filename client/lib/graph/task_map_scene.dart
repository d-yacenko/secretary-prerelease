import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api/api_models.dart';

/// Fixed card slot for the V2 geometry spike. Zoom changes text, not this size.
const Size kTaskMapSceneNodeSize = Size(168, 104);

/// Overview without a selected Task stays task-only and bounded.
const int kTaskMapOverviewTaskCap = 24;

/// Engine-neutral scene. [groupIds] stays empty in V2 so a later
/// presentation-only grouping can be added without ELK types or new ontology.
class TaskMapScene {
  const TaskMapScene({
    required this.nodes,
    required this.edges,
    this.groupIds = const [],
  });

  final List<TaskMapSceneNode> nodes;
  final List<TaskMapSceneEdge> edges;
  final List<String> groupIds;
}

class TaskMapSceneNode {
  const TaskMapSceneNode({
    required this.id,
    required this.width,
    required this.height,
    this.prior,
    this.groupId,
  });

  final String id;
  final double width;
  final double height;

  /// Optional previous top-left. Engines may ignore it. V2 does not persist it.
  final Offset? prior;

  /// Reserved for a future presentation group. V2 leaves this null.
  final String? groupId;
}

class TaskMapSceneEdge {
  const TaskMapSceneEdge({
    required this.id,
    required this.sourceId,
    required this.targetId,
  });

  final String id;
  final String sourceId;
  final String targetId;
}

class TaskMapRoutedEdge {
  const TaskMapRoutedEdge({
    required this.id,
    required this.sourceId,
    required this.targetId,
    required this.sections,
  });

  final String id;
  final String sourceId;
  final String targetId;

  /// Polylines from the layout engine. One section is the usual simple edge.
  final List<List<Offset>> sections;

  bool get hasRoute => sections.any((section) => section.length >= 2);

  bool get hasBend => sections.any((section) => section.length >= 3);
}

/// Normalized geometry. Callers outside an engine adapter do not see engine types.
class TaskMapSceneLayout {
  const TaskMapSceneLayout._({
    required this.completed,
    required this.nodes,
    required this.edges,
    this.error,
  });

  const TaskMapSceneLayout.success({
    required Map<String, Rect> nodes,
    required List<TaskMapRoutedEdge> edges,
  }) : this._(completed: true, nodes: nodes, edges: edges);

  const TaskMapSceneLayout.failure(String error)
      : this._(completed: false, nodes: const {}, edges: const [], error: error);

  final bool completed;
  final String? error;
  final Map<String, Rect> nodes;
  final List<TaskMapRoutedEdge> edges;
}

abstract class TaskMapLayoutEngine {
  TaskMapSceneLayout layout(TaskMapScene scene);
}

class TaskMapFixture {
  const TaskMapFixture({
    required this.nodes,
    required this.edges,
    required this.rootId,
  });

  final List<SecretaryObject> nodes;
  final List<SecretaryEdge> edges;
  final String rootId;
}

/// Selected Task flower: the Task, its already-loaded direct neighbors, and
/// existing edges whose endpoints remain in that set. No selected Task yields
/// a bounded Task-only overview.
TaskMapScene buildTaskMapScene({
  required List<SecretaryObject> nodes,
  required List<SecretaryEdge> edges,
  required String? selectedObjectId,
  Map<String, Offset>? priors,
}) {
  final byId = {for (final node in nodes) node.id: node};
  final selected = selectedObjectId == null ? null : byId[selectedObjectId];
  final visible = <String>{};
  if (selected != null && selected.kind == 'task') {
    visible.add(selected.id);
    for (final edge in edges) {
      final String? other;
      if (edge.sourceId == selected.id) {
        other = edge.targetId;
      } else if (edge.targetId == selected.id) {
        other = edge.sourceId;
      } else {
        other = null;
      }
      if (other != null && byId.containsKey(other)) {
        visible.add(other);
      }
    }
  } else {
    var count = 0;
    for (final node in nodes) {
      if (node.kind != 'task') {
        continue;
      }
      visible.add(node.id);
      count += 1;
      if (count >= kTaskMapOverviewTaskCap) {
        break;
      }
    }
  }
  return TaskMapScene(
    nodes: [
      for (final node in nodes)
        if (visible.contains(node.id))
          TaskMapSceneNode(
            id: node.id,
            width: kTaskMapSceneNodeSize.width,
            height: kTaskMapSceneNodeSize.height,
            prior: priors?[node.id],
            groupId: null,
          ),
    ],
    edges: [
      for (final edge in edges)
        if (visible.contains(edge.sourceId) && visible.contains(edge.targetId))
          TaskMapSceneEdge(
            id: edge.id,
            sourceId: edge.sourceId,
            targetId: edge.targetId,
          ),
    ],
  );
}

/// Full fixture scene for the cluster probe. Product rendering still uses
/// [buildTaskMapScene], which keeps the local flower.
TaskMapScene taskMapFullScene(TaskMapFixture fixture) {
  final ids = {for (final node in fixture.nodes) node.id};
  return TaskMapScene(
    nodes: [
      for (final node in fixture.nodes)
        TaskMapSceneNode(
          id: node.id,
          width: kTaskMapSceneNodeSize.width,
          height: kTaskMapSceneNodeSize.height,
        ),
    ],
    edges: [
      for (final edge in fixture.edges)
        if (ids.contains(edge.sourceId) && ids.contains(edge.targetId))
          TaskMapSceneEdge(
            id: edge.id,
            sourceId: edge.sourceId,
            targetId: edge.targetId,
          ),
    ],
  );
}

TaskMapScene sceneWithPriors(TaskMapScene scene, TaskMapSceneLayout layout) {
  return TaskMapScene(
    nodes: [
      for (final node in scene.nodes)
        TaskMapSceneNode(
          id: node.id,
          width: node.width,
          height: node.height,
          groupId: node.groupId,
          prior: layout.nodes[node.id]?.topLeft,
        ),
    ],
    edges: scene.edges,
    groupIds: scene.groupIds,
  );
}

int taskMapOverlapCount(Map<String, Rect> nodes) {
  final rects = nodes.values.toList();
  var count = 0;
  for (var i = 0; i < rects.length; i++) {
    for (var j = i + 1; j < rects.length; j++) {
      if (_areaOverlap(rects[i], rects[j])) {
        count += 1;
      }
    }
  }
  return count;
}

int taskMapBendEdgeCount(List<TaskMapRoutedEdge> edges) {
  return edges.where((edge) => edge.hasBend).length;
}

int taskMapRoutedEdgeCount(List<TaskMapRoutedEdge> edges) {
  return edges.where((edge) => edge.hasRoute).length;
}

/// Counts edge-section segments that cross an unrelated node rectangle.
int taskMapEdgeNodeIntersectionCount(TaskMapSceneLayout layout) {
  var count = 0;
  for (final edge in layout.edges) {
    for (final section in edge.sections) {
      for (var index = 0; index < section.length - 1; index++) {
        final start = section[index];
        final end = section[index + 1];
        for (final entry in layout.nodes.entries) {
          if (entry.key == edge.sourceId || entry.key == edge.targetId) {
            continue;
          }
          if (_segmentHitsRect(start, end, entry.value)) {
            count += 1;
          }
        }
      }
    }
  }
  return count;
}

bool taskMapLayoutsMatch(TaskMapSceneLayout left, TaskMapSceneLayout right) {
  if (!left.completed || !right.completed) {
    return left.completed == right.completed && left.error == right.error;
  }
  if (left.nodes.length != right.nodes.length || left.edges.length != right.edges.length) {
    return false;
  }
  for (final entry in left.nodes.entries) {
    final other = right.nodes[entry.key];
    if (other == null || (entry.value.topLeft - other.topLeft).distance > 0.01) {
      return false;
    }
    if ((entry.value.width - other.width).abs() > 0.01 ||
        (entry.value.height - other.height).abs() > 0.01) {
      return false;
    }
  }
  for (var index = 0; index < left.edges.length; index++) {
    final a = left.edges[index];
    final b = right.edges[index];
    if (a.id != b.id || a.sections.length != b.sections.length) {
      return false;
    }
    for (var section = 0; section < a.sections.length; section++) {
      final leftPoints = a.sections[section];
      final rightPoints = b.sections[section];
      if (leftPoints.length != rightPoints.length) {
        return false;
      }
      for (var point = 0; point < leftPoints.length; point++) {
        if ((leftPoints[point] - rightPoints[point]).distance > 0.01) {
          return false;
        }
      }
    }
  }
  return true;
}

/// How many [base] nodes move by more than 1px after [added].
int taskMapSceneMovedNodeCount(TaskMapSceneLayout base, TaskMapSceneLayout added) {
  if (!base.completed || !added.completed) {
    return base.nodes.length;
  }
  var moved = 0;
  for (final entry in base.nodes.entries) {
    final next = added.nodes[entry.key];
    if (next == null || (entry.value.center - next.center).distance > 1) {
      moved += 1;
    }
  }
  return moved;
}

bool _areaOverlap(Rect a, Rect b) {
  final left = math.max(a.left, b.left);
  final right = math.min(a.right, b.right);
  final top = math.max(a.top, b.top);
  final bottom = math.min(a.bottom, b.bottom);
  return right - left > 0.5 && bottom - top > 0.5;
}

bool _segmentHitsRect(Offset a, Offset b, Rect rect) {
  if (rect.contains(a) || rect.contains(b)) {
    return true;
  }
  final corners = [rect.topLeft, rect.topRight, rect.bottomRight, rect.bottomLeft];
  for (var index = 0; index < corners.length; index++) {
    if (_segmentsCross(a, b, corners[index], corners[(index + 1) % corners.length])) {
      return true;
    }
  }
  return false;
}

bool _segmentsCross(Offset a, Offset b, Offset c, Offset d) {
  double cross(Offset p, Offset q, Offset r) {
    return (q.dx - p.dx) * (r.dy - p.dy) - (q.dy - p.dy) * (r.dx - p.dx);
  }

  final d1 = cross(c, d, a);
  final d2 = cross(c, d, b);
  final d3 = cross(a, b, c);
  final d4 = cross(a, b, d);
  return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) &&
      ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
}

SecretaryObject _fixtureObject({
  required String id,
  required String title,
  String kind = 'task',
}) {
  return SecretaryObject(
    id: id,
    kind: kind,
    title: title,
    metadata: const {},
    origin: 'user',
    state: 'confirmed',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  );
}

SecretaryEdge _fixtureEdge(String sourceId, String targetId, String type) {
  return SecretaryEdge(
    id: '$sourceId-$targetId',
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

/// One Task, three neighboring Tasks, and twelve evidence nodes already linked
/// to the center. The unrelated node is loaded but not in the flower.
TaskMapFixture taskMapFlowerFixture() {
  const root = 'flower-task';
  final nodes = <SecretaryObject>[
    _fixtureObject(id: root, title: 'Центральная задача'),
    for (var index = 0; index < 3; index++)
      _fixtureObject(id: 'flower-neighbor-$index', title: 'Соседняя задача $index'),
    for (var index = 0; index < 12; index++)
      _fixtureObject(
        id: 'flower-evidence-$index',
        title: 'Контекст $index',
        kind: 'email',
      ),
    _fixtureObject(id: 'flower-unrelated', title: 'Чужой объект', kind: 'file'),
  ];
  final edges = <SecretaryEdge>[
    for (var index = 0; index < 3; index++)
      _fixtureEdge(root, 'flower-neighbor-$index', 'depends_on'),
    for (var index = 0; index < 12; index++)
      _fixtureEdge(root, 'flower-evidence-$index', 'references'),
  ];
  return TaskMapFixture(nodes: nodes, edges: edges, rootId: root);
}

/// Eight Tasks with existing Task links and twenty evidence nodes.
TaskMapFixture taskMapClusterFixture() {
  const root = 'cluster-task-0';
  final nodes = <SecretaryObject>[
    for (var index = 0; index < 8; index++)
      _fixtureObject(id: 'cluster-task-$index', title: 'Задача кластера $index'),
    for (var index = 0; index < 20; index++)
      _fixtureObject(
        id: 'cluster-evidence-$index',
        title: 'Контекст кластера $index',
        kind: 'email',
      ),
  ];
  final edges = <SecretaryEdge>[
    for (var index = 0; index < 7; index++)
      _fixtureEdge('cluster-task-$index', 'cluster-task-${index + 1}', 'depends_on'),
    _fixtureEdge('cluster-task-0', 'cluster-task-3', 'depends_on'),
    _fixtureEdge('cluster-task-2', 'cluster-task-5', 'depends_on'),
    _fixtureEdge('cluster-task-1', 'cluster-task-6', 'depends_on'),
    for (var index = 0; index < 20; index++)
      _fixtureEdge('cluster-task-${index % 8}', 'cluster-evidence-$index', 'references'),
  ];
  return TaskMapFixture(nodes: nodes, edges: edges, rootId: root);
}

TaskMapFixture taskMapFixtureWithEvidenceLeaf(TaskMapFixture fixture) {
  final leafId = '${fixture.rootId}-extra-evidence';
  return TaskMapFixture(
    nodes: [
      ...fixture.nodes,
      _fixtureObject(id: leafId, title: 'Дополнительный контекст', kind: 'email'),
    ],
    edges: [
      ...fixture.edges,
      _fixtureEdge(fixture.rootId, leafId, 'references'),
    ],
    rootId: fixture.rootId,
  );
}
